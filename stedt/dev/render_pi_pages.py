#!/usr/bin/env python3
"""Pre-render the per-language pages of the Phonological Inventories monograph (Namkung, ed. 1996,
STEDT Monograph #3) to trimmed grayscale PNGs — one per distinct physical page — under
static/pubs/pi/.

The language page embeds the image of that language's inventory page, so the reader sees just the
page (no PDF-viewer chrome, no scroll). Output is committed: an immutable vendored derivative of the
vendored PDF, so normal builds need no PDF tooling. Re-run only when the data changes the set of
pi_page values. Needs poppler-utils (pdftoppm) + ImageMagick (convert).

    python3 -m stedt.dev.render_pi_pages
"""

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

from stedt.paths import DB, STATIC

PDF = os.path.join(STATIC, "pubs", "STEDT_Monograph3_Phonological-Inv-TB.pdf")
OUT = os.path.join(STATIC, "pubs", "pi")
DPI = 200  # ~1270px wide after trim — crisp at the 600px display box on retina
OFFSET = 26  # front matter: printed pi_page + 26 = physical PDF page (SYNC with render/language.py)


def main():
    for tool in ("pdftoppm", "convert"):
        if not shutil.which(tool):
            sys.exit(f"need {tool} on PATH (poppler-utils / imagemagick)")
    if not os.path.exists(PDF):
        sys.exit(f"missing monograph PDF at {PDF}")
    c = sqlite3.connect(DB)
    pages = sorted({r[0] + OFFSET for r in c.execute("SELECT DISTINCT pi_page FROM languagenames WHERE coalesce(pi_page,0)!=0")})
    c.close()
    os.makedirs(OUT, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        raw = os.path.join(tmp, "raw")
        for i, p in enumerate(pages, 1):
            subprocess.run(
                ["pdftoppm", "-gray", "-r", str(DPI), "-f", str(p), "-l", str(p), "-png", "-singlefile", PDF, raw],
                check=True,
            )
            subprocess.run(
                ["convert", raw + ".png", "-trim", "+repage", "-strip",
                 "-define", "png:compression-level=9", os.path.join(OUT, f"p{p}.png")],
                check=True,
            )
            if i % 50 == 0:
                print(f"  {i}/{len(pages)}")
    print(f"rendered {len(pages)} inventory pages -> {OUT}")


if __name__ == "__main__":
    main()
