# `data/` — the STEDT source of truth

Everything here is **TSV**. The whole site is a deterministic function of these files:
`data/ ──stedt build──▶ site/`.

## The one escaping rule

Every file is read and written through Python's `csv` module with `delimiter='\t'`,
`quoting=csv.QUOTE_MINIMAL`. A cell that contains a tab, a double-quote, or a newline is
wrapped in double-quotes (and embedded quotes are doubled); everything else is bare. So **any
text — including the marked-up prose in note fields — round-trips losslessly.** Don't hand-roll
delimiters or escaping; use a CSV/TSV library set to these options. The bulk note files are
newline-free in practice, so they stay one-row-per-line and grep-friendly; only a handful of
metadata cells use quoted multi-line values.

## Layout

One entity per row. A row's variable-length children (notes, mesoroots, …) live in their own
table keyed back by id — TSV has no nesting, so one-to-many becomes a second table.

**Global tables**

| file | grain | key |
|------|-------|-----|
| `etyma.tsv` | one cognate set (reconstruction + phonology, flattened to columns) | `tag` |
| `mesoroots.tsv` | intermediate reconstructions, child of an etymon | → `tag` |
| `etymon_notes.tsv` | notes on an etymon; optional `group` (a grpid) anchors the note to that subgroup's band in the reflex table | → `tag` |
| `languages.tsv` | one language | `lgid` |
| `languagegroups.tsv` | one subgroup (`lineage` flattened to `grp0..grp4`) | `grpid` |
| `thesaurus.tsv` | one semantic-category node | `semkey` |
| `chapter_notes.tsv` | notes on a thesaurus node | → `semkey` |
| `hptb.tsv` | a *Handbook of PTB* reconstruction; `etyma_links` = comma-joined etymon ids | `hptbid` |
| `majorcats.tsv`, `otherchapters.tsv`, `pi.tsv`, `glosswords.tsv` | reference scaffolding | — |
| `orphan_links.tsv`, `orphan_reflex_notes.tsv` | rows whose `rn` predates any digitized wordlist | — |

**Per-source folders** — `data/sources/<srcabbr>/`

| file | grain |
|------|-------|
| `source.tsv` | the one-row bibliography entry (the source's home; present even with no wordlist yet) |
| `wordlist.tsv` | this source's reflexes; the `analysis` column tags each reflex to etyma |
| `notes.tsv` | notes on this source's reflexes, keyed by `rn` |
| `annotations.tsv` | source-level bibliographic annotations |

A source that's only cited (not digitized) is a folder with just `source.tsv`. Adding a
language's data is therefore **one new folder that collides with nothing** — the contribution unit.

## Two cell conventions worth knowing

- **`wordlist.tsv` `analysis`** encodes the reflex→etymon morpheme analysis: morpheme slots are
  separated by `,`, and multiple etymon tags at one slot by `|` (e.g. `711,695` or `4|5`). A
  cell of *atomic integer ids* like this is fine; structured records never go in a cell.
- **`hptb.tsv` `etyma_links`** is likewise a comma-joined list of etymon ids.

## Contributing

`stedt validate` checks referential integrity (TSV headers, unique/known keys, every
`analysis`/note/link target exists). It runs on every PR. ERRORs block a merge; WARNINGs (legacy
dangling links inherited from the original dump) don't.

A new etymon takes the next free `tag` (the id space is sparse — any unused integer works).
Because `tag` is a sequential key, two PRs adding etyma in parallel can independently pick the
same number, so `main` requires a PR to be **up to date before merging**: the second PR then
re-runs `stedt validate` against the merged state, where a duplicate `tag` is an ERROR — bump it
and re-push.

### Adding a whole source: `stedt new-source`

A new wordlist never edits these files by hand — `stedt new-source` walks a contributor file
into a complete source folder, and **its `--help` is the usage documentation**. Two data-layer
facts it builds on:

- Language entries are **per-source**: every `lgid` in the corpus is used by exactly one
  source, and `languages.source` names it (a `languages.tsv` row is "a lect as documented in
  one source"). New sources append language rows; they never reuse another source's `lgid`.
- `rn` is one global sequence (the orphan tables occupy the same id space) and follows the
  same parallel-PR rule as `tag`, with a mechanical fix: re-running the importer on the
  up-to-date branch reallocates non-colliding `rn`s — nothing is ever renumbered by hand.
