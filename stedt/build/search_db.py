#!/usr/bin/env python3
"""Build search.sqlite3 — a lean, fully-indexed SQLite for in-browser (WASM) search.

Derived from stedt.sqlite. Holds only what the live search queries touch — etyma, lexicon,
languagenames, languagegroups, lx_et_hash, srcbib, lxnote, chapters — plus the FTS5 index over
reflex form/gloss/language (`unicode61 remove_diacritics 2`, same tokenizer as legacy.sqlite3's
`lexicon_fts`). Small page_size + VACUUM so sql.js-httpvfs range requests fetch little; indexes so
every query is index-backed (the only intentional scan is the ~5K-row etyma table). The full
content stays in the HTML pages.

The transferred tables are declared ONCE in TABLES below — the single contract of what the search
DB ships. The CREATE and INSERT are generated from it (so the two can't drift), the build verifies
the result against it, and the in-browser SQL (web/src/search.js) is checked against it so a column
a row builder needs can't be silently dropped (the failure mode this manifest exists to prevent).
"""

import json
import os
import re
import sqlite3

from stedt.paths import DB as SRC, SEARCH_DB as OUT, WEB
from stedt.render.db import LEX_VISIBLE
from stedt.render.text import seq_label

# NB: .sqlite3 (not .db) — GitHub Pages gzip-compresses .db, which corrupts the byte-range
# math sql.js-httpvfs relies on; it serves .sqlite3 uncompressed. (community #162857)

# proto-excluded reflex count, shown by etymonRow as "· N reflexes" (the inner alias is `l` so the
# shared LEX_VISIBLE filter applies verbatim, matching the etymon page's reflex_counts())
_NREFLEX = (
    "(SELECT count(DISTINCT h.rn) FROM src.lx_et_hash h "
    "JOIN src.lexicon l ON l.rn=h.rn JOIN src.languagenames n2 ON n2.lgid=l.lgid "
    f"WHERE h.tag=e.tag AND h.tag>0 AND n2.language NOT LIKE '*%' AND {LEX_VISIBLE})"
)

# --- The search DB's column contract -----------------------------------------------------------
# One entry per transferred table; each column is (name, create_decl, select_expr) and notes the
# client field it feeds (search.js SELECT alias -> rows.js consumer). The build GENERATES the CREATE
# TABLE and INSERT...SELECT from this, VERIFIES the result matches, and CHECKS that search.js reads
# only columns declared here. To give a row builder a new field: add the column here (and select it
# in search.js / read it in rows.js) — otherwise the contract check fails the build. select_expr is
# the expression filling the column from `src` (default: the bare name); src=None ⇒ filled in Python
# (lxnote); a table may carry a `where` filter.
TABLES = [
    {"name": "etyma", "src": "src.etyma e", "cols": [
        ("tag",        "INTEGER PRIMARY KEY", "e.tag"),       # etymonRow #tag; etyma[].tag (chips / sylLink)
        ("protoform",  "",                    "e.protoform"), # etymonRow / chip / popover *protoform (etyma 'pf')
        ("protogloss", "",                    "e.protogloss"),# etymonRow gloss; syllable popover 'gloss' (etyma 'pg')
        ("semkey",     "",                    "e.semkey"),    # etyma semantic filing
        ("status",     "",                    "e.status"),    # DELETE filter (query WHERE)
        ("grpid",      "",                    "e.grpid"),     # join -> languagegroups (plg)
        ("nreflex",    "",                    _NREFLEX),      # etymonRow "· N reflexes"
        ("exemplary",  "",                    "e.exemplary"), # etymonRow .exm badge
        ("public",     "",                    "e.public"),    # etymonRow .prov marker (public=0)
        # syllable-popover enrichment (etyma 'plg'/'meso'): the popover mirrors the original's
        # elink popup — '#tag PLG *protoform' + the etymon's mesoroots. plg denormalized so the
        # reflex payload needn't join languagegroups twice; meso prebuilt as an ORDERED JSON
        # array [{plg,f,g,no},…] (Stammbaum: grp0..grp4, variant — the original elink ORDER BY;
        # 'no' = grpno, anchoring the popover's meso link to its row on the etymon page).
        ("plg",        "",                    "(SELECT g2.plg FROM src.languagegroups g2 WHERE g2.grpid=e.grpid)"),
        ("meso",       "",                    """(SELECT json_group_array(json_object('plg', plg, 'f', form, 'g', gloss, 'no', grpno))
            FROM (SELECT lg.plg AS plg, m.form AS form, m.gloss AS gloss, lg.grpno AS grpno
                  FROM src.mesoroots m LEFT JOIN src.languagegroups lg ON lg.grpid=m.grpid
                  WHERE m.tag=e.tag ORDER BY lg.grp0, lg.grp1, lg.grp2, lg.grp3, lg.grp4, m.variant))"""),
        # the computed allofam family (chapter + integer sequence — the original elink's allofams
        # query), prebuilt as ordered JSON [{s,tag,plg,pf,pg},…] with the seq label preformatted;
        # filled in Python after the insert (families need a group-by pass), '[]' when alone
        ("fam",        "",                    "'[]'"),
    ]},
    {"name": "languagegroups", "src": "src.languagegroups", "cols": [
        ("grpid", "INTEGER PRIMARY KEY", "grpid"),
        ("plg",   "",                    "plg"),    # etymonRow PLG label
        ("grpno", "",                    "grpno"),  # reflex row Stammbaum sort key
        ("grp",   "",                    "grp"),    # reflex row subgroup label
    ]},
    {"name": "languagenames", "src": "src.languagenames", "cols": [
        ("lgid",     "INTEGER PRIMARY KEY", "lgid"),
        ("language", "",                    "language"),  # reflexRow language name + FTS column
        ("lgsort",   "",                    "lgsort"),    # curated collation key: listings order by it, not the display name
        ("srcabbr",  "",                    "srcabbr"),   # reflexRow source -> srcbib.citation
        ("grpid",    "",                    "grpid"),     # join -> languagegroups
    ]},
    {"name": "lexicon", "src": "src.lexicon l", "where": LEX_VISIBLE, "cols": [
        ("rn",     "INTEGER PRIMARY KEY", "rn"),     # reflexRow #rn attestation link + FTS rowid
        ("reflex", "",                    "reflex"), # reflexRow form + FTS column
        ("gloss",  "",                    "gloss"),  # reflexRow gloss + FTS column
        ("gfn",    "",                    "gfn"),    # reflexRow POS
        ("lgid",   "",                    "lgid"),   # join -> languagenames
        ("semkey", "",                    "semkey"), # reflexRow category link -> chapters
        ("srcid",  "",                    "srcid"),  # reflexRow source locus ": page/entry"
        ("analysis", "",                  "''"),     # reflexRow per-morpheme codes (b/p/s/m); filled in main()
    ]},
    # NB: the INTEGER decls are load-bearing, not documentation — typeless columns get BLOB
    # affinity, which disqualifies ix_hash_rn from the h.rn=l.rn join (lexicon.rn is INTEGER),
    # turning every search into a per-row full scan of this table (~9-75s tab freezes).
    # rn IN (SELECT …) keeps the table consistent with the LEX_VISIBLE-filtered lexicon copy
    # (which is inserted before this one): no orphan rows for suppressed reflexes.
    {"name": "lx_et_hash", "src": "src.lx_et_hash", "where": "tag > 0 AND rn IN (SELECT rn FROM lexicon)", "cols": [
        ("rn",  "INTEGER", "rn"),   # reflex -> etyma enrichment join (hot path; indexed below)
        ("tag", "INTEGER", "tag"),  # etymon a syllable/reflex belongs to
        ("ind", "INTEGER", "ind"),  # syllable position -> per-syllable links (r.syn)
    ]},
    {"name": "srcbib", "src": "src.srcbib", "where": "coalesce(srcabbr,'')!=''", "cols": [
        ("srcabbr",  "TEXT PRIMARY KEY", "srcabbr"),
        ("citation", "",                 "citation"),  # reflexRow source label
    ]},
    {"name": "chapters", "src": "src.chapters", "where": "coalesce(semkey,'')!=''", "cols": [
        ("semkey",       "TEXT PRIMARY KEY", "semkey"),       # ~829 rows
        ("chaptertitle", "",                 "chaptertitle"), # reflexRow category label (r.cat)
    ]},
    # lxnote is rendered in Python (render_note), not a column copy — declared for the schema +
    # verification, populated in main().
    {"name": "lxnote", "src": None, "cols": [
        ("rn",   "INTEGER PRIMARY KEY", None),
        ("note", "",                    None),  # reflexRow note popover (rendered HTML)
    ]},
]

# the aliases search.js binds to the search-DB tables (stable; from the query FROM/JOIN clauses)
_CLIENT_ALIASES = {"l": "lexicon", "ln": "languagenames", "g": "languagegroups", "sb": "srcbib",
                   "nt": "lxnote", "h": "lx_et_hash", "e": "etyma", "c": "chapters"}


def _create_sql(t):
    cols = ", ".join(f"{n} {decl}".strip() for n, decl, _ in t["cols"])
    return f"CREATE TABLE {t['name']} ({cols});"


def _insert_sql(t):
    exprs = ", ".join(e for _, _, e in t["cols"])
    where = f" WHERE {t['where']}" if t.get("where") else ""
    return f"INSERT INTO {t['name']} SELECT {exprs} FROM {t['src']}{where};"


def _verify_schema(db):
    """The built DB must match the manifest column-for-column (catches any drift between the manifest
    and the generated/edited SQL)."""
    for t in TABLES:
        actual = [r[1] for r in db.execute(f"PRAGMA table_info({t['name']})")]
        expected = [n for n, _, _ in t["cols"]]
        if actual != expected:
            raise SystemExit(f"search-db: {t['name']} built columns {actual} != manifest {expected}")


def verify_client_contract():
    """Fail the build if the in-browser SQL (web/src/search.js) reads a search-DB column the manifest
    doesn't ship — turning a would-be broken-search-at-runtime into a loud build error. Scans only the
    SQL template literals (backtick strings), so JS code isn't mistaken for column refs."""
    js = os.path.join(WEB, "src", "search.js")
    if not os.path.isfile(js):
        print("  (client-contract check skipped: web/src/search.js not found)")
        return
    with open(js, encoding="utf-8") as fh:
        sql = " ".join(re.findall(r"`([^`]*)`", fh.read()))
    cols = {t["name"]: {n for n, _, _ in t["cols"]} for t in TABLES}
    aliases = sorted(_CLIENT_ALIASES, key=len, reverse=True)   # ln before l, so "ln.x" binds to ln
    pat = re.compile(r"\b(" + "|".join(aliases) + r")\.(\w+)\b")
    missing = {
        f"search.js reads {_CLIENT_ALIASES[a]}.{c}, not shipped by the search-DB manifest"
        for a, c in pat.findall(sql) if c not in cols[_CLIENT_ALIASES[a]]
    }
    if missing:
        raise SystemExit("search-db contract violation:\n  " + "\n  ".join(sorted(missing)))


def main():
    if not os.path.exists(SRC):
        raise SystemExit(f"missing {SRC} — run `stedt build` first")
    verify_client_contract()   # fail fast, before building, if the client wants a column we don't ship
    if os.path.exists(OUT):
        os.remove(OUT)

    db = sqlite3.connect(OUT)
    db.executescript("PRAGMA page_size=1024; PRAGMA journal_mode=DELETE;")
    db.execute("ATTACH DATABASE ? AS src", (SRC,))

    # tables + data generated from the manifest (lxnote's rows are filled in Python below)
    for t in TABLES:
        db.execute(_create_sql(t))
    for t in TABLES:
        if t["src"]:
            db.execute(_insert_sql(t))

    # etyma.fam: the computed allofam family (same chapter + integer sequence, the original
    # elink's allofams derivation) needs a grouping pass, so it's filled here rather than in
    # the generated INSERT. Members are sequence-ordered; the seq label is preformatted with
    # the shared seq_label (the etymon page's Allofams list shows identical labels).
    fams = {}
    for tag, chap, seq, pf, pg, plg in db.execute("""
            SELECT e.tag, e.chapter, e.sequence, e.protoform, e.protogloss, g.plg
            FROM src.etyma e LEFT JOIN src.languagegroups g ON g.grpid=e.grpid
            WHERE coalesce(upper(e.status),'') != 'DELETE' AND coalesce(e.chapter,'') != ''
              AND CAST(e.sequence AS INTEGER) > 0
            ORDER BY e.chapter, e.sequence"""):
        fams.setdefault((chap, int(float(seq))), []).append((seq, tag, plg, pf, pg))
    upd = []
    for members in fams.values():
        if len(members) < 2:
            continue
        arr = json.dumps(
            [{"s": seq_label(q), "tag": t, "plg": gp, "pf": f, "pg": g}
             for q, t, gp, f, g in members],
            ensure_ascii=False,
        )
        upd.extend((arr, t) for _, t, _, _, _ in members)
    db.executemany("UPDATE etyma SET fam=? WHERE tag=?", upd)

    # lexicon.analysis: the per-reflex morpheme-analysis codes (b/p/s/m + borrowing source) the
    # original surfaced in its "analysis" column. Stored ONLY for reflexes that carry at least one
    # code — purely-cognate reflexes already get their links from lx_et_hash — as the grouped string
    # the client (search.js shapeReflexEtyma) splits by morpheme slot: ',' between slots (= the
    # lx_et_hash.ind position), '|' within a slot. Numeric/empty slots are kept as placeholders so a
    # code's position still equals its ind. Read from the FULL src.lx_et_hash (the shipped copy drops
    # tag=0 code rows); grouping mirrors dev/export_tsv.py.
    from stedt.render.rows import morph_code

    slots_by_rn = {}
    for rn, ind, tag_str in db.execute(
        "SELECT rn, ind, tag_str FROM src.lx_et_hash WHERE rn IN (SELECT rn FROM lexicon) "
        "ORDER BY rn, ind, tag_str"
    ):
        slots_by_rn.setdefault(rn, {}).setdefault(ind, []).append(tag_str or "")
    ana = []
    for rn, slots in slots_by_rn.items():
        if any(morph_code(t) for toks in slots.values() for t in toks):
            ana.append((",".join("|".join(slots[i]) for i in sorted(slots)), rn))
    db.executemany("UPDATE lexicon SET analysis=? WHERE rn=?", ana)

    db.executescript("""
        CREATE INDEX ix_hash_rn ON lx_et_hash(rn);   -- rn non-unique here (multi-tag reflexes)
        -- ^ REQUIRED, not optional (~1 MB gz): the reflex->etyma enrichment LEFT JOIN (h.rn=l.rn)
        -- is the search's hot path, and SQLite does NOT build an automatic_index for it — without
        -- this it full-scans lx_et_hash per driving row (heavy LIMIT-10000 query: 0.01s -> 34s+).
        -- NB: no index on lexicon.semkey. The "Reflexes" browse scans it once in-memory
        -- (WASM, ~540K rows = a few ms) on expand; an index would add ~2.4 MB to the gz download
        -- for no perceptible gain. Keep the transfer lean.
    """)

    # Per-reflex lexical notes (what entry pages show: spec='L', notetype!='I'), rendered to HTML with
    # the SAME render_note() the entity pages use — so a search/thesaurus result shows the identical
    # note, cross-reference links and all, instead of stripped plain text. Each note is flattened into
    # one inline <span class="np"> (matching the entity-page popover markup); the client (rows.js
    # reflexRow) injects it as HTML and rebases the root-relative /etymon links to the page base.
    # Display only, NOT added to the FTS index (notes are shown, not searched). ~2.7K notes.
    from stedt.render.notes import note_span, render_note_inline

    by_rn = {}
    for rn, xml, nt in db.execute("""SELECT rn, xmlnote, notetype FROM src.notes
            WHERE spec='L' AND notetype!='I' AND xmlnote IS NOT NULL AND rn IS NOT NULL
            AND rn IN (SELECT rn FROM lexicon)
            ORDER BY rn, ord, noteid"""):
        if render_note_inline(xml).strip():  # a note rendering to no text never bakes an empty span
            by_rn.setdefault(rn, []).append(note_span(nt, xml))
    db.executemany("INSERT INTO lxnote(rn, note) VALUES(?,?)", [(rn, "".join(v)) for rn, v in by_rn.items()])

    # FTS5 over reflex form/gloss/language. CONTENTLESS (content='') so the index doesn't
    # duplicate the text (it lives once in lexicon/languagenames) — ~27 MB saved; columnsize=0
    # drops the per-doc size table (we don't bm25-rank). detail=column drops the position lists
    # too (~0.6 MB gz): the search builds only single-term AND/OR and column-filtered (`gloss:(…)`)
    # MATCH queries — never a multi-word phrase — so positions buy nothing, while column info is
    # kept for the `gloss:` filter. rowid = rn, so the search selects rowid. Same tokenizer and
    # MATCH semantics as legacy.sqlite3's lexicon_fts.
    db.executescript("""
        CREATE VIRTUAL TABLE lexicon_fts USING fts5(
            form, gloss, language, content='', columnsize=0, detail=column,
            tokenize='unicode61 remove_diacritics 2');
        INSERT INTO lexicon_fts(rowid, form, gloss, language)
          SELECT l.rn, l.reflex, l.gloss, ln.language
          FROM lexicon l JOIN languagenames ln ON ln.lgid = l.lgid;
    """)

    _verify_schema(db)
    db.commit()
    db.execute("VACUUM")
    db.close()
    print(f"search.sqlite3: {os.path.getsize(OUT) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
