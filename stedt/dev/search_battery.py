"""Search-semantics battery: assert the documented query idioms over search.sqlite3.

The client search (web/src/search.js) promises, via the /search syntax reference, a set
of semantics: bare terms match whole tokens in form/gloss/language and AND together;
commas make OR groups; `gloss:`/`form:`/`language:` filter one column; CJK input falls
back to substring matching; `pform:`/`pgloss:` search reconstructions; language and
subgroup terms behave as documented. Those promises rest on two artifacts this battery
checks mechanically (no browser, no JS):

  1. the FTS index — its membership must equal the search DB's own content tables
     (a contentless FTS5 table silently desynchronizes if an INSERT path changes),
     and the search DB's lexicon must equal the canonical DB's visible rows;
  2. the documented MATCH/LIKE semantics — each idiom is executed with the same query
     shapes search.js emits, against ground truth derived independently by tokenizing
     the stored text in Python (mirroring unicode61 remove_diacritics 2).

What this deliberately does NOT cover: the JS query-construction code itself (ftsQ /
parseFields) — that runs only in the browser; its contract with the DB is what's
asserted here, its parsing is exercised by the runnable examples on /search.

Run: python -m stedt.dev.search_battery  (or `stedt check search`).
Needs stedt.sqlite + search.sqlite3 built. Exits nonzero on any failed assertion.
The golden-corpus comparison at the end is REPORT-ONLY (data vintage + word-boundary
vs token semantics differ by design).
"""

import os
import re
import sqlite3
import sys
import unicodedata
from collections import Counter

from stedt.paths import DB, ROOT, SEARCH_DB

CORPUS = os.path.join(ROOT, ".archive", "original-snapshot")
failures = []


def fail(msg):
    failures.append(msg)


def ok(label, detail=""):
    print(f"  ok {label}{(' — ' + detail) if detail else ''}")


# unicode61 remove_diacritics 2, in Python: a token is a run of letters/numbers/marks
# (everything else separates), then fold case and strip combining marks (NFD), like the
# indexer does. Category lookups are cached — this tokenizes ~16M chars per run.
_tokchar = {}


def _is_tok(c):
    v = _tokchar.get(c)
    if v is None:
        v = _tokchar[c] = unicodedata.category(c)[0] in ("L", "N", "M")
    return v


def toks(s):
    out, cur = [], []
    for c in str(s or ""):
        if _is_tok(c):
            cur.append(c)
        elif cur:
            out.append("".join(cur)); cur = []
    if cur:
        out.append("".join(cur))
    return ["".join(c for c in unicodedata.normalize("NFD", t)
                    if unicodedata.category(c)[0] != "M").casefold() for t in out]


def main():
    if not (os.path.exists(DB) and os.path.exists(SEARCH_DB)):
        sys.exit("check search: build stedt.sqlite and search.sqlite3 first")
    sdb = sqlite3.connect(f"file:{SEARCH_DB}?mode=ro", uri=True)
    cdb = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    # ---- 1. membership: canonical visible rows == search-db lexicon == FTS index ----
    vis = {rn for (rn,) in cdb.execute(
        "SELECT rn FROM lexicon l WHERE coalesce(upper(l.status),'') NOT IN ('HIDE','DELETED')")}
    srows = {rn for (rn,) in sdb.execute("SELECT rn FROM lexicon")}
    if vis != srows:
        fail(f"membership: search-db lexicon != canonical visible rows "
             f"(+{len(srows - vis)} extra, -{len(vis - srows)} missing; e.g. {sorted((srows ^ vis))[:5]})")
    else:
        ok("membership", f"{len(srows)} visible rows in search-db lexicon")
    # (contentless FTS5 can't be scanned for a doc count; the index↔content equality is
    # asserted token-by-token below instead, which is stronger anyway)

    # ground-truth token index over the search DB's own content (form/gloss/language)
    truth = {}  # token -> set(rn), per column
    cols = {"form": {}, "gloss": {}, "language": {}}
    for rn, reflex, gloss, language in sdb.execute(
            "SELECT l.rn, l.reflex, l.gloss, ln.language FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid"):
        for col, val in (("form", reflex), ("gloss", gloss), ("language", language)):
            for t in set(toks(val)):
                cols[col].setdefault(t, set()).add(rn)
                truth.setdefault(t, set()).add(rn)

    def match(q):
        return {rn for (rn,) in sdb.execute("SELECT rowid FROM lexicon_fts WHERE lexicon_fts MATCH ?", (q,))}

    # ---- 2. single-token whole-word search: named idioms + a frequency-spread sample ----
    for w in ["dog", "hand", "water", "fish", "two", "lotha", "kui"]:
        got, want = match(f'"{w}"'), truth.get(w, set())
        if got != want:
            fail(f'MATCH "{w}": {len(got)} rows vs ground truth {len(want)} '
                 f"(e.g. {sorted(got ^ want)[:5]})")
        else:
            ok(f'"{w}"', f"{len(got)} rows")
    # index↔content: the shipped index must equal an index freshly rebuilt from the
    # shipped content with the same tokenizer — catches desync (an INSERT path change,
    # a missed row) without having to emulate unicode61 edge cases in Python.
    sdb.executescript("""
        CREATE VIRTUAL TABLE temp.fts_check USING fts5(
            form, gloss, language, content='', columnsize=0, detail=column,
            tokenize='unicode61 remove_diacritics 2');
        INSERT INTO temp.fts_check(rowid, form, gloss, language)
          SELECT l.rn, l.reflex, l.gloss, ln.language
          FROM lexicon l JOIN languagenames ln ON ln.lgid = l.lgid;
        CREATE VIRTUAL TABLE temp.fts_vocab USING fts5vocab(temp, 'fts_check', 'row');
    """)
    vocab = [t for (t,) in sdb.execute(
        "SELECT term FROM temp.fts_vocab ORDER BY doc DESC, term")]
    sample_toks = vocab[:: max(1, len(vocab) // 300)]
    bad = 0
    for t in sample_toks:
        fresh = {rn for (rn,) in sdb.execute(
            "SELECT rowid FROM temp.fts_check WHERE fts_check MATCH ?", (f'"{t}"',))}
        if match(f'"{t}"') != fresh:
            bad += 1
            if bad <= 3:
                fail(f'index↔rebuild: MATCH "{t}" differs between the shipped index and a fresh rebuild')
    if bad > 3:
        fail(f"index↔rebuild: {bad}/{len(sample_toks)} sampled tokens diverge")
    if not bad:
        ok("index↔rebuild sample", f"{len(sample_toks)} tokens across the frequency range, all equal")

    # ---- 3. AND of terms / comma-OR groups (the shapes ftsQ emits) ----
    hit, lotha = truth.get("hit", set()), truth.get("lotha", set())
    got = match('"hit" "lotha"')
    if got != (hit & lotha):
        fail(f"AND: hit+lotha gave {len(got)}, expected {len(hit & lotha)}")
    else:
        ok("AND", f'hit Lotha → {len(got)} rows (∩ of {len(hit)} and {len(lotha)})')
    frog, snail = truth.get("frog", set()), truth.get("snail", set())
    got = match('("frog") OR ("snail")')
    if got != (frog | snail):
        fail(f"comma-OR: frog,snail gave {len(got)}, expected {len(frog | snail)}")
    else:
        ok("comma-OR", f"frog, snail → {len(got)} rows (∪ of {len(frog)} and {len(snail)})")

    # ---- 4. column filter: gloss:"dog" restricts to the gloss column ----
    got, want = match('gloss:"dog"'), cols["gloss"].get("dog", set())
    if got != want:
        fail(f'gloss:"dog": {len(got)} vs {len(want)} gloss-column rows')
    else:
        ok('gloss: filter', f"{len(got)} rows (vs {len(truth.get('dog', set()))} any-column)")

    # ---- 4b. column-scoped OR group (the shape comma-alternatives in a field emit) ----
    got = match('gloss:("frog" OR "snail")')
    want = cols["gloss"].get("frog", set()) | cols["gloss"].get("snail", set())
    if got != want:
        fail(f'gloss:("frog" OR "snail"): {len(got)} vs {len(want)} gloss-column rows')
    else:
        ok("gloss: comma-OR group", f"{len(got)} rows")
    # explicit AND next to a group — implicit (space) AND is an fts5 syntax error there,
    # which is why fieldedSearch joins terms with ' AND '
    got = match('"green" AND (gloss:"frog" OR gloss:"snail")')
    want = truth.get("green", set()) & want
    if got != want:
        fail(f'AND-with-group: {len(got)} vs {len(want)}')
    else:
        ok("explicit AND with group", f"{len(got)} rows")

    # ---- 5. CJK fallback path: substring LIKE over stored text ----
    cj = sdb.execute(
        "SELECT count(*) FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid "
        "WHERE (l.reflex LIKE '%头%' OR l.gloss LIKE '%头%') AND ln.language NOT LIKE '*%'").fetchone()[0]
    if cj == 0:
        fail("CJK LIKE path: '头' finds nothing (Han text missing from search-db lexicon?)")
    else:
        ok("CJK substring", f"'头' → {cj} rows")

    # ---- 6. reconstruction search (the ETYMA_SQL shape incl. the de-hyphenated variant) ----
    for term, must_tag in [("lak", 695), ("sin", 511)]:
        v = f"%{term}%"
        tags = {t for (t,) in sdb.execute(
            "SELECT tag FROM etyma e WHERE coalesce(upper(e.status),'') != 'DELETE' AND "
            "(e.protogloss LIKE ? OR e.protoform LIKE ? OR "
            "replace(replace(replace(e.protoform,'-',''),'|',''),'◦','') LIKE ?)", (v, v, v))}
        if must_tag not in tags:
            fail(f"pform '{term}': expected etymon #{must_tag} in results, got {len(tags)} tags")
        else:
            ok(f"pform '{term}'", f"{len(tags)} reconstructions incl. #{must_tag}")

    # ---- 7. language result type: substring LIKE, proto-lects excluded, true counts ----
    rows = sdb.execute(
        "SELECT ln.language, count(l.rn) FROM languagenames ln JOIN lexicon l ON l.lgid=ln.lgid "
        "WHERE ln.language LIKE '%lahu%' AND ln.language NOT LIKE '*%' GROUP BY ln.lgid").fetchall()
    if not rows:
        fail("language search: 'lahu' matches no languages")
    elif any(n == 0 for _, n in rows):
        fail("language search: zero-reflex language surfaced")
    else:
        ok("language search", f"'lahu' → {len(rows)} lects, {sum(n for _, n in rows)} reflexes")
    star = sdb.execute("SELECT count(*) FROM languagenames WHERE language LIKE '*%'").fetchone()[0]
    if star == 0:
        fail("language search: no '*' proto-lects in search-db (exclusion untestable / data missing)")

    # ---- 8. subgroup: documented subtree rule (name substring | plg exact | grpno) ----
    groups = sdb.execute("SELECT grpid, grpno, grp, plg FROM languagegroups").fetchall()
    def subtree(term):
        tl = term.lower()
        pref = [str(no) for _, no, grp, plg in groups
                if tl in (grp or "").lower() or (plg or "").lower() == tl or str(no) == term]
        return {gid for gid, no, _, _ in groups
                if any(str(no) == p or str(no).startswith(p + ".") for p in pref)}
    kir = subtree("Kiranti")
    nref = sdb.execute(
        f"SELECT count(*) FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid "
        f"WHERE ln.grpid IN ({','.join('?' * len(kir))}) AND ln.language NOT LIKE '*%'",
        sorted(kir)).fetchone()[0] if kir else 0
    if not kir or not nref:
        fail(f"subgroup: 'Kiranti' subtree resolved to {len(kir)} grpids / {nref} reflexes")
    else:
        ok("subgroup subtree", f"Kiranti → {len(kir)} grpids, {nref} reflexes")
    pkc = subtree("PKC")
    if not pkc or pkc == kir:
        fail("subgroup: plg-exact 'PKC' did not resolve to its own subtree")
    else:
        ok("subgroup plg-exact", f"PKC → {len(pkc)} grpids")

    # ---- 9. golden corpus, report-only: the original's answers for the same battery ----
    print()
    for slug, q in [("gloss-dog", "dog"), ("gloss-hand", "hand"), ("gloss-frog-snail", "frog, snail")]:
        p = os.path.join(CORPUS, "pages", "search", f"{slug}.html")
        if not os.path.exists(p):
            continue
        page = open(p, encoding="utf8", errors="replace").read()
        # the original's gnis page embeds the raw lexicon result table; count its rows
        m = re.search(r'<table id="lexicon_resulttable".*?<tbody>(.*?)</tbody>', page, re.S)
        orig = len(re.findall(r"<tr[ >]", m.group(1))) if m else None
        ours = len(match("(" + ") OR (".join(" ".join(f'"{t}"' for t in toks(g)) for g in q.split(",")) + ")"))
        print(f"  corpus '{q}': original {orig if orig is not None else 'unparsed'} rows, modern {ours}"
              f"  (report-only: data vintage + word-boundary vs token semantics)")

    print()
    if failures:
        print(f"check search: {len(failures)} FAILURE(S)")
        for f in failures:
            print(f"  FAIL {f}")
        sys.exit(1)
    print("check search: all documented search semantics hold")


if __name__ == "__main__":
    main()
