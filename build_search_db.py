#!/usr/bin/env python3
"""Build search.sqlite3 — a lean, fully-indexed SQLite for in-browser (WASM) search.

Derived from stedt.sqlite (build_from_tsv.py output). Holds only what the live search
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
# NB: .sqlite3 (not .db) — GitHub Pages gzip-compresses .db, which corrupts the byte-range
# math sql.js-httpvfs relies on; it serves .sqlite3 uncompressed. (community #162857)
OUT = os.path.join(HERE, "search.sqlite3")


def main():
    if not os.path.exists(SRC):
        raise SystemExit(f"missing {SRC} — run build_from_tsv.py first")
    if os.path.exists(OUT):
        os.remove(OUT)

    db = sqlite3.connect(OUT)
    db.executescript("PRAGMA page_size=1024; PRAGMA journal_mode=DELETE;")
    db.execute("ATTACH DATABASE ? AS src", (SRC,))

    # Lean copies — only the columns the search queries read. Beyond the bare match columns we
    # carry what a result ROW shows: each reflex's source (per-lgid srcabbr + srcbib.citation — the
    # WORK it's attested in), its subgroup (languagenames.grpid -> languagegroups.grpno/grp), its
    # lexical note (lxnote, built below), and the per-syllable tag position (lx_et_hash.ind) so
    # tagged syllables can link to their etymon. NB: we deliberately do NOT carry the per-reflex
    # locus lexicon.srcid — it is per-reflex (540K rows, ~0.8 MB gz) and only refines the source;
    # the page/entry number lives on the entry page each result links to. Keep the transfer lean.
    db.executescript("""
        -- key columns as INTEGER PRIMARY KEY (the rowid) so no separate index is needed
        CREATE TABLE etyma          (tag INTEGER PRIMARY KEY, protoform, protogloss, semkey, status, grpid, nreflex);
        CREATE TABLE languagegroups (grpid INTEGER PRIMARY KEY, plg, grpno, grp);
        CREATE TABLE languagenames  (lgid INTEGER PRIMARY KEY, language, srcabbr, grpid);
        CREATE TABLE lexicon        (rn INTEGER PRIMARY KEY, reflex, gloss, gfn, lgid, semkey);
        CREATE TABLE lx_et_hash     (rn INTEGER, tag INTEGER, ind INTEGER);   -- ind = syllable position
        CREATE TABLE srcbib         (srcabbr TEXT PRIMARY KEY, citation);
        CREATE TABLE lxnote         (rn INTEGER PRIMARY KEY, note);
        INSERT INTO etyma SELECT e.tag, e.protoform, e.protogloss, e.semkey, e.status, e.grpid,
            (SELECT count(DISTINCT h.rn) FROM src.lx_et_hash h
               JOIN src.lexicon l2 ON l2.rn=h.rn JOIN src.languagenames n2 ON n2.lgid=l2.lgid
               WHERE h.tag=e.tag AND h.tag>0 AND n2.language NOT LIKE '*%')   -- proto-excluded reflex count
          FROM src.etyma e;
        INSERT INTO languagegroups SELECT grpid, plg, grpno, grp FROM src.languagegroups;
        INSERT INTO languagenames  SELECT lgid, language, srcabbr, grpid FROM src.languagenames;
        INSERT INTO lexicon        SELECT rn, reflex, gloss, gfn, lgid, semkey FROM src.lexicon;
        INSERT INTO lx_et_hash     SELECT rn, tag, ind FROM src.lx_et_hash WHERE tag > 0;
        INSERT INTO srcbib         SELECT srcabbr, citation FROM src.srcbib WHERE coalesce(srcabbr,'')!='';
        CREATE INDEX ix_hash_rn ON lx_et_hash(rn);   -- rn non-unique here (multi-tag reflexes)
        -- NB: no index on lexicon.semkey. The "attested forms" browse scans it once in-memory
        -- (WASM, ~540K rows = a few ms) on expand; an index would add ~2.4 MB to the gz download
        -- for no perceptible gain. Keep the transfer lean.
    """)

    # Per-reflex lexical notes (what entry pages show: spec='L', notetype!='I'), stripped to plain
    # text so a search result can display them. ~2.7K notes / ~0.16 MB — display only, NOT added to
    # the FTS index (so notes are shown, not searched).
    import re
    _TAG = re.compile(r"<[^>]+>")
    def _plain(s):
        s = _TAG.sub(" ", s or "")   # space, not empty: <br/> & block tags are word/line boundaries
        for a, b in (("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&"), ("&apos;", "'"), ("&quot;", '"')):
            s = s.replace(a, b)
        return " ".join(s.split())
    by_rn = {}
    for rn, xml in db.execute("""SELECT rn, xmlnote FROM src.notes
            WHERE spec='L' AND notetype!='I' AND xmlnote IS NOT NULL AND rn IS NOT NULL
            ORDER BY rn, ord, noteid"""):
        t = _plain(xml)
        if t:
            by_rn.setdefault(rn, []).append(t)
    db.executemany("INSERT INTO lxnote(rn, note) VALUES(?,?)",
                   [(rn, " / ".join(v)) for rn, v in by_rn.items()])

    # FTS5 over reflex form/gloss/language. CONTENTLESS (content='') so the index doesn't
    # duplicate the text (it lives once in lexicon/languagenames) — ~27 MB saved; columnsize=0
    # drops the per-doc size table (~7 MB; we don't bm25-rank). detail stays full so the phrase
    # queries fts_q builds still work. rowid = rn, so the search selects rowid. Same tokenizer
    # and MATCH semantics as the server's lexicon_fts.
    db.executescript("""
        CREATE VIRTUAL TABLE lexicon_fts USING fts5(
            form, gloss, language, content='', columnsize=0, tokenize='unicode61 remove_diacritics 2');
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
