#!/usr/bin/env python3
"""Build search.db — a lean, fully-indexed SQLite for in-browser (WASM) search.

Derived from stedt.sqlite (build_from_files.py output). Holds only what the live search
queries touch — etyma, lexicon, languagenames, languagegroups, lx_et_hash — plus the FTS5
index over reflex form/gloss/language (`unicode61 remove_diacritics 2`, byte-identical to
the server's `lexicon_fts`). Small page_size + VACUUM so sql.js-httpvfs range requests
fetch little; indexes so every query is index-backed (the only intentional scan is the
~5K-row etyma table). The full content stays in the prerendered HTML pages.
"""
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "stedt.sqlite")
OUT = os.path.join(HERE, "search.db")


def main():
    if not os.path.exists(SRC):
        raise SystemExit(f"missing {SRC} — run build_from_files.py first")
    if os.path.exists(OUT):
        os.remove(OUT)

    db = sqlite3.connect(OUT)
    db.executescript("PRAGMA page_size=1024; PRAGMA journal_mode=DELETE;")
    db.execute("ATTACH DATABASE ? AS src", (SRC,))

    # Lean copies — only the columns the two search queries read.
    db.executescript("""
        CREATE TABLE etyma          AS SELECT tag, protoform, protogloss, semkey, status, grpid FROM src.etyma;
        CREATE TABLE languagegroups AS SELECT grpid, plg FROM src.languagegroups;
        CREATE TABLE languagenames  AS SELECT lgid, language FROM src.languagenames;
        CREATE TABLE lexicon        AS SELECT rn, reflex, gloss, lgid FROM src.lexicon;
        CREATE TABLE lx_et_hash     AS SELECT rn, tag FROM src.lx_et_hash WHERE tag > 0;
    """)

    # Index every key the reflex join + the plg lookup use (etyma LIKE is a deliberate small scan).
    db.executescript("""
        CREATE UNIQUE INDEX ix_ety_tag  ON etyma(tag);
        CREATE UNIQUE INDEX ix_grp      ON languagegroups(grpid);
        CREATE UNIQUE INDEX ix_lang     ON languagenames(lgid);
        CREATE UNIQUE INDEX ix_lex_rn   ON lexicon(rn);
        CREATE INDEX        ix_hash_rn  ON lx_et_hash(rn);
    """)

    # FTS5 — identical definition + tokenizer to the server's lexicon_fts.
    db.executescript("""
        CREATE VIRTUAL TABLE lexicon_fts USING fts5(
            form, gloss, language, rn UNINDEXED, tokenize='unicode61 remove_diacritics 2');
        INSERT INTO lexicon_fts(form, gloss, language, rn)
          SELECT l.reflex, l.gloss, ln.language, l.rn
          FROM lexicon l JOIN languagenames ln ON ln.lgid = l.lgid;
    """)

    db.commit()
    db.execute("VACUUM")
    db.close()
    print(f"search.db: {os.path.getsize(OUT) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
