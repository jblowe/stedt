#!/usr/bin/env python3
"""Prerender the /_legacy/ rootcanal clone into site/_legacy/.

Runs AFTER build_static.py (which rmtrees + builds site/); this script ONLY writes under site/_legacy/
and never removes site/. Copies rootcanal's verbatim front-end assets (legacy_assets/) + legacy.sqlite3,
renders the public pages via legacy_render.py, and stamps a data-version for the WASM DB cache key.
The legacy-shim JS bundle is produced separately by `npm run build:legacy`.

Env:  STEDT_BASE   main-site subpath prefix (default /stedt; '' for apex/localhost). The legacy base
                   is BASE + '/_legacy'.
      STEDT_OUT    output dir (default site)
      STEDT_LIMIT  cap etyma pages for quick local testing (0 = all)
"""
import glob
import hashlib
import os
import shutil
import time

BASE = os.environ.get("STEDT_BASE", "/stedt").rstrip("/")
LEGACY_BASE = BASE + "/_legacy"
OUT = os.environ.get("STEDT_OUT", "site")
LEGACY_OUT = os.path.join(OUT, "_legacy")
LIMIT = int(os.environ.get("STEDT_LIMIT", "0"))
HERE = os.path.dirname(os.path.abspath(__file__))


def data_version():
    """Cache-bust the legacy DB by hashing data/ + the legacy DB builder (so the key changes when the
    data OR the schema changes, not on every deploy). Mirrors build_static.data_version()."""
    import render
    h = hashlib.sha256()
    paths = sorted(glob.glob(os.path.join(render.DATA, "**", "*"), recursive=True))
    paths.append(os.path.join(HERE, "build_legacy_search_db.py"))
    for p in paths:
        if os.path.isfile(p):
            h.update(os.path.relpath(p, HERE).encode("utf-8"))
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
    return h.hexdigest()[:16]


def main():
    t0 = time.time()
    # Configure the renderer's base + cache version BEFORE importing its page fns build URLs.
    os.environ["STEDT_LEGACY_BASE"] = LEGACY_BASE
    os.environ["STEDT_LEGACY_VER"] = data_version()
    import legacy_render as L

    os.makedirs(LEGACY_OUT, exist_ok=True)

    # 1) verbatim rootcanal assets (styles/js/scriptaculous/img) -> site/_legacy/
    for sub in ("styles", "js", "scriptaculous", "img"):
        src = os.path.join(HERE, "legacy_assets", sub)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(LEGACY_OUT, sub), dirs_exist_ok=True)

    # 2) the WASM search DB
    db = os.path.join(HERE, "legacy.sqlite3")
    if os.path.exists(db):
        shutil.copy(db, os.path.join(LEGACY_OUT, "legacy.sqlite3"))
    else:
        print("  ! legacy.sqlite3 missing — run build_legacy_search_db.py first")

    # 3) pages
    n = 0; fails = 0
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

    # etymon pages (citation core)
    if hasattr(L, "legacy_etymon"):
        c = L.render.con()
        tags = [r[0] for r in c.execute(
            "SELECT tag FROM etyma WHERE coalesce(upper(status),'')!='DELETE' ORDER BY tag")]
        c.close()
        if LIMIT:
            tags = tags[:LIMIT]
        for t in tags:
            write(f"etymon/{t}", (lambda t=t: L.legacy_etymon(t)))

    print(f"legacy: {n} pages, {fails} skipped -> {LEGACY_OUT} (base={LEGACY_BASE!r}, "
          f"ver={os.environ['STEDT_LEGACY_VER']}, {time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
