#!/usr/bin/env python3
"""Build legacy.sqlite3 — the in-browser (WASM) search DB for the /_legacy/ rootcanal clone.

Separate from search.sqlite3 (the modern site's lean search DB) because the rootcanal gnis
result tables display columns search.sqlite3 dropped (gfn, grp, citation, srcabbr, srcid,
chaptertitle, analysis). Carries the *normalized* tables rootcanal's query_from joins
(etyma, lexicon, languagenames, languagegroups, srcbib, chapters, lx_et_hash) so the shim can
reproduce the live SQL, plus a contentless FTS5 index over reflex/gloss/language for the
word-search prefilter.

Aggregates that depend on ORDER BY group_concat (the `analysis` tag-string sequence) or counts
are PRECOMPUTED here in Python — the GitHub Actions runner ships an older SQLite without
`group_concat(... ORDER BY ...)`, so we never rely on it. Mirrors build_search_db.py's
page_size/FTS5/VACUUM conventions. Output is .sqlite3 (not .db) for the same GitHub-Pages
gzip reason noted there.
"""
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "stedt.sqlite")
OUT = os.path.join(HERE, "legacy.sqlite3")

# rootcanal's default_where for the public lexicon search (Table/Lexicon.pm).
LEX_VISIBLE = "coalesce(status,'') NOT IN ('HIDE','DELETED')"
# rootcanal's default_where for etyma (Table/Etyma.pm: status != 'DELETE').
ETY_VISIBLE = "coalesce(upper(status),'') != 'DELETE'"


def main():
    if not os.path.exists(SRC):
        raise SystemExit(f"missing {SRC} — run build_from_tsv.py first")
    if os.path.exists(OUT):
        os.remove(OUT)

    db = sqlite3.connect(OUT)
    db.executescript("PRAGMA page_size=1024; PRAGMA journal_mode=DELETE;")
    db.execute("ATTACH DATABASE ? AS src", (SRC,))

    # --- normalized dimension + fact tables (only the columns the gnis result rows / WHERE use) ---
    db.executescript(f"""
        CREATE TABLE etyma (
            tag INTEGER PRIMARY KEY, chapter, sequence, protoform, protogloss, grpid INTEGER,
            notes, status, public, prefix, initial, rhyme, tone,
            num_recs INTEGER DEFAULT 0, num_notes INTEGER DEFAULT 0, num_comparanda INTEGER DEFAULT 0);
        CREATE TABLE lexicon (
            rn INTEGER PRIMARY KEY, reflex, gloss, gfn, lgid INTEGER, srcid, semkey,
            analysis, num_notes INTEGER DEFAULT 0);
        CREATE TABLE languagenames  (lgid INTEGER PRIMARY KEY, language, srcabbr, grpid INTEGER, lgcode, silcode, lgsort);
        CREATE TABLE languagegroups (grpid INTEGER PRIMARY KEY, grpno, grp, plg, genetic,
                                     grp0 INTEGER, grp1 INTEGER, grp2 INTEGER, grp3 INTEGER, grp4 INTEGER);
        CREATE TABLE srcbib         (srcabbr TEXT PRIMARY KEY, citation);
        CREATE TABLE chapters       (semkey TEXT PRIMARY KEY, chaptertitle);
        CREATE TABLE lx_et_hash     (rn INTEGER, tag INTEGER);  -- tag>0; for numeric form-field tag search

        INSERT INTO etyma (tag,chapter,sequence,protoform,protogloss,grpid,notes,status,public,prefix,initial,rhyme,tone)
            SELECT tag,chapter,sequence,protoform,protogloss,grpid,notes,status,public,prefix,initial,rhyme,tone
            FROM src.etyma WHERE {ETY_VISIBLE};
        INSERT INTO lexicon (rn,reflex,gloss,gfn,lgid,srcid,semkey)
            SELECT rn,reflex,gloss,gfn,lgid,srcid,semkey FROM src.lexicon WHERE {LEX_VISIBLE};
        INSERT INTO languagenames  SELECT lgid,language,srcabbr,grpid,lgcode,silcode,lgsort FROM src.languagenames;
        INSERT INTO languagegroups SELECT grpid,grpno,grp,plg,genetic,grp0,grp1,grp2,grp3,grp4 FROM src.languagegroups;
        INSERT INTO srcbib         SELECT srcabbr,citation FROM src.srcbib WHERE coalesce(srcabbr,'')!='';
        INSERT INTO chapters       SELECT semkey,chaptertitle FROM src.chapters WHERE coalesce(semkey,'')!='';
        INSERT INTO lx_et_hash     SELECT rn,tag FROM src.lx_et_hash WHERE tag>0;
    """)

    # --- analysis = GROUP_CONCAT(tag_str ORDER BY ind), comma-separated, over ALL hash rows for the rn
    #     (incl. tag=0 morpheme markers like 'm'). MySQL GROUP_CONCAT skips NULL tag_str. ---
    ana = {}
    for rn, ts in db.execute(
            "SELECT rn, tag_str FROM src.lx_et_hash WHERE tag_str IS NOT NULL ORDER BY rn, ind"):
        ana.setdefault(rn, []).append(str(ts))
    db.executemany("UPDATE lexicon SET analysis=? WHERE rn=?",
                   [(",".join(v), rn) for rn, v in ana.items()])

    # --- per-rn public note count (notetype != 'I'); per-tag etyma note/comparandum/record counts ---
    lex_nn = dict(db.execute(
        "SELECT rn, COUNT(*) FROM src.notes WHERE rn IS NOT NULL AND notetype!='I' GROUP BY rn"))
    db.executemany("UPDATE lexicon SET num_notes=? WHERE rn=?", [(n, rn) for rn, n in lex_nn.items()])

    ety_nn = dict(db.execute(
        "SELECT tag, COUNT(*) FROM src.notes WHERE tag IS NOT NULL AND tag>0 GROUP BY tag"))
    ety_cmp = dict(db.execute(
        "SELECT tag, COUNT(*) FROM src.notes WHERE tag IS NOT NULL AND tag>0 AND notetype='F' GROUP BY tag"))
    ety_rec = dict(db.execute(
        "SELECT tag, COUNT(DISTINCT rn) FROM src.lx_et_hash WHERE tag>0 GROUP BY tag"))
    db.executemany("UPDATE etyma SET num_notes=?, num_comparanda=?, num_recs=? WHERE tag=?",
                   [(ety_nn.get(t, 0), ety_cmp.get(t, 0), ety_rec.get(t, 0), t)
                    for t in set(ety_nn) | set(ety_cmp) | set(ety_rec)])

    # --- pre-rendered per-rn lexical-note HTML for the shim's notes/notes_for_rn endpoint (the
    #     "N notes" click + hover tip in search results / etymon reflex rows). Matches rootcanal's
    #     runmode: notes WHERE rn=? AND notetype!='I', each xml2html'd, joined by <p>. render_note's
    #     xref links stay root-relative (/etymon/N); the shim rebases them to the legacy base. ---
    import render
    notes_by_rn = {}
    for rn, xml in db.execute("""SELECT rn, xmlnote FROM src.notes
            WHERE rn IS NOT NULL AND notetype!='I' AND xmlnote IS NOT NULL ORDER BY rn, ord, noteid"""):
        notes_by_rn.setdefault(rn, []).append(render.render_note(xml))
    db.execute("CREATE TABLE lexnotes (rn INTEGER PRIMARY KEY, html)")
    db.executemany("INSERT INTO lexnotes(rn, html) VALUES(?,?)",
                   [(rn, "<p>".join(v)) for rn, v in notes_by_rn.items()])

    # --- indexes for the shim's prefilter joins (FK lookups + grpno/srcabbr/tag) ---
    db.executescript("""
        CREATE INDEX ix_lex_lgid   ON lexicon(lgid);
        CREATE INDEX ix_ln_grpid   ON languagenames(grpid);
        CREATE INDEX ix_ln_srcabbr ON languagenames(srcabbr);
        CREATE INDEX ix_lg_grpno   ON languagegroups(grpno);
        CREATE INDEX ix_hash_tag   ON lx_et_hash(tag);
    """)

    # --- FTS5 over reflex/gloss/language (visible rows only). Contentless + columnsize=0, same
    #     tokenizer/MATCH semantics as the server's lexicon_fts; rowid = rn. ---
    db.executescript("""
        CREATE VIRTUAL TABLE lexicon_fts USING fts5(
            form, gloss, language, content='', columnsize=0, tokenize='unicode61 remove_diacritics 2');
        INSERT INTO lexicon_fts(rowid, form, gloss, language)
          SELECT l.rn, l.reflex, l.gloss, ln.language
          FROM lexicon l LEFT JOIN languagenames ln ON ln.lgid = l.lgid;
    """)

    db.commit()
    db.execute("VACUUM")
    db.close()
    print(f"legacy.sqlite3: {os.path.getsize(OUT) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
