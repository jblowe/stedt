#!/usr/bin/env python3
"""Build search.sqlite3 — a lean, fully-indexed SQLite for in-browser (WASM) search.

Derived from stedt.sqlite. Holds only what the live search queries touch — etyma, lexicon,
languagenames, languagegroups, lx_et_hash — plus the FTS5 index over reflex form/gloss/language
(`unicode61 remove_diacritics 2`, byte-identical to the server's `lexicon_fts`). Small page_size
+ VACUUM so sql.js-httpvfs range requests fetch little; indexes so every query is index-backed
(the only intentional scan is the ~5K-row etyma table). The full content stays in the HTML pages.
"""

import os
import sqlite3

from stedt.paths import DB as SRC, SEARCH_DB as OUT

# NB: .sqlite3 (not .db) — GitHub Pages gzip-compresses .db, which corrupts the byte-range
# math sql.js-httpvfs relies on; it serves .sqlite3 uncompressed. (community #162857)


def main():
    if not os.path.exists(SRC):
        raise SystemExit(f"missing {SRC} — run `stedt build` first")
    if os.path.exists(OUT):
        os.remove(OUT)

    db = sqlite3.connect(OUT)
    db.executescript("PRAGMA page_size=1024; PRAGMA journal_mode=DELETE;")
    db.execute("ATTACH DATABASE ? AS src", (SRC,))

    # Lean copies — only the columns the search queries read. Beyond the bare match columns we
    # carry what a result ROW shows: each reflex's source (per-lgid srcabbr + srcbib.citation — the
    # WORK it's attested in) and its locus within that work (lexicon.srcid, the page/entry, ~0.8 MB gz
    # over 540K rows), its subgroup (languagenames.grpid -> languagegroups.grpno/grp), its lexical note
    # (lxnote, built below), and the per-syllable tag position (lx_et_hash.ind) so tagged syllables can
    # link to their etymon — so a search/thesaurus row reads "Citation: locus" exactly like the
    # language and etymon pages, instead of dropping the locus only on these two client-rendered views.
    db.executescript("""
        -- key columns as INTEGER PRIMARY KEY (the rowid) so no separate index is needed
        CREATE TABLE etyma          (tag INTEGER PRIMARY KEY, protoform, protogloss, semkey, status, grpid, nreflex, exemplary);
        CREATE TABLE languagegroups (grpid INTEGER PRIMARY KEY, plg, grpno, grp);
        CREATE TABLE languagenames  (lgid INTEGER PRIMARY KEY, language, srcabbr, grpid);
        CREATE TABLE lexicon        (rn INTEGER PRIMARY KEY, reflex, gloss, gfn, lgid, semkey, srcid);
        CREATE TABLE lx_et_hash     (rn INTEGER, tag INTEGER, ind INTEGER);   -- ind = syllable position
        CREATE TABLE srcbib         (srcabbr TEXT PRIMARY KEY, citation);
        CREATE TABLE lxnote         (rn INTEGER PRIMARY KEY, note);
        CREATE TABLE chapters       (semkey TEXT PRIMARY KEY, chaptertitle);   -- ~829 rows; semkey -> human label
        INSERT INTO etyma SELECT e.tag, e.protoform, e.protogloss, e.semkey, e.status, e.grpid,
            (SELECT count(DISTINCT h.rn) FROM src.lx_et_hash h
               JOIN src.lexicon l2 ON l2.rn=h.rn JOIN src.languagenames n2 ON n2.lgid=l2.lgid
               WHERE h.tag=e.tag AND h.tag>0 AND n2.language NOT LIKE '*%'),   -- proto-excluded reflex count
            e.exemplary
          FROM src.etyma e;
        INSERT INTO languagegroups SELECT grpid, plg, grpno, grp FROM src.languagegroups;
        INSERT INTO languagenames  SELECT lgid, language, srcabbr, grpid FROM src.languagenames;
        INSERT INTO lexicon        SELECT rn, reflex, gloss, gfn, lgid, semkey, srcid FROM src.lexicon;
        INSERT INTO lx_et_hash     SELECT rn, tag, ind FROM src.lx_et_hash WHERE tag > 0;
        INSERT INTO srcbib         SELECT srcabbr, citation FROM src.srcbib WHERE coalesce(srcabbr,'')!='';
        INSERT INTO chapters       SELECT semkey, chaptertitle FROM src.chapters WHERE coalesce(semkey,'')!='';
        CREATE INDEX ix_hash_rn ON lx_et_hash(rn);   -- rn non-unique here (multi-tag reflexes)
        -- ^ REQUIRED, not optional (~1 MB gz): the reflex->etyma enrichment LEFT JOIN (h.rn=l.rn)
        -- is the search's hot path, and SQLite does NOT build an automatic_index for it — without
        -- this it full-scans lx_et_hash per driving row (heavy LIMIT-10000 query: 0.01s -> 34s+).
        -- NB: no index on lexicon.semkey. The "attested forms" browse scans it once in-memory
        -- (WASM, ~540K rows = a few ms) on expand; an index would add ~2.4 MB to the gz download
        -- for no perceptible gain. Keep the transfer lean.
    """)

    # Per-reflex lexical notes (what entry pages show: spec='L', notetype!='I'), rendered to HTML with
    # the SAME render_note() the entity pages use — so a search/thesaurus result shows the identical
    # note, cross-reference links and all, instead of stripped plain text. Each note is flattened into
    # one inline <span class="np"> (matching the entity-page popover markup); the client (rows.js
    # reflexRow) injects it as HTML and rebases the root-relative /etymon links to the page base.
    # Display only, NOT added to the FTS index (notes are shown, not searched). ~2.7K notes.
    from stedt.render.notes import render_note

    by_rn = {}
    for rn, xml in db.execute("""SELECT rn, xmlnote FROM src.notes
            WHERE spec='L' AND notetype!='I' AND xmlnote IS NOT NULL AND rn IS NOT NULL
            ORDER BY rn, ord, noteid"""):
        h = render_note(xml).replace('<p class="np">', "").replace("</p>", "")
        if h.strip():
            by_rn.setdefault(rn, []).append('<span class="np">' + h + "</span>")
    db.executemany("INSERT INTO lxnote(rn, note) VALUES(?,?)", [(rn, "".join(v)) for rn, v in by_rn.items()])

    # FTS5 over reflex form/gloss/language. CONTENTLESS (content='') so the index doesn't
    # duplicate the text (it lives once in lexicon/languagenames) — ~27 MB saved; columnsize=0
    # drops the per-doc size table (we don't bm25-rank). detail=column drops the position lists
    # too (~0.6 MB gz): the search builds only single-term AND/OR and column-filtered (`gloss:(…)`)
    # MATCH queries — never a multi-word phrase — so positions buy nothing, while column info is
    # kept for the `gloss:` filter. rowid = rn, so the search selects rowid. Same tokenizer and
    # MATCH semantics as the server's lexicon_fts.
    db.executescript("""
        CREATE VIRTUAL TABLE lexicon_fts USING fts5(
            form, gloss, language, content='', columnsize=0, detail=column,
            tokenize='unicode61 remove_diacritics 2');
        INSERT INTO lexicon_fts(rowid, form, gloss, language)
          SELECT l.rn, l.reflex, l.gloss, ln.language
          FROM lexicon l JOIN languagenames ln ON ln.lgid = l.lgid;
    """)

    db.commit()
    db.execute("VACUUM")
    db.close()
    print(f"search.sqlite3: {os.path.getsize(OUT) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
