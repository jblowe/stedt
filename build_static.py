#!/usr/bin/env python3
"""Prerender the STEDT read site to static HTML for GitHub Pages.

Calls serve.py's render functions for every stable route — home, about, the browse
indexes, and every etymon / language / source / thesaurus node — and writes each to
site/<path>/index.html. Search is handled separately by Pagefind (run
`pagefind --site site` after this; the deploy workflow does).

GitHub Pages serves a *project* site under a subpath (https://larc-iu.github.io/stedt/),
so each page's root-absolute links are rewritten with the /stedt prefix and a base global
is injected for Pagefind's client-side result links.

Usage:  python3 build_static.py            # full build -> site/  (needs stedt.sqlite)
Env:    STEDT_BASE   subpath prefix (default /stedt; use '' for a custom apex domain)
        STEDT_OUT    output dir (default site)
        STEDT_LIMIT  cap entities per kind for quick local testing (0 = all)
"""
import os
import re
import shutil
import time

os.environ["STEDT_PREVIEW"] = "1"          # must be set before importing serve
import serve                                # noqa: E402

BASE = os.environ.get("STEDT_BASE", "/stedt").rstrip("/")
OUT = os.environ.get("STEDT_OUT", "site")
LIMIT = int(os.environ.get("STEDT_LIMIT", "0"))

# Add the subpath to root-absolute href/src/action (but not protocol-relative //), and
# inject the base so Pagefind can prefix its client-side result URLs at runtime.
_LINK = re.compile(r'(\b(?:href|src|action)=")/(?!/)')


def rewrite(s):
    if not BASE:
        return s
    s = _LINK.sub(lambda m: m.group(1) + BASE + "/", s)
    return s.replace("<head>", f'<head><script>window.STEDT_BASE="{BASE}";</script>', 1)


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
    t0 = time.time()
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
    for t in tags:
        write(f"etymon/{t}", lambda t=t: serve.etymon(t))
    for g in lgids:
        write(f"language/{g}", lambda g=g: serve.language(g))
    for s in srcs:
        write(f"source/{s}", lambda s=s: serve.source(s))
    for k in semks:
        write(f"thesaurus/{k}", lambda k=k: serve.thesaurus(k))

    open(os.path.join(OUT, ".nojekyll"), "w").close()   # don't let Pages run Jekyll on our files
    print(f"Done: {_ok} pages, {_fail} skipped, {time.time() - t0:.0f}s "
          f"(BASE={BASE!r}, LIMIT={LIMIT or 'all'})")


if __name__ == "__main__":
    main()
