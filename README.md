# STEDT — Sino-Tibetan Etymological Dictionary & Thesaurus

A community-stewarded revival of the [Sino-Tibetan Etymological Dictionary and
Thesaurus](https://stedt.berkeley.edu/), originally compiled at UC Berkeley under
James A. Matisoff. This repository holds the data as **plain, version-controlled
files** so the resource can outlive any single host or institution, and compiles
them into a fast, searchable site.

- **3,916** reconstructions (proto-forms / cognate sets)
- **540,503** attested forms across **690** languages
- a **6-level semantic thesaurus** and the language family tree (Stammbaum)
- **~9,000** scholarly notes

## The data *is* the source of truth

Everything lives as human-readable, diffable files under `data/`:

```
data/
  etyma/<tag>.yaml          one cognate set: reconstruction, gloss, phonology,
                              mesoroots, scholarly notes, curation status
  wordlists/<srcabbr>.tsv   reflexes grouped by source; morpheme→etymon tagging
                              lives in each reflex's `analysis` column
  reference/
    thesaurus.yaml          the semantic hierarchy
    languages.yaml          language varieties (lgid → name, group, source)
    languagegroups.yaml     the Stammbaum
    bibliography.yaml       the sources
    reflex-notes.yaml       per-reflex annotations
```

Etymon numbers are stable and are preserved for citation. Each etymon records its
`status` (`KEEP` / `DELETE` / blank) and `public` flag, so nothing is hidden — the
build decides what to display.

## Pipeline

```
            build_db.py            export_files.py          build_from_files.py
 MySQL dump ───────────▶ SQLite ──────────────▶  data/  ──────────────────▶ stedt.sqlite ──▶ serve.py
 (one-time migration)                         (source of truth)    (canonical build)        (website)
```

`build_db.py` is the one-time importer from the original Berkeley dump. Going
forward the canonical build is **`build_from_files.py`**, which compiles `data/`
into `stedt.sqlite`. The round-trip is verified lossless for all meaningful data.

## Quickstart

```bash
pip install pyyaml                  # only dependency
python3 build_from_files.py        # data/ -> stedt.sqlite  (~115 MB)
python3 serve.py                   # -> http://localhost:8000
python3 validate.py                # referential-integrity check (CI gate)
```

(To re-import from the original Berkeley dump instead, place the decompressed
`STEDT_public_*.sql` under `stedtdb_v1.0/` and run `python3 build_db.py`.)

## Contributing

Edit the files under `data/` — fix a reconstruction, add a reflex, retag a
morpheme, write a note — and open a pull request. CI runs `validate.py`, which
checks that every cognate tag, language, semantic key, and source resolves, that
record ids are unique, and that the YAML is well-formed. A green check means the
change is structurally sound and safe to review.

## Provenance & license

Built from the STEDT v1.0 public release (2017). The original release materials
are archived separately (see `stedtdb_v1.0/` README files). Please retain
attribution to the original STEDT project.
