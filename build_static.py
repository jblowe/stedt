#!/usr/bin/env python3
"""Prerender the STEDT read site to static HTML for GitHub Pages.

Calls serve.py's render functions for every stable route — home, about, the browse
indexes, and every etymon / language / source / thesaurus node — and writes each to
site/<path>/index.html. Search runs client-side (WASM SQLite over search.db;
see build_search_db.py + src/search.js).

GitHub Pages serves a *project* site under a subpath (https://larc-iu.github.io/stedt/),
so each page's root-absolute links are rewritten with the /stedt prefix and a base global
is injected (window.STEDT_BASE) for the client search's result links.

Usage:  python3 build_static.py            # full build -> site/  (needs stedt.sqlite)
Env:    STEDT_BASE   subpath prefix (default /stedt; use '' for a custom apex domain)
        STEDT_OUT    output dir (default site)
        STEDT_LIMIT  cap entities per kind for quick local testing (0 = all)
"""
import glob
import hashlib
import os
import re
import shutil
import time

import serve                                # noqa: E402

BASE = os.environ.get("STEDT_BASE", "/stedt").rstrip("/")
OUT = os.environ.get("STEDT_OUT", "site")
LIMIT = int(os.environ.get("STEDT_LIMIT", "0"))

# Add the subpath to root-absolute href/src/action (but not protocol-relative //), and inject
# the base + data version so the client search can prefix result URLs and cache-key the DB.
_LINK = re.compile(r'(\b(?:href|src|action)=")/(?!/)')


def data_version():
    """A content hash of data/ — changes only when the source data changes, so the search DB
    is cache-busted (search.sqlite3?v=...) on data updates rather than on every deploy."""
    h = hashlib.sha256()
    for p in sorted(glob.glob(os.path.join(serve.DATA, "**", "*"), recursive=True)):
        if os.path.isfile(p):
            h.update(p.encode("utf-8"))
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
    return h.hexdigest()[:16]


DB_VERSION = ""   # set in main()


def rewrite(s):
    if BASE:
        s = _LINK.sub(lambda m: m.group(1) + BASE + "/", s)
    head = f'<head><script>window.STEDT_BASE="{BASE}";window.STEDT_DB_VERSION="{DB_VERSION}";</script>'
    return s.replace("<head>", head, 1)


_ok = 0
_fail = 0


def write(path, render):
    global _ok, _fail
    try:
        r = render()
        s = r[0] if isinstance(r, tuple) else r
    except Exception as e:
        _fail += 1
        print(f"  ! skip /{path}: {type(e).__name__}: {e}")
        return
    fp = os.path.join(OUT, path, "index.html")
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(rewrite(s))
    _ok += 1
    if _ok % 1000 == 0:
        print(f"  {_ok} pages…")


def cap(xs):
    return xs[:LIMIT] if LIMIT else xs


def main():
    global DB_VERSION
    t0 = time.time()
    DB_VERSION = data_version()
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)

    c = serve.con()
    OKE = "coalesce(upper(status),'')!='DELETE'"
    tags = cap([r[0] for r in c.execute(f"SELECT tag FROM etyma WHERE {OKE} ORDER BY tag")])
    lgids = cap([r[0] for r in c.execute("SELECT lgid FROM languagenames ORDER BY lgid")])
    srcs = cap([r[0] for r in c.execute("SELECT srcabbr FROM srcbib WHERE coalesce(srcabbr,'')!='' ORDER BY srcabbr")])
    semks = cap([r[0] for r in c.execute("SELECT semkey FROM chapters WHERE coalesce(semkey,'')!='' ORDER BY semkey")])
    c.close()

    write("", serve.home)
    write("about", serve.about)
    write("reconstructions", serve.reconstructions)
    write("languages", serve.languages_index)
    write("sources", serve.sources_index)
    write("thesaurus", lambda: serve.thesaurus(None))
    write("search", lambda: serve.search_page(""))   # client-side results shell (reads ?q=)
    for t in tags:
        write(f"etymon/{t}", lambda t=t: serve.etymon(t))
    for g in lgids:
        write(f"language/{g}", lambda g=g: serve.language(g))
    for s in srcs:
        write(f"source/{s}", lambda s=s: serve.source(s))
    for k in semks:
        write(f"thesaurus/{k}", lambda k=k: serve.thesaurus(k))

    src_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "search.sqlite3")
    if os.path.exists(src_db):
        shutil.copy(src_db, os.path.join(OUT, "search.sqlite3"))
    open(os.path.join(OUT, ".nojekyll"), "w").close()   # don't let Pages run Jekyll on our files
    print(f"Done: {_ok} pages, {_fail} skipped, {time.time() - t0:.0f}s "
          f"(BASE={BASE!r}, LIMIT={LIMIT or 'all'})")


if __name__ == "__main__":
    main()
