#!/usr/bin/env python3
"""Cross-runtime consistency check for the proto-form "alternation star" transform.

It's implemented twice — alt() in Python (stedt/render/text.py, server render) and altstar() in JS
(web/src/rows.js, client search/reconstructions). They MUST agree, or the same proto-form renders
differently server-side vs. in client search (a real risk: the etymon-row consolidation hinged on
exactly this). This runs BOTH over a corpus — hand-picked edge cases plus every distinct proto-form
in stedt.sqlite — and asserts identical output. Exits non-zero on any mismatch, so it doubles as a
CI / pre-commit gate. Needs `node` on PATH.

    python stedt/dev/check_altstar.py
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from stedt.render.text import alt  # noqa: E402

# Edge cases that exercise every branch: leading star (incl. doubled), ⪤ with/without an existing
# star and with/without surrounding spaces, multiple alternants, empty.
EDGE = ["", "m-gam", "*a", " * a", "**d-k-wiy", "a⪤b", "a ⪤ b", "a⪤*b", "a⪤ *b", "a⪤b⪤c", "*s-tak⪤*tak"]


def corpus():
    cases = list(EDGE)
    db = os.path.join(ROOT, "stedt.sqlite")
    if os.path.exists(db):
        import sqlite3
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        cases += [r[0] for r in c.execute("SELECT DISTINCT protoform FROM etyma WHERE protoform IS NOT NULL")]
        c.close()
    else:
        print("(stedt.sqlite not found — testing edge cases only)")
    return cases


def altstar_js(items):
    """Run web/src/rows.js altstar() over the corpus via node, returning the results."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(items, f)
        path = f.name
    try:
        rows_url = "file://" + os.path.join(ROOT, "web/src/rows.js")
        code = (
            f"import {{altstar}} from {json.dumps(rows_url)};"
            f"import {{readFileSync}} from 'node:fs';"
            f"const xs=JSON.parse(readFileSync({json.dumps(path)},'utf8'));"
            f"process.stdout.write(JSON.stringify(xs.map(altstar)));"
        )
        out = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, check=True)
        return json.loads(out.stdout)
    finally:
        os.unlink(path)


def main():
    items = corpus()
    py = [alt(x) for x in items]
    js = altstar_js(items)
    mismatches = [(x, p, j) for x, p, j in zip(items, py, js) if p != j]
    print(f"checked {len(items):,} proto-forms (incl. {len(EDGE)} edge cases)")
    if mismatches:
        print(f"MISMATCH — alt() (Python) and altstar() (JS) disagree on {len(mismatches)}:")
        for x, p, j in mismatches[:20]:
            print(f"  in={x!r}  alt()={p!r}  altstar()={j!r}")
        sys.exit(1)
    print("alt() and altstar() agree ✓")


if __name__ == "__main__":
    main()
