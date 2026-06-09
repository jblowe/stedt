#!/usr/bin/env python3
"""Lossless gate for the all-TSV round-trip.

  baseline.sqlite → stedt.dev.export_tsv → TSV → stedt.build.from_tsv → rebuilt.sqlite
  assert: per-table semantic fingerprint(rebuilt) == fingerprint(baseline)

Args: BASELINE_SQLITE REBUILT_SQLITE. Surrogate row-ids that carry no cross-references (and
are assigned by iteration order) are excluded from the comparison; everything else must match.
"""

import sqlite3, hashlib, sys

# columns that are internal surrogate keys (enumeration order), not semantic content
DROP = {"mesoroots": {"id"}, "chapters": {"id"}, "glosswords": {"id"}, "notes": {"noteid"}}


def fingerprint(path):
    db = sqlite3.connect(path)
    c = db.cursor()
    tabs = [
        r[0]
        for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '%_fts%' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    out = {}
    for t in tabs:
        cols = [d[1] for d in c.execute(f"PRAGMA table_info({t})")]
        keep = [x for x in cols if x not in DROP.get(t, set())]
        rowset = c.execute(f"SELECT {','.join(keep)} FROM {t}").fetchall()
        blob = repr(sorted(repr(r) for r in rowset)).encode()
        out[t] = (len(rowset), hashlib.sha256(blob).hexdigest()[:16])
    db.close()
    return out


def main():
    base, rebuilt = sys.argv[1], sys.argv[2]
    a, b = fingerprint(base), fingerprint(rebuilt)
    ok = True
    for t in sorted(set(a) | set(b)):
        av, bv = a.get(t), b.get(t)
        mark = "OK " if av == bv else "DIFF"
        if av != bv:
            ok = False
        print(f"  {mark} {t:18} baseline={av}  rebuilt={bv}")
    print("\nGATE PASS — semantic content identical" if ok else "\nGATE FAIL — see DIFF rows above")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
