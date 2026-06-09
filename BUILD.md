# Building

Data is canonically stored under **`data/`** as TSV (see [`data/FORMAT.md`](data/FORMAT.md)).
Every build step is a subcommand of the `stedt` CLI (`stedt --help` lists them). The pipeline:

```
# normal: build the site from the markup
data/ ──stedt build──▶ stedt.sqlite ──stedt search-db──▶ search.sqlite3
                            └──────────stedt render──────────▶ site/  +  npm run build:search

# or: regenerate the markup from a SQL dump (data/ already exists in the repo —
# only needed once per dump)
dump.sql ──stedt import-dump──▶ stedt.sqlite ──stedt export──▶ data/
```

## Prerequisites

```sh
pip install .              # installs the `stedt` command + jinja2/typer (use -e for development)
npm --prefix web ci        # esbuild + the WASM SQLite bundle (the JS frontend lives in web/)
```

For development, `pip install -e ".[dev]"` adds black + pre-commit; run `pre-commit install`
once and black (line-length 120) formats staged Python on every commit.

## Option 1: Build the site from the markup

```sh
stedt build                      # 1. compile data/ → stedt.sqlite
stedt search-db                  # 2. derive search.sqlite3 (shipped to the browser for search)
stedt render                     # 3. prerender HTML under site/
npm --prefix web run build:search  # 4. bundle web/src/search.js → site/assets/
```

Optional: `stedt validate` checks `data/` referential integrity.

The pixel-faithful `/_legacy/` clone is built separately, **after** the modern site (it writes
only under `site/_legacy/`):

```sh
stedt legacy search-db && stedt legacy render && npm --prefix web run build:legacy
```

### Preview locally

`stedt render` prefixes every link with `/stedt` (the GitHub Pages subpath). To serve from the
root instead, build with an empty base:

```sh
stedt render --base "" && npm --prefix web run build:search
python3 -m http.server 8000 --directory site      # → http://localhost:8000
```

## Option 2: Rebuild the markup from a different SQL dump

`data/` was generated once from a STEDT SQL dump. To regenerate it from a new dump:

```sh
stedt import-dump path/to/dump.sql   # build stedt.sqlite from the dump (any path)
stedt export                         # export stedt.sqlite → the flat files under data/
```

Then review the change with `git diff data/` and build the site as in Option 1 (whose step 1
re-derives `stedt.sqlite` from `data/`).

`stedt export` intentionally drops a few non-curated columns (modtime/uid, stale workflow flags,
legacy category codes) — see `stedt/dev/export_tsv.py` for the documented list. The `build →
export` round-trip is lossless; `stedt roundtrip <baseline.sqlite> <rebuilt.sqlite>` asserts it
(every table's content reproduced identically, surrogate row-ids excepted).

## Verifying a refactor (golden-output snapshots)

Every page is a deterministic function of `data/` (the only date — the citation "Accessed" stamp
— is filled in client-side), so a refactor that isn't meant to change the site should produce
byte-identical HTML. `stedt snapshot` makes that checkable: it renders the full site (modern +
`/_legacy/`) via the real build modules, then writes a `MANIFEST.sha256`.

```sh
stedt snapshot build .snapshots/before    # 1. baseline the current site
# 2. ...make your change...
stedt snapshot build .snapshots/after     # 3. snapshot again
stedt snapshot compare .snapshots/before .snapshots/after
```

`compare` prints `IDENTICAL` (exit 0) or the list of changed/added/removed pages (exit 1, so it
works as a pre-commit gate). For an intentional change, inspect the diff it points you at
(`diff -u .snapshots/before/<path> .snapshots/after/<path>`) and confirm only the expected pages
moved. A full snapshot is ~2 min / ~600 MB; `--limit N` caps entities per kind for a quick smoke
run; `--rebuild-db` regenerates `stedt.sqlite` + the search DBs first (only needed when `data/`
or the DB-build pipeline changed). Snapshot dirs are gitignored — regenerate on demand.
