#!/usr/bin/env python3
"""Prerender the /_legacy/ rootcanal clone into site/_legacy/.

Runs AFTER the modern site build (which rmtrees + builds site/); this writes only under
site/_legacy/ and never removes site/. Copies the verbatim rootcanal front-end assets (assets/)
+ legacy.sqlite3, renders the public pages via stedt.legacy.render, and stamps a data-version for
the WASM DB cache key. The legacy-shim JS bundle is produced separately by `npm run build:legacy`.

Env:  STEDT_BASE   main-site subpath prefix (default /stedt; '' for apex/localhost). The legacy
                   base is BASE + '/_legacy'.
      STEDT_OUT    output dir (default site/)
      STEDT_LIMIT  cap etyma pages for quick local testing (0 = all)
"""

import os
import shutil
import sys
import time

from stedt.paths import SITE, LEGACY_DB, STATIC

BASE = os.environ.get("STEDT_BASE", "/stedt").rstrip("/")
LEGACY_BASE = BASE + "/_legacy"
OUT = os.environ.get("STEDT_OUT") or SITE
LEGACY_OUT = os.path.join(OUT, "_legacy")
LIMIT = int(os.environ.get("STEDT_LIMIT", "0"))
ASSETS = os.path.join(os.path.dirname(__file__), "assets")  # rootcanal front-end (ships with the package)


def data_version():
    """Cache-bust the legacy DB: the shared dependency-closure hash (data/ + this builder + the
    render_note pipeline whose HTML is baked into legacy.sqlite3 — see stedt/build/version.py)."""
    from stedt.build.version import data_version as dv

    return dv(os.path.join(os.path.dirname(__file__), "search_db.py"))


def main():
    t0 = time.time()
    # Configure the renderer's base + cache version BEFORE importing its page fns build URLs.
    os.environ["STEDT_LEGACY_BASE"] = LEGACY_BASE
    # Honor a pre-set version (the snapshot harness pins it); otherwise it's a data content hash.
    os.environ["STEDT_LEGACY_VER"] = os.environ.get("STEDT_LEGACY_VER") or data_version()
    from stedt.legacy import render as L

    os.makedirs(LEGACY_OUT, exist_ok=True)

    # 1) verbatim rootcanal assets (styles/js/scriptaculous/img) -> site/_legacy/
    for sub in ("styles", "js", "scriptaculous", "img"):
        src = os.path.join(ASSETS, sub)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(LEGACY_OUT, sub), dirs_exist_ok=True)

    # 1b) the "Phon. Inventory" viewer + the monograph it embeds. rootcanal's column links to
    #     phon_inv.html?page=N (N already = printed page + 26pp front matter); the original fed N to
    #     Google Docs Viewer, dead since ~2021, so we host the PDF ourselves. The PDF is the main
    #     site's shared publication (static/pubs/) — copy it in so the subtree stays self-contained.
    shutil.copy(os.path.join(ASSETS, "phon_inv.html"), os.path.join(LEGACY_OUT, "phon_inv.html"))
    pi_pdf = "STEDT_Monograph3_Phonological-Inv-TB.pdf"
    os.makedirs(os.path.join(LEGACY_OUT, "pubs"), exist_ok=True)
    shutil.copy(os.path.join(STATIC, "pubs", pi_pdf), os.path.join(LEGACY_OUT, "pubs", pi_pdf))

    # 2) the WASM search DB
    if os.path.exists(LEGACY_DB):
        shutil.copy(LEGACY_DB, os.path.join(LEGACY_OUT, "legacy.sqlite3"))
    else:
        print("  ! legacy.sqlite3 missing — run `stedt legacy search-db` first")

    # 3) pages
    n = 0
    fails = 0

    def write(path, fn):
        nonlocal n, fails
        try:
            s = fn()
        except Exception as e:
            fails += 1
            print(f"  ! skip /_legacy/{path}: {type(e).__name__}: {e}")
            return
        fp = os.path.join(LEGACY_OUT, path, "index.html")
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(s)
        n += 1

    write("", L.legacy_splash)
    write("gnis", L.legacy_gnis)
    write("source", L.legacy_all_sources)
    write("chapters", L.legacy_chapter_browser)

    c = L.render.con()
    tags = [r[0] for r in c.execute("SELECT tag FROM etyma WHERE coalesce(upper(status),'')!='DELETE' ORDER BY tag")]
    srcs = [r[0] for r in c.execute(f"""SELECT DISTINCT ln.srcabbr FROM srcbib sb
        JOIN languagenames ln ON ln.srcabbr=sb.srcabbr JOIN lexicon l ON l.lgid=ln.lgid
        WHERE {L.render.LEX_VISIBLE} AND coalesce(sb.srcabbr,'')!=''""")]
    semks = [r[0] for r in c.execute("SELECT semkey FROM chapters WHERE coalesce(semkey,'')!=''")]
    grpids = [r[0] for r in c.execute("SELECT grpid FROM languagegroups ORDER BY grpid")]
    # (grpid,lgid) pairs that reflex language-links point at → redirect stubs that scroll the group page
    lg_pairs = c.execute(f"""SELECT ln.grpid, ln.lgid FROM languagenames ln JOIN lexicon l ON l.lgid=ln.lgid
        WHERE coalesce(ln.lgcode,0)!=0 AND {L.render.LEX_VISIBLE}
          AND ln.grpid IS NOT NULL GROUP BY ln.lgid""").fetchall()
    c.close()
    if LIMIT:
        tags, srcs, semks, grpids = tags[:LIMIT], srcs[:LIMIT], semks[:LIMIT], grpids[:LIMIT]

    for t in tags:
        write(f"etymon/{t}", (lambda t=t: L.legacy_etymon(t)))
    for s in srcs:
        write(f"source/{s}", (lambda s=s: L.legacy_source(s)))
    for k in semks:
        write(f"chap/{k}", (lambda k=k: L.legacy_chapter(k)))
    for gid in grpids:
        write(f"group/{gid}", (lambda gid=gid: L.legacy_group(gid)))
    # /group/<grpid>/<lgid> — the full selected-language page each reflex language link points at
    for gid, lgid in (lg_pairs[:LIMIT] if LIMIT else lg_pairs):
        write(f"group/{gid}/{lgid}", (lambda gid=gid, lgid=lgid: L.legacy_group(gid, lgid)))

    # static per-source raw-data TSVs (rootcanal's guest /sources/ddata export, linked from source pages)
    import csv

    ddir = os.path.join(LEGACY_OUT, "sources", "ddata")
    os.makedirs(ddir, exist_ok=True)
    c = L.render.con()
    by_src = {}
    # Withdrawn rows (HIDE/DELETED) must not ship: rootcanal's export ran behind the same status
    # gate as its listings, and the rest of this build filters them everywhere else.
    for r in c.execute(f"""SELECT ln.srcabbr, l.rn, l.reflex, l.gloss, l.gfn, l.lgid, ln.language, l.srcid
                          FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid
                          WHERE coalesce(ln.srcabbr,'')!='' AND ln.srcabbr!='SIL-Nuosu'
                            AND {L.render.LEX_VISIBLE}"""):
        by_src.setdefault(r[0], []).append(r[1:])
    c.close()
    if LIMIT:
        by_src = dict(list(by_src.items())[:LIMIT])
    for src, rws in by_src.items():
        with open(os.path.join(ddir, f"{src}.tsv"), "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(["rn", "reflex", "gloss", "gfn", "srcabbr", "lgid", "language", "srcid"])
            for rn, reflex, gloss, gfn, lgid, language, srcid in rws:
                w.writerow([rn, reflex, gloss, gfn, src, lgid, language, srcid])
    print(f"  + {len(by_src)} source data TSVs -> {ddir}")

    print(
        f"legacy: {n} pages, {fails} skipped -> {LEGACY_OUT} (base={LEGACY_BASE!r}, "
        f"ver={os.environ['STEDT_LEGACY_VER']}, {time.time() - t0:.0f}s)"
    )
    # Same contract as the modern build: a skipped page is a silent production 404 — only a
    # capped local run (STEDT_LIMIT) may ship partial output.
    if fails and not LIMIT:
        sys.exit(f"{fails} legacy page(s) failed to render — refusing to ship a partial site")


if __name__ == "__main__":
    main()
