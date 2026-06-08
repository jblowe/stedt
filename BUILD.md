# Building

The site is fully static. **`data/` (YAML + TSV) is the source of truth**; `stedt.sqlite`,
`search.sqlite3`, and `site/` are all generated (and git-ignored).

```
# normal: build the site from the markup
data/ ──build_from_files.py──▶ stedt.sqlite ──build_search_db.py──▶ search.sqlite3
                                     └────────build_static.py────────▶ site/  +  npm run build:search

# rare: regenerate the markup from a SQL dump (data/ already exists in the repo)
stedtdb_v1.0/*.sql ──tools/build_db.py──▶ stedt.sqlite ──tools/export_files.py──▶ data/
```

## Prerequisites

```sh
pip install pyyaml
npm ci              # esbuild + the WASM SQLite bundle
```

## 1. Build the site from the markup

This is the normal flow — and exactly what CI runs on every push to `main`:

```sh
python3 build_from_files.py    # data/ → stedt.sqlite
python3 build_search_db.py     # stedt.sqlite → search.sqlite3 (FTS5 + lexicon.semkey)
python3 build_static.py        # → site/  (prerendered HTML)
npm run build:search           # bundle src/search.js → site/assets/
```

`npm run build:search` must come **last**: `build_static.py` wipes `site/` before writing.

Optional: `python3 validate.py` checks `data/` referential integrity (non-zero exit on errors).

### Preview locally

`build_static.py` prefixes every link with `/stedt` (the GitHub Pages subpath). To serve from
the root instead, build with an empty base:

```sh
STEDT_BASE="" python3 build_static.py && npm run build:search
python3 -m http.server 8000 --directory site      # → http://localhost:8000
```

For a faster iteration loop, `STEDT_LIMIT=50 python3 build_static.py` caps each entity type.

## 2. Rebuild the markup from a different SQL dump

`data/` was generated once from the STEDT MySQL dump. To regenerate it from a new dump:

1. Put the dump at `stedtdb_v1.0/STEDT_public_20160602.sql` (or edit `SQLDUMP` in `tools/build_db.py`).
2. Build the intermediate DB, then re-export the flat files:

   ```sh
   python3 tools/build_db.py        # dump → stedt.sqlite  (full normalized load)
   python3 tools/export_files.py    # stedt.sqlite → data/  (the editable markup)
   ```

3. Review the change with `git diff data/`, then build the site as in §1 (which re-derives
   `stedt.sqlite` from `data/`).

`export_files.py` intentionally drops a few non-curated columns (modtime/uid, stale workflow
flags, legacy category codes) — see its docstring for the full, documented list.
