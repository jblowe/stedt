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

import glob
import hashlib
import os
import shutil
import time

from stedt.paths import ROOT, SITE, LEGACY_DB

BASE = os.environ.get("STEDT_BASE", "/stedt").rstrip("/")
LEGACY_BASE = BASE + "/_legacy"
OUT = os.environ.get("STEDT_OUT") or SITE
LEGACY_OUT = os.path.join(OUT, "_legacy")
LIMIT = int(os.environ.get("STEDT_LIMIT", "0"))
ASSETS = os.path.join(os.path.dirname(__file__), "assets")  # rootcanal front-end (ships with the package)


def data_version():
    """Cache-bust the legacy DB by hashing data/ + the legacy DB builder, relativized to the repo
    root, so the key changes when the data OR the schema changes but not on every deploy. Mirrors
    the modern build's data_version()."""
    from stedt import render

    h = hashlib.sha256()
    paths = sorted(glob.glob(os.path.join(render.DATA, "**", "*"), recursive=True))
    paths.append(os.path.join(os.path.dirname(__file__), "search_db.py"))
    for p in paths:
        if os.path.isfile(p):
            h.update(os.path.relpath(p, ROOT).encode("utf-8"))
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
    return h.hexdigest()[:16]


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
    srcs = [r[0] for r in c.execute("""SELECT DISTINCT ln.srcabbr FROM srcbib sb
        JOIN languagenames ln ON ln.srcabbr=sb.srcabbr JOIN lexicon l ON l.lgid=ln.lgid
        WHERE coalesce(l.status,'') NOT IN ('HIDE','DELETED') AND coalesce(sb.srcabbr,'')!=''""")]
    semks = [r[0] for r in c.execute("SELECT semkey FROM chapters WHERE coalesce(semkey,'')!=''")]
    grpids = [r[0] for r in c.execute("SELECT grpid FROM languagegroups ORDER BY grpid")]
    # (grpid,lgid) pairs that reflex language-links point at → redirect stubs that scroll the group page
    lg_pairs = c.execute("""SELECT ln.grpid, ln.lgid FROM languagenames ln JOIN lexicon l ON l.lgid=ln.lgid
        WHERE coalesce(ln.lgcode,0)!=0 AND coalesce(l.status,'') NOT IN ('HIDE','DELETED')
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
    for r in c.execute("""SELECT ln.srcabbr, l.rn, l.reflex, l.gloss, l.gfn, l.lgid, ln.language, l.srcid
                          FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid
                          WHERE coalesce(ln.srcabbr,'')!='' AND ln.srcabbr!='SIL-Nuosu'"""):
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


if __name__ == "__main__":
    main()
