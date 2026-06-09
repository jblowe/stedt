# Building

Data is canonically stored under **`data/`** as TSV (see [`data/FORMAT.md`](data/FORMAT.md)).
The build pipeline looks like this:

```
# normal: build the site from the markup
data/ ──build_from_tsv.py──▶ stedt.sqlite ──build_search_db.py──▶ search.sqlite3
                                   └────────build_static.py────────▶ site/  +  npm run build:search

# or: regenerate the markup from a SQL dump (but data/ already exists in the 
# repo--only needs to be done once per dump)
dump.sql ──tools/build_db.py──▶ stedt.sqlite ──tools/export_tsv.py──▶ data/
```

## Prerequisites

```sh
pip install jinja2  # the build no longer needs PyYAML — data/ is pure TSV
npm ci              # esbuild + the WASM SQLite bundle
```

## Option 1: Build the site from the markup

To generate the site artifacts from `data/`, execute the following steps:

```sh
# step 1: build `stedt.sqlite` from `data/`
python build_from_tsv.py
# step 2: build `search.sqlite3` from `stedt.sqlite`
# the search sqlite database is shipped directly to clients' browsers for search
python build_search_db.py
# step 3: render html under `site/`
python build_static.py 
# step 4: prepare JS and other assets needed to power search
npm run build:search           # bundle src/search.js → site/assets/
```

Optional: `python validate.py` checks `data/` referential integrity.

### Preview locally

`build_static.py` prefixes every link with `/stedt` (the GitHub Pages subpath). To serve from
the root instead, build with an empty base:

```sh
# steps 3 and 4 from above
STEDT_BASE="" python build_static.py && npm run build:search
python3 -m http.server 8000 --directory site      # → http://localhost:8000
```

## Option 2: Rebuild the markup from a different SQL dump

`data/` was generated once from a STEDT SQL dump. To regenerate it from a new dump, pass the
dump's path to `build_db.py` and re-export the flat files:

```sh
# step 1: build `stedt.sqlite` from a SQL dump (any path — no fixed filename)
python tools/build_db.py path/to/dump.sql
# step 2: export `stedt.sqlite` back out to the flat files under `data/`
python tools/export_tsv.py
```

Then review the change with `git diff data/` and build the site as in Option 1 (whose step 1
re-derives `stedt.sqlite` from `data/`).

`export_tsv.py` intentionally drops a few non-curated columns (modtime/uid, stale workflow
flags, legacy category codes) — see its docstring for the full, documented list. The
`build_from_tsv → export_tsv` round-trip is lossless; `tools/gate_tsv_roundtrip.py` asserts it
(every table's content reproduced identically, surrogate row-ids excepted).

## Verifying a refactor (golden-output snapshots)

Every page is a deterministic function of `data/` (the only date — the citation "Accessed"
stamp — is filled in client-side), so a refactor that isn't meant to change the site should
produce byte-identical HTML. `tools/snapshot.py` makes that checkable: it renders the full
site (modern + `/_legacy/`) by running the real build scripts, then writes a `MANIFEST.sha256`.

```sh
# 1. baseline the current site
python tools/snapshot.py build .snapshots/before

# 2. ...make your change...

# 3. snapshot again and compare
python tools/snapshot.py build .snapshots/after
python tools/snapshot.py compare .snapshots/before .snapshots/after
```

`compare` prints `IDENTICAL` (exit 0) or the list of changed/added/removed pages (exit 1, so
it works as a pre-commit gate). For an intentional change, inspect the diff it points you at
(`diff -u .snapshots/before/<path> .snapshots/after/<path>`) and confirm only the expected
pages moved. A full snapshot is ~60s / ~600MB; `--limit N` caps entities per kind for a quick
smoke run; `--rebuild-db` regenerates `stedt.sqlite` + the search DBs first (only needed when
`data/` or the DB-build pipeline changed). Snapshot dirs are gitignored — regenerate on demand.
