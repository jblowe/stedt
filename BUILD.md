# Setup

Install the package to get the `stedt` command:

```bash
pip install -e .
```

# Building

Data is canonically stored under **`data/`** as TSV (see [`data/FORMAT.md`](data/FORMAT.md)).
Everything is a subcommand of the `stedt` CLI (`stedt --help`), grouped by workflow:

```
data/    ──stedt build──▶  site/     # compile + render + bundle the whole deployable site
dump.sql ──stedt ingest──▶ data/     # (re)derive the TSV markup from a SQL dump (rare)
```

## Prerequisites

```sh
pip install .     # installs the `stedt` command + jinja2/typer (use -e for development)
stedt setup       # installs the JS build deps (npm ci in web/)
```

For development, `pip install -e ".[dev]"` adds black + pre-commit; run `pre-commit install`
once and black (line-length 120) formats staged Python on every commit.

## Build the site

```sh
stedt build       # data/ → stedt.sqlite → search.sqlite3 → HTML → JS bundles → /_legacy/
```

`stedt build` with no subcommand runs the whole pipeline. Each step is also a subcommand, for
iterating on one part:

```sh
stedt build db          # data/ → stedt.sqlite
stedt build search-db   # → search.sqlite3 (shipped to the browser for client-side search)
stedt build render      # → prerendered HTML under site/
stedt build bundle      # → the client JS bundles under site/assets/
stedt build legacy      # → the pixel-faithful /_legacy/ rootcanal clone
```

Optional: `stedt validate` checks `data/` referential integrity (it also runs in CI on every PR).

### Preview locally

```sh
stedt serve       # builds root-relative (base='') and serves site/ at http://localhost:8000
```

`stedt serve --no-build` skips the rebuild and just serves the existing `site/`; `--port N`
changes the port. (A plain `stedt build` prefixes links with `/stedt`, the GitHub Pages subpath —
that's for deploying, not local serving.)

## Regenerate the markup from a SQL dump

`data/` was generated once from a STEDT SQL dump. To re-derive it (rarely needed):

```sh
stedt ingest                              # the archived dump → stedt.sqlite → data/ TSVs
# or, for a specific dump:
stedt ingest import-dump path/to/dump.sql
stedt ingest export
```

Then review with `git diff data/` and rebuild as above (`stedt build` re-derives `stedt.sqlite`
from `data/`). `stedt ingest export` drops a few non-curated columns (modtime/uid, stale workflow
flags, legacy category codes) — see `stedt/dev/export_tsv.py`. The round-trip is lossless;
`stedt ingest roundtrip <baseline.sqlite> <rebuilt.sqlite>` asserts it (every table reproduced
identically, surrogate row-ids excepted).

## Verifying a refactor (golden-output snapshots)

Every page is a deterministic function of `data/` (the only date — the citation "Accessed" stamp
— is filled in client-side), so a refactor that isn't meant to change the site should produce
byte-identical HTML. `stedt dev snapshot` makes that checkable: it renders the full site (modern +
`/_legacy/`) via the real build modules, then writes a `MANIFEST.sha256`.

```sh
stedt dev snapshot build .snapshots/before    # 1. baseline the current site
# 2. ...make your change...
stedt dev snapshot build .snapshots/after     # 3. snapshot again
stedt dev snapshot compare .snapshots/before .snapshots/after
```

`compare` prints `IDENTICAL` (exit 0) or the list of changed/added/removed pages (exit 1, so it
works as a pre-commit gate). For an intentional change, inspect the diff it points you at
(`diff -u .snapshots/before/<path> .snapshots/after/<path>`) and confirm only the expected pages
moved. A full snapshot is ~2 min / ~600 MB; `--limit N` caps entities per kind for a quick smoke
run; `--rebuild-db` regenerates `stedt.sqlite` + the search DBs first. Snapshot dirs are
gitignored — regenerate on demand.
