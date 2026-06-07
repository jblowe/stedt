#!/usr/bin/env python3
"""Apply a *shallow* etymon edit to a data/etyma/<tag>.yaml document.

Shared by the contribution pipeline — the GitHub Action that turns a "Suggest an
edit" Issue Form submission into a pull request (see .github/workflows/suggest-edit.yml
and .github/scripts/apply_suggested_edit.py). Kept deliberately small: only the handful
of shallow fields a guided form should touch. Deep structural edits (mesoroots, cognate
retagging, phonology) stay in the raw-YAML / "Edit on GitHub" lane.

The dumper below must stay byte-compatible with export_files.py's dumper so that a
one-field edit re-serializes to a clean, minimal diff (no spurious reflow). _NEL holds
U+0085 NEL, U+2028 LINE SEPARATOR, U+2029 PARAGRAPH SEPARATOR — chars PyYAML would
otherwise fold to spaces; double-quoting forces escaping. (Codepoints verified equal to
export_files.py's _NEL.)
"""
import yaml

# Shallow scalar fields the "Suggest an edit" form may change. A blank submission means
# "leave unchanged" — never delete — which is fail-safe for a public form and for the
# GitHub mobile app, where URL prefill is dropped and the contributor would otherwise
# see (and submit) empty fields. Clearing a field is rare and stays a maintainer/YAML job.
SCALAR_FIELDS = ('protoform', 'gloss', 'semkey', 'references')


class _YD(yaml.SafeDumper):
    pass


_NEL = ('\x85', ' ', ' ')


def _ystr(d, s):
    if any(ch in s for ch in _NEL):
        return d.represent_scalar('tag:yaml.org,2002:str', s, style='"')
    return d.represent_scalar('tag:yaml.org,2002:str', s, style='|' if '\n' in s else None)


_YD.add_representer(str, _ystr)


def ydump(o):
    return yaml.dump(o, Dumper=_YD, allow_unicode=True, sort_keys=False, width=100)


def apply_edit(doc, fields):
    """Mutate `doc` (a loaded etymon mapping) in place from submitted form `fields`.

    `fields` maps form keys -> submitted strings. Semantics:
      - protoform / gloss / semkey / references: a non-blank value replaces the current
        value; a blank value leaves the field untouched (we never delete via the form).
      - newnote: if non-blank, append {type: 'T', text: ...} to the notes list.

    The etymon `tag` is never touched — it is a stable citation id.

    Returns (changed: bool, problems: list[str]). `problems` are reasons a maintainer
    would reject the change outright; their presence means "don't open a PR" and the
    message is surfaced back to the contributor. Referential checks (e.g. semkey must be
    a real thesaurus node) are left to validate.py, which the Action runs afterwards.
    """
    changed = False
    g = lambda k: (fields.get(k) or '').strip()

    for k in SCALAR_FIELDS:
        if k not in fields:          # field absent from the payload entirely -> ignore
            continue
        v = g(k)
        if v == '':                  # blank -> leave unchanged
            continue
        if str(doc.get(k, '')) != v:
            doc[k] = v
            changed = True

    note = g('newnote')
    if note:
        doc.setdefault('notes', []).append({'type': 'T', 'text': note})
        changed = True

    problems = []
    if not str(doc.get('protoform') or '').strip():
        problems.append("the proto-form is empty")
    if not str(doc.get('gloss') or '').strip():
        problems.append("the gloss is empty")

    return changed, problems
