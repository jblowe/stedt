# Building

Data is canonically stored under **`data/`** as YAML and TSV.
The build pipeline looks like this:

```
# normal: build the site from the markup
data/ ──build_from_files.py──▶ stedt.sqlite ──build_search_db.py──▶ search.sqlite3
                                     └────────build_static.py────────▶ site/  +  npm run build:search

# or: regenerate the markup from a SQL dump (but data/ already exists in the 
# repo--only needs to be done once per dump)
dump.sql ──tools/build_db.py──▶ stedt.sqlite ──tools/export_files.py──▶ data/
```

## Prerequisites

```sh
pip install pyyaml
npm ci              # esbuild + the WASM SQLite bundle
```

## Option 1: Build the site from the markup

To generate the site artifacts from `data/`, execute the following steps:

```sh
# step 1: build `stedt.sqlite` from `data/`
python build_from_files.py
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
python tools/export_files.py
```

Then review the change with `git diff data/` and build the site as in Option 1 (whose step 1
re-derives `stedt.sqlite` from `data/`).

`export_files.py` intentionally drops a few non-curated columns (modtime/uid, stale workflow
flags, legacy category codes) — see its docstring for the full, documented list.
