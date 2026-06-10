#!/usr/bin/env python3
"""Prerender the STEDT read site to static HTML for GitHub Pages.

Renders every stable route — home, about, the browse indexes, and every etymon / language /
source / thesaurus node — to site/<path>/index.html. Search runs client-side (WASM SQLite over
search.sqlite3; see stedt.build.search_db + src/search.js).

GitHub Pages serves a *project* site under a subpath (https://larc-iu.github.io/stedt/), so each
page's root-absolute links are rewritten with the /stedt prefix and a base global is injected
(window.STEDT_BASE) for the client search's result links.

Env:  STEDT_BASE   subpath prefix (default /stedt; use '' for a custom apex domain)
      STEDT_OUT    output dir (default site/)
      STEDT_LIMIT  cap entities per kind for quick local testing (0 = all)
"""

import os
import re
import shutil
import sys
import time

from stedt import render
from stedt.build.version import data_version
from stedt.paths import SITE, SEARCH_DB, STATIC

BASE = os.environ.get("STEDT_BASE", "/stedt").rstrip("/")
OUT = os.environ.get("STEDT_OUT") or SITE
LIMIT = int(os.environ.get("STEDT_LIMIT", "0"))

# Add the subpath to root-absolute href/src/action (but not protocol-relative //), and inject
# the base + data version so the client search can prefix result URLs and cache-key the DB.
_LINK = re.compile(r'(\b(?:href|src|action)=")/(?!/)')


DB_VERSION = ""  # set in main()
DB_BYTES = 0  # set in main(): decompressed search-DB size for the client progress denominator


def rewrite(s):
    if BASE:
        s = _LINK.sub(lambda m: m.group(1) + BASE + "/", s)
    # DB_BYTES is the DECOMPRESSED size, for the download-progress denominator: Pages serves the
    # DB gzipped, so Content-Length is the ~18 MB wire size while the streamed reader counts the
    # ~43 MB decompressed bytes — using the header showed '41 / 18 MB'.
    head = (
        f'<head><script>window.STEDT_BASE="{BASE}";window.STEDT_DB_VERSION="{DB_VERSION}";'
        f"window.STEDT_DB_BYTES={DB_BYTES};</script>"
    )
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
    html = (
        '<!doctype html><meta charset="utf-8">'
        f'<link rel="canonical" href="{url}">'
        f'<meta http-equiv="refresh" content="0; url={url}">'
        f'<script>location.replace("{url}"+location.hash)</script>'
        f'<p>Redirecting to <a href="{url}">{url}</a>…</p>'
    )
    fp = os.path.join(OUT, path, "index.html")
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(html)
    _ok += 1


def cap(xs):
    return xs[:LIMIT] if LIMIT else xs


def main():
    global DB_VERSION, DB_BYTES
    t0 = time.time()
    # STEDT_DB_VERSION pins the cache-bust hash (used by the snapshot harness so renaming a build
    # file doesn't churn every page's <head>); unset in real builds, where it's a content hash.
    DB_VERSION = os.environ.get("STEDT_DB_VERSION") or data_version(
        os.path.join(os.path.dirname(__file__), "search_db.py")
    )
    # pinnable like the version (snapshot harness), else the real artifact size
    DB_BYTES = int(os.environ.get("STEDT_DB_BYTES", "0")) or (
        os.path.getsize(SEARCH_DB) if os.path.exists(SEARCH_DB) else 0
    )
    # Clear only what THIS step owns: other steps' outputs survive a render re-run, so the local
    # iterate loop is render-only (previously rmtree(site/) silently 404'd the JS bundles and
    # deleted the whole /_legacy subtree until `stedt build bundle`/`legacy` were re-run).
    KEEP = {"assets", "_legacy"}
    if os.path.isdir(OUT):
        for name in os.listdir(OUT):
            if name in KEEP:
                continue
            p = os.path.join(OUT, name)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    os.makedirs(OUT, exist_ok=True)

    c = render.con()
    tags = cap([r[0] for r in c.execute(f"SELECT tag FROM etyma e WHERE {render.ETY_LIVE} ORDER BY tag")])
    lgids = cap([r[0] for r in c.execute("SELECT lgid FROM languagenames ORDER BY lgid")])
    srcs = cap([r[0] for r in c.execute("SELECT srcabbr FROM srcbib WHERE coalesce(srcabbr,'')!='' ORDER BY srcabbr")])
    semks = cap([r[0] for r in c.execute("SELECT semkey FROM chapters WHERE coalesce(semkey,'')!='' ORDER BY semkey")])
    # The thesaurus index and breadcrumbs link top-level chapters by integer key
    # (1.0 -> /thesaurus/1), so emit those pages too or every top-level link 404s.
    roots = [
        r[0].split(".")[0]
        for r in c.execute(
            "SELECT semkey FROM chapters WHERE semkey LIKE '%.0'"
            " AND (length(semkey)-length(replace(semkey,'.','')))=1"
        )
    ]
    semks = list(dict.fromkeys(roots + semks))
    grpids = cap([r[0] for r in c.execute("SELECT grpid FROM languagegroups ORDER BY grpid")])
    c.close()

    write("", render.home)
    # GitHub Pages picks up 404.html at the artifact root (must be the bare file, not 404/index.html)
    with open(os.path.join(OUT, "404.html"), "w", encoding="utf-8") as f:
        f.write(rewrite(render.not_found()))
    write("about", render.about)
    write("reconstructions", render.reconstructions)
    write("languages", render.languages_index)
    write("sources", render.sources_index)
    write("thesaurus", lambda: render.thesaurus(None))
    write("search", lambda: render.search_page(""))  # client-side results shell (reads ?q=)
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

    if os.path.exists(SEARCH_DB):
        shutil.copy(SEARCH_DB, os.path.join(OUT, "search.sqlite3"))
    # static/ holds the shared stylesheet + universal JS the renderer links (site.css, site.js);
    # copy it in so /static/... resolves (rewrite() applies the BASE prefix to those links).
    if os.path.isdir(STATIC):
        shutil.copytree(STATIC, os.path.join(OUT, "static"), dirs_exist_ok=True)
    open(os.path.join(OUT, ".nojekyll"), "w").close()  # don't let Pages run Jekyll on our files
    print(f"Done: {_ok} pages, {_fail} skipped, {time.time() - t0:.0f}s " f"(BASE={BASE!r}, LIMIT={LIMIT or 'all'})")
    # A skipped page is a permanent production 404 under a green CI run — the only detection point
    # in a project with no test harness. Partial builds are only acceptable in capped local runs.
    if _fail and not LIMIT:
        sys.exit(f"{_fail} page(s) failed to render — refusing to ship a partial site")


if __name__ == "__main__":
    main()
