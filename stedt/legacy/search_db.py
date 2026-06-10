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
`group_concat(... ORDER BY ...)`, so we never rely on it. Mirrors the modern search DB's
page_size/FTS5/VACUUM conventions. Output is .sqlite3 (not .db) for the same GitHub-Pages
gzip reason noted there.
"""

import os
import re
import sqlite3

from stedt.paths import DB as SRC, LEGACY_DB as OUT, WEB

# rootcanal's default_where for the public lexicon search (Table/Lexicon.pm). These are
# render.db's LEX_VISIBLE / ETY_LIVE minus the l./e. alias (the INSERTs below read src tables
# unaliased) — keep the upper() so case drift in a future dump can't leak withdrawn rows here.
LEX_VISIBLE = "coalesce(upper(status),'') NOT IN ('HIDE','DELETED')"
# rootcanal's default_where for etyma (Table/Etyma.pm: status != 'DELETE').
ETY_VISIBLE = "coalesce(upper(status),'') != 'DELETE'"

# the aliases legacy-shim.js binds to the legacy-DB tables (from its SELECT FROM/JOIN clauses)
_SHIM_ALIASES = {"e": "etyma", "l": "lexicon", "ln": "languagenames", "g": "languagegroups",
                 "sb": "srcbib", "ch": "chapters"}


def _verify_shim_contract(db):
    """Every alias-qualified column and every FROM/JOIN table the shim's SQL reads must exist in
    the built DB — the modern pair got this check (build/search_db.py verify_client_contract)
    after four real column-drift bugs of this class. The shim has no manifest, so the read set
    comes from scanning its string literals; // comments are stripped first, or their prose
    apostrophes would pair into pseudo-strings full of false column refs."""
    js = os.path.join(WEB, "src", "legacy-shim.js")
    if not os.path.isfile(js):
        print("  (shim-contract check skipped: web/src/legacy-shim.js not found)")
        return
    with open(js, encoding="utf-8") as fh:
        code = "\n".join(re.sub(r"//.*$", "", ln) for ln in fh)
    sql = " ".join(s for q in (r"`([^`]*)`", r"'((?:[^'\\\n]|\\.)*)'") for s in re.findall(q, code))
    aliases = sorted(_SHIM_ALIASES, key=len, reverse=True)  # ln before l, so "ln.x" binds to ln
    pat = re.compile(r"\b(" + "|".join(aliases) + r")\.(\w+)\b")
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = {
        f"legacy-shim.js reads FROM/JOIN {t}, not shipped by legacy.sqlite3"
        for t in re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", sql) if t not in tables
    }
    for a, c in set(pat.findall(sql)):
        cols = {r[1] for r in db.execute(f"PRAGMA table_info({_SHIM_ALIASES[a]})")}
        if c not in cols:
            missing.add(f"legacy-shim.js reads {_SHIM_ALIASES[a]}.{c}, not shipped by legacy.sqlite3")
    if missing:
        raise SystemExit("legacy-db contract violation:\n  " + "\n  ".join(sorted(missing)))


def main():
    if not os.path.exists(SRC):
        raise SystemExit(f"missing {SRC} — run `stedt build` first")
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
    for rn, ts in db.execute("SELECT rn, tag_str FROM src.lx_et_hash WHERE tag_str IS NOT NULL ORDER BY rn, ind"):
        ana.setdefault(rn, []).append(str(ts))
    db.executemany("UPDATE lexicon SET analysis=? WHERE rn=?", [(",".join(v), rn) for rn, v in ana.items()])

    # --- per-rn public note count (notetype != 'I'); per-tag etyma note/comparandum/record counts ---
    lex_nn = dict(db.execute("SELECT rn, COUNT(*) FROM src.notes WHERE rn IS NOT NULL AND notetype!='I' GROUP BY rn"))
    db.executemany("UPDATE lexicon SET num_notes=? WHERE rn=?", [(n, rn) for rn, n in lex_nn.items()])

    ety_nn = dict(db.execute("SELECT tag, COUNT(*) FROM src.notes WHERE tag IS NOT NULL AND tag>0 GROUP BY tag"))
    ety_cmp = dict(
        db.execute("SELECT tag, COUNT(*) FROM src.notes WHERE tag IS NOT NULL AND tag>0 AND notetype='F' GROUP BY tag")
    )
    ety_rec = dict(db.execute("SELECT tag, COUNT(DISTINCT rn) FROM src.lx_et_hash WHERE tag>0 GROUP BY tag"))
    db.executemany(
        "UPDATE etyma SET num_notes=?, num_comparanda=?, num_recs=? WHERE tag=?",
        [
            (ety_nn.get(t, 0), ety_cmp.get(t, 0), ety_rec.get(t, 0), t)
            for t in set(ety_nn) | set(ety_cmp) | set(ety_rec)
        ],
    )

    # --- pre-rendered per-rn lexical-note HTML for the shim's notes/notes_for_rn endpoint (the
    #     "N notes" click + hover tip in search results / etymon reflex rows). Matches rootcanal's
    #     runmode: notes WHERE rn=? AND notetype!='I', each xml2html'd, joined by <p>. render_note's
    #     xref links stay root-relative (/etymon/N); the shim rebases them to the legacy base. ---
    from stedt import render

    notes_by_rn = {}
    for rn, xml, nt in db.execute("""SELECT rn, xmlnote, notetype FROM src.notes
            WHERE rn IS NOT NULL AND notetype!='I' AND xmlnote IS NOT NULL ORDER BY rn, ord, noteid"""):
        h = render.render_note(xml)
        lab = render.note_label(nt)  # '[Source note]' on source-quoted notes, like the original
        notes_by_rn.setdefault(rn, []).append(h.replace('<p class="np">', f'<p class="np">{lab}', 1) if lab else h)
    db.execute("CREATE TABLE lexnotes (rn INTEGER PRIMARY KEY, html)")
    db.executemany("INSERT INTO lexnotes(rn, html) VALUES(?,?)", [(rn, "<p>".join(v)) for rn, v in notes_by_rn.items()])

    # --- indexes for the shim's prefilter joins (FK lookups + grpno/srcabbr/tag) ---
    db.executescript("""
        CREATE INDEX ix_lex_lgid   ON lexicon(lgid);
        CREATE INDEX ix_ln_grpid   ON languagenames(grpid);
        CREATE INDEX ix_ln_srcabbr ON languagenames(srcabbr);
        CREATE INDEX ix_lg_grpno   ON languagegroups(grpno);
        CREATE INDEX ix_hash_tag   ON lx_et_hash(tag);
    """)

    # --- FTS5 over reflex/gloss/language (visible rows only). Contentless + columnsize=0, same
    #     tokenizer/MATCH semantics as search.sqlite3's lexicon_fts; rowid = rn. ---
    db.executescript("""
        CREATE VIRTUAL TABLE lexicon_fts USING fts5(
            form, gloss, language, content='', columnsize=0, tokenize='unicode61 remove_diacritics 2');
        INSERT INTO lexicon_fts(rowid, form, gloss, language)
          SELECT l.rn, l.reflex, l.gloss, ln.language
          FROM lexicon l LEFT JOIN languagenames ln ON ln.lgid = l.lgid;
    """)

    _verify_shim_contract(db)
    db.commit()
    db.execute("VACUUM")
    db.close()
    print(f"legacy.sqlite3: {os.path.getsize(OUT) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
