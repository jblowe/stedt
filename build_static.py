#!/usr/bin/env python3
"""Prerender the STEDT read site to static HTML for GitHub Pages.

Calls render.py's render functions for every stable route — home, about, the browse
indexes, and every etymon / language / source / thesaurus node — and writes each to
site/<path>/index.html. Search runs client-side (WASM SQLite over search.sqlite3;
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

import render                               # noqa: E402

BASE = os.environ.get("STEDT_BASE", "/stedt").rstrip("/")
OUT = os.environ.get("STEDT_OUT", "site")
LIMIT = int(os.environ.get("STEDT_LIMIT", "0"))

# Add the subpath to root-absolute href/src/action (but not protocol-relative //), and inject
# the base + data version so the client search can prefix result URLs and cache-key the DB.
_LINK = re.compile(r'(\b(?:href|src|action)=")/(?!/)')


def data_version():
    """A content hash for cache-busting the search DB (search.sqlite3?v=...). The DB's bytes are
    a pure function of data/ AND build_search_db.py (its schema), so hash both — that way the key
    changes when the data OR the schema changes (e.g. a new column), but NOT on every deploy.
    Hashing build_search_db.py rather than the 44 MB DB itself avoids cache churn from any
    run-to-run nondeterminism in the file while still busting on every real schema change."""
    h = hashlib.sha256()
    here = os.path.dirname(os.path.abspath(__file__))
    paths = sorted(glob.glob(os.path.join(render.DATA, "**", "*"), recursive=True))
    paths.append(os.path.join(here, "build_search_db.py"))
    for p in paths:
        if os.path.isfile(p):
            h.update(os.path.relpath(p, here).encode("utf-8"))
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
        s = render()
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


def write_redirect(path, target):
    """Static redirect for a non-canonical language×source lgid -> its canonical lect page. JS
    preserves any #rn<id> fragment (the reflex lives on the canonical page); meta-refresh + link
    are the no-JS fallback. Written with BASE already applied (not run through rewrite())."""
    global _ok
    url = BASE + target
    html = ('<!doctype html><meta charset="utf-8">'
            f'<link rel="canonical" href="{url}">'
            f'<meta http-equiv="refresh" content="0; url={url}">'
            f'<script>location.replace("{url}"+location.hash)</script>'
            f'<p>Redirecting to <a href="{url}">{url}</a>…</p>')
    fp = os.path.join(OUT, path, "index.html")
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(html)
    _ok += 1


def cap(xs):
    return xs[:LIMIT] if LIMIT else xs


def main():
    global DB_VERSION
    t0 = time.time()
    DB_VERSION = data_version()
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)

    c = render.con()
    OKE = "coalesce(upper(status),'')!='DELETE'"
    tags = cap([r[0] for r in c.execute(f"SELECT tag FROM etyma WHERE {OKE} ORDER BY tag")])
    lgids = cap([r[0] for r in c.execute("SELECT lgid FROM languagenames ORDER BY lgid")])
    srcs = cap([r[0] for r in c.execute("SELECT srcabbr FROM srcbib WHERE coalesce(srcabbr,'')!='' ORDER BY srcabbr")])
    semks = cap([r[0] for r in c.execute("SELECT semkey FROM chapters WHERE coalesce(semkey,'')!='' ORDER BY semkey")])
    # The thesaurus index and breadcrumbs link top-level chapters by integer key
    # (1.0 -> /thesaurus/1), so emit those pages too or every top-level link 404s.
    roots = [r[0].split('.')[0] for r in c.execute(
        "SELECT semkey FROM chapters WHERE semkey LIKE '%.0'"
        " AND (length(semkey)-length(replace(semkey,'.','')))=1")]
    semks = list(dict.fromkeys(roots + semks))
    grpids = cap([r[0] for r in c.execute("SELECT grpid FROM languagegroups ORDER BY grpid")])
    c.close()

    write("", render.home)
    write("about", render.about)
    write("reconstructions", render.reconstructions)
    write("languages", render.languages_index)
    write("sources", render.sources_index)
    write("thesaurus", lambda: render.thesaurus(None))
    write("search", lambda: render.search_page(""))   # client-side results shell (reads ?q=)
    for t in tags:
        write(f"etymon/{t}", lambda t=t: render.etymon(t))
    # A 'language' is a lect: render one canonical page per (name, subgroup) aggregating all its
    # source-variant lgids; the other lgids become redirects (so old /language/<lgid> links + the
    # thesaurus/search #rn<id> deep-links still resolve).
    canon_of, _members = render.canonical_languages()
    for g in lgids:
        canon = canon_of.get(g, g)
        if canon == g:
            write(f"language/{g}", lambda g=g: render.language(g))
        else:
            write_redirect(f"language/{g}", f"/language/{canon}/")
    for s in srcs:
        write(f"source/{s}", lambda s=s: render.source(s))
    for g in grpids:
        write(f"group/{g}", lambda g=g: render.group(g))
    for k in semks:
        write(f"thesaurus/{k}", lambda k=k: render.thesaurus(k))

    src_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "search.sqlite3")
    if os.path.exists(src_db):
        shutil.copy(src_db, os.path.join(OUT, "search.sqlite3"))
    open(os.path.join(OUT, ".nojekyll"), "w").close()   # don't let Pages run Jekyll on our files
    print(f"Done: {_ok} pages, {_fail} skipped, {time.time() - t0:.0f}s "
          f"(BASE={BASE!r}, LIMIT={LIMIT or 'all'})")


if __name__ == "__main__":
    main()
