#!/usr/bin/env python3
"""Turn a "Suggest an edit" Issue Form submission into a staged etymon edit.

Pure stdlib + PyYAML; no third-party Actions. Parses the rendered issue-form markdown,
applies the shallow change to data/etyma/<tag>.yaml, and reports the outcome for the
workflow (.github/workflows/suggest-edit.yml). The workflow validates the dataset and
opens the PR; this script only parses + applies + reports.

Inputs (environment):
  ISSUE_BODY     rendered issue-form markdown (github.event.issue.body)
  ISSUE_NUMBER   issue number (for crediting + auto-close link)
  ISSUE_AUTHOR   GitHub login of the issue author (verified attribution)
  GITHUB_OUTPUT  provided by Actions; we append `key=value` lines (falls back to stdout)

Outputs (to GITHUB_OUTPUT):
  status = applied | nochange | rejected
  tag    = <etymon tag>            (when known)
  reason = <one-line message>      (when nochange / rejected)
On `applied`: data/etyma/<tag>.yaml is rewritten in the working tree and pr_body.md is
written at the repo root. Exit code is always 0 — a rejection is a handled outcome (the
workflow comments it back), not a workflow failure.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))   # .github/scripts -> repo root
sys.path.insert(0, REPO_ROOT)

import yaml                                  # noqa: E402
from etymon_edit import apply_edit, ydump    # noqa: E402

DATA = os.path.join(REPO_ROOT, "data")

# Issue-form field label (lower-cased) -> our field key. Must match the `label:` values
# in .github/ISSUE_TEMPLATE/suggest-edit.yml.
LABELS = {
    "etymon number": "tag",
    "proto-form": "protoform",
    "gloss": "gloss",
    "semantic key": "semkey",
    "references": "references",
    "add a note": "newnote",
    "what & why": "summary",
}


def parse_issue_form(body):
    """A rendered issue form is a series of `### Label` headings each followed by the
    submitted value (or the literal `_No response_` when left blank)."""
    fields = {}
    parts = re.split(r'(?m)^###[ \t]+(.+?)[ \t]*$', body or "")
    # parts = [preamble, label1, value1, label2, value2, ...]
    for i in range(1, len(parts) - 1, 2):
        label = parts[i].strip().lower()
        value = parts[i + 1].strip()
        if value == "_No response_":
            value = ""
        key = LABELS.get(label)
        if key is not None:
            fields[key] = value
    return fields


def out(**kv):
    path = os.environ.get("GITHUB_OUTPUT")
    lines = [f"{k}={v}" for k, v in kv.items()]
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))


def finish(status, *, tag=None, reason=None):
    kv = {"status": status}
    if tag is not None:
        kv["tag"] = tag
    if reason is not None:
        kv["reason"] = reason          # keep single-line; consumed by `gh issue comment`
    out(**kv)
    print(f"{status.upper()}" + (f": {reason}" if reason else ""))
    sys.exit(0)


def main():
    fields = parse_issue_form(os.environ.get("ISSUE_BODY", ""))

    m = re.search(r'\d+', fields.get("tag", "") or "")
    if not m:
        finish("rejected", reason="I couldn't read a valid etymon number from the form.")
    tag = int(m.group())

    path = os.path.join(DATA, "etyma", f"{tag}.yaml")
    if not os.path.exists(path):
        finish("rejected", tag=tag, reason=f"etymon #{tag} doesn't exist (no data/etyma/{tag}.yaml).")

    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict):
        finish("rejected", tag=tag, reason=f"the file for etymon #{tag} isn't a valid entry.")

    changed, problems = apply_edit(doc, fields)
    if problems:
        finish("rejected", tag=tag, reason="; ".join(problems) + ".")
    if not changed:
        finish("nochange", tag=tag,
               reason="no change detected — every field already matches the current entry.")

    with open(path, "w", encoding="utf-8") as f:
        f.write(ydump(doc))

    author = (os.environ.get("ISSUE_AUTHOR") or "").strip()
    issue = (os.environ.get("ISSUE_NUMBER") or "").strip()
    summary = (fields.get("summary") or "").strip() or "_(no summary provided)_"
    credit = f"@{author}" if author else "a contributor"
    pr_body = (
        f"Suggested by {credit} via #{issue}.\n\n"
        f"**What & why:** {summary}\n\n"
        f"A shallow edit to `data/etyma/{tag}.yaml`. `validate.py` passed in the Action "
        f"before this PR was opened; a maintainer should still review the content.\n\n"
        f"Closes #{issue}\n"
    )
    with open(os.path.join(REPO_ROOT, "pr_body.md"), "w", encoding="utf-8") as f:
        f.write(pr_body)

    finish("applied", tag=tag)


if __name__ == "__main__":
    main()
