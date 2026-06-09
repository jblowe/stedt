#!/usr/bin/env python3
"""Golden-output snapshot harness — prove a refactor didn't change the rendered site.

The read site is fully deterministic: every page is a pure function of `data/` (the only
date — the citation "Accessed" stamp — is filled in client-side, so the HTML ships
identical run to run). That lets us verify refactors by *byte comparison*: snapshot the
site before a change, snapshot it after, diff. An output-preserving refactor produces an
empty diff; an intentional change produces a small, reviewable one.

This wraps the REAL build modules (stedt.build.static + stedt.legacy.build_site) so the
snapshot covers exactly the pages that ship — there is no second copy of the page list to
drift out of sync. It then writes a sorted `MANIFEST.sha256` over every text output
(HTML/CSS/JS), the fast way to see *which* pages moved without diffing hundreds of MB.

Snapshots are built with STEDT_BASE='' (root-relative links) for clean, short diffs; they
are for COMPARISON, not deployment. Use the same settings on both sides.

Usage
-----
    # capture a baseline, make your change, capture again, compare:
    stedt snapshot build .snapshots/before
    #   ...refactor...
    stedt snapshot build .snapshots/after
    stedt snapshot compare .snapshots/before .snapshots/after

    # fast smoke run (caps entities per kind via STEDT_LIMIT):
    stedt snapshot build .snapshots/quick --limit 25

    # also rebuild stedt.sqlite/search DBs from data/ first (use when data/ or the
    # DB-build pipeline changed, not for a pure render-layer refactor):
    stedt snapshot build .snapshots/after --rebuild-db

Compare exits non-zero when anything differs, so it doubles as a CI/pre-commit gate.
"""
import argparse
import hashlib
import os
import subprocess
import sys

from stedt.paths import ROOT, DB

# Files whose bytes are real render output we want to track. Everything else under site/
# is a verbatim copy (the WASM search DBs, fonts, images) — excluded so the manifest stays
# focused and a 45 MB binary diff never drowns out a one-line HTML change.
TEXT_EXT = {".html", ".css", ".js", ".json", ".txt", ".xml", ".nojekyll"}
SKIP_NAMES = {"MANIFEST.sha256"}


def _run(module, out_dir, limit):
    """Run one build module (python -m) into out_dir with a pinned, reproducible env."""
    env = dict(os.environ)
    env["STEDT_OUT"] = out_dir
    env["STEDT_BASE"] = ""            # root-relative -> clean diffs; comparison only, not deploy
    # Pin the cache-bust versions so a diff reflects only rendered content, not the data/pipeline
    # content hash (which legitimately changes when a build file is renamed or moved).
    env["STEDT_DB_VERSION"] = "snapshot"
    env["STEDT_LEGACY_VER"] = "snapshot"
    if limit:
        env["STEDT_LIMIT"] = str(limit)
    r = subprocess.run([sys.executable, "-m", module], cwd=ROOT, env=env)
    if r.returncode != 0:
        sys.exit(f"snapshot: {module} failed (exit {r.returncode})")


def _manifest_lines(root):
    """Yield '<sha256>  <relpath>' for every tracked text file under root, sorted by path."""
    rows = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name in SKIP_NAMES:
                continue
            ext = name[name.rfind("."):] if "." in name else ""
            if name not in TEXT_EXT and ext not in TEXT_EXT:
                continue
            fp = os.path.join(dirpath, name)
            h = hashlib.sha256()
            with open(fp, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            rows.append((os.path.relpath(fp, root), h.hexdigest()))
    rows.sort()
    return [f"{sha}  {rel}" for rel, sha in rows]


def cmd_build(args):
    out = os.path.abspath(args.dir)
    os.makedirs(out, exist_ok=True)

    # Pin the hash seed so the snapshot is reproducible. Rendering is hash-seed-independent
    # today (verified: two builds in different processes are byte-identical), but a future
    # refactor could let set-iteration order leak into output; pinning keeps the harness a
    # clean signal instead of flagging seed noise as a change. Inherited by every subprocess.
    os.environ["PYTHONHASHSEED"] = "0"

    if args.rebuild_db:
        # data/ -> stedt.sqlite -> search.sqlite3 (and the legacy search DB). Only needed when
        # the data or the DB-build pipeline changed; a render-only refactor leaves these alone.
        for module in ("stedt.build.from_tsv", "stedt.build.search_db", "stedt.legacy.search_db"):
            r = subprocess.run([sys.executable, "-m", module], cwd=ROOT)
            if r.returncode != 0:
                sys.exit(f"snapshot: {module} failed (exit {r.returncode})")

    if not os.path.exists(DB):
        sys.exit("snapshot: stedt.sqlite missing — run with --rebuild-db, or `stedt build` first")

    _run("stedt.build.static", out, args.limit)         # rmtrees + rebuilds out/  (modern site)
    if not args.no_legacy:
        _run("stedt.legacy.build_site", out, args.limit)   # adds out/_legacy/  (legacy clone)

    lines = _manifest_lines(out)
    with open(os.path.join(out, "MANIFEST.sha256"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nsnapshot: {len(lines)} text outputs -> {out}/MANIFEST.sha256")


def _read_manifest(d):
    p = os.path.join(d, "MANIFEST.sha256")
    if not os.path.exists(p):
        sys.exit(f"snapshot: no MANIFEST.sha256 in {d} — run `snapshot.py build {d}` first")
    out = {}
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            sha, rel = line.split("  ", 1)
            out[rel] = sha
    return out


def cmd_compare(args):
    a, b = _read_manifest(args.before), _read_manifest(args.after)
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    changed = sorted(r for r in (set(a) & set(b)) if a[r] != b[r])

    if not (added or removed or changed):
        print(f"IDENTICAL — {len(a)} outputs match byte-for-byte.")
        return

    print(f"DIFFERS — {len(changed)} changed, {len(added)} added, {len(removed)} removed "
          f"(of {len(a)} -> {len(b)} outputs)\n")
    show = lambda label, items: [print(f"  {label} {r}") for r in items[:args.max_list]]
    if removed:
        show("removed", removed)
        if len(removed) > args.max_list:
            print(f"  … +{len(removed) - args.max_list} more removed")
    if added:
        show("added  ", added)
        if len(added) > args.max_list:
            print(f"  … +{len(added) - args.max_list} more added")
    if changed:
        show("changed", changed)
        if len(changed) > args.max_list:
            print(f"  … +{len(changed) - args.max_list} more changed")
        print(f"\nInspect a change with:\n"
              f"  diff -u {args.before}/<path> {args.after}/<path>\n"
              f"  # or, for color: git diff --no-index {args.before}/<path> {args.after}/<path>")
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="render a snapshot of the site into DIR")
    b.add_argument("dir")
    b.add_argument("--limit", type=int, default=0, help="cap entities per kind (fast smoke run)")
    b.add_argument("--no-legacy", action="store_true", help="skip the /_legacy/ clone")
    b.add_argument("--rebuild-db", action="store_true", help="rebuild stedt.sqlite + search DBs from data/ first")
    b.set_defaults(func=cmd_build)

    c = sub.add_parser("compare", help="diff two snapshot manifests; exits non-zero if they differ")
    c.add_argument("before")
    c.add_argument("after")
    c.add_argument("--max-list", type=int, default=40, help="max paths to list per category")
    c.set_defaults(func=cmd_compare)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
