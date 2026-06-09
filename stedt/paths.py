"""Filesystem locations, resolved against the repo root.

This is build tooling: it reads the working tree (data/, static/, src/) and writes
artifacts beside them, so paths anchor on the *repo root*, not the installed package.
The root is the nearest ancestor of the current directory holding both ``data/`` and
``pyproject.toml``; set ``STEDT_ROOT`` to override. (Templates are the exception — they
ship inside the package, at stedt/render/templates, and are located package-relatively.)
"""

import os


def _find_root():
    override = os.environ.get("STEDT_ROOT")
    if override:
        return os.path.abspath(override)
    d = os.getcwd()
    while True:
        if os.path.isdir(os.path.join(d, "data")) and os.path.isfile(os.path.join(d, "pyproject.toml")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.getcwd()  # no marker found: fall back to the current directory
        d = parent


ROOT = _find_root()

DATA = os.path.join(ROOT, "data")  # all-TSV source of truth
STATIC = os.path.join(ROOT, "static")  # shared site assets (site.css, site.js)
LEGACY_ASSETS = os.path.join(ROOT, "legacy_assets")  # verbatim rootcanal front-end
SITE = os.path.join(ROOT, "site")  # prerendered output
WEB = os.path.join(ROOT, "web")  # JS frontend (npm project; esbuild bundles)

DB = os.path.join(ROOT, "stedt.sqlite")  # canonical compiled DB
SEARCH_DB = os.path.join(ROOT, "search.sqlite3")  # lean modern WASM search index
LEGACY_DB = os.path.join(ROOT, "legacy.sqlite3")  # legacy WASM search index
