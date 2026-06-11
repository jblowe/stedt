"""Cross-UI parity check: the legacy mirror as a rendering oracle for the modern pages.

Both UIs are built from the same stedt.sqlite, but through unrelated pipelines: the
modern pages via stedt/render/*, the /_legacy/ mirror via stedt/legacy/render.py — a
transform-faithful port of the original Perl app whose etymon and chapter pages embed
the RAW database table (untransformed reflex/gloss/srcid/protoform…; the original's
client JS prettifies it). That raw table is an oracle the modern renderer never
touches: for every shared page we re-derive what the modern markup MUST say from the
legacy raw values and diff. Any mismatch outside the named whitelist rules below is a
rendering divergence — the "delicate handling" loss class PARITY.md catalogs — and
fails the run.

Deliberate divergences are encoded as WHITELIST RULES, each tied to its PARITY.md
entry, so a change that silently widens a divergence still fails:

  W-PIPE      the '|' analysis delimiter is display-stripped where syllabification can
              place it, kept verbatim where it can't — exactly the original client's
              behavior (CORE-31). Both sides of the form check therefore drop pipes;
              pipe *placement* is the SYNC(syllabify) twins' contract, not ours. What
              this check still guarantees is no TEXT loss (the thesaurus ind-0 bug).
  W-GLOSS-SUP the etymon page suppresses an unnoted gloss equal to the protogloss
              (CORE-32); a noted row shows the protogloss as the icon's anchor.
  W-LGID-CANON language links resolve source-variant lgids to the canonical lect page
              (CORE-33/SEARCH); the rule (most visible forms, tie → lowest lgid, per
              (name, grpid)) is REIMPLEMENTED here from the DB so parity checks the
              renderer against the spec, not against itself.
  W-NREF-STAR the reflex count on chapter/search rows means ATTESTED rows; the etymon
              page's table also contains the *proto-lect rows (leading grpno-0.x bands,
              the original's layout — the bottom-section design was reverted 2026-06-11),
              so the cross-view count check compares against the page's non-star rows.
  W-ORDER     row/band/section ORDER differs by design (lgsort, Stammbaum, natural
              grpno); everything is compared as sets/multisets.
  W-SEQ-FMT   allofam sequence labels: original shows '1b', modern '1.2' (CHAP); the
              chapter check compares tag sets and facts, not sequence rendering.
  W-NREF      the original's num_recs counts every uid-8-tagged record (TBL-13),
              including HIDE/DELETED rows and *proto-lect attestations; the modern
              reflex count means "rows on the etymon page". So the chapter count is
              checked against the etymon page itself (cross-view consistency), not
              against num_recs.
  W-CHAP-ORPHAN an etymon filed under a chapter that has no chapters row is surfaced
              at its nearest real ancestor by the modern thesaurus; the faithful
              legacy port (WHERE chapter = semkey) orphans it.

Usage: python -m stedt.dev.parity  (or `stedt dev parity`); exits nonzero on
non-whitelisted divergences. Compares every page present in BOTH trees, so it works
on STEDT_LIMIT builds too (and says how many pages were skipped as one-sided).
"""

import html
import html.parser
import os
import re
import sqlite3
import sys
from collections import Counter

from stedt.paths import DB, SITE

MAX_LIST = 8  # examples shown per failing check


def _ws(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def _alt(s):
    """The protoform display normalisation (strip the re-added leading star, star each
    alternant) — mirrors text.py alt()/rows.js altstar by spec, not by import."""
    s = re.sub(r"^\s*\*\s*", "", str(s or ""))
    return re.sub(r"(⪤|\bOR\b|~|=)\s*\*?", r"\1 *", s)


def _form_key(s):
    """Form-text comparison key: whitespace-normalised, pipe-blind (W-PIPE), and
    fullwidth-paren-blind — the original's SylStation shields '(x)' as '（x）' during
    tokenization and restores BOTH kinds to ASCII on output, so a form whose stored
    text has genuine fullwidth parens (Chinese typography) faithfully renders with
    ASCII ones; our port keeps that behavior (SYNC(syllabify))."""
    return _ws(str(s or "").replace("|", "").replace("（", "(").replace("）", ")"))


def _strip_tags(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s))


# ───────────────────────────── modern etymon page ─────────────────────────────

class ModernEtymon(html.parser.HTMLParser):
    """Pull the reflex rows + subgroup bands out of a modern /etymon/{tag} page.

    Stack machine over (tag, classes); text inside .sylpop/.notepop/.anl is
    presentation the raw table doesn't have, so it never lands in the compared fields.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = {}      # rn -> {lang, lgid, form, gloss, pos, srcabbr, src, noted}
        self.bands = []     # (grpno, name, count)
        self._stack = []    # [(tag, classset)]
        self._row = None
        self._sink = None   # current text sink key on the row
        self._h4 = None     # collecting a band header: {grpno, name, c}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = set((a.get("class") or "").split())
        self._stack.append((tag, cls))
        m_id = re.fullmatch(r"r(n?)(\d+)", a.get("id") or "")
        if "rfx" in cls and m_id:
            self._row = {"rn": int(m_id.group(2)), "lang": "", "lgid": None, "form": "",
                         "gloss": None, "pos": "", "srcabbr": None, "src": "", "noted": False}
            self.rows[self._row["rn"]] = self._row
        if self._row is not None:
            if "rx-go" in cls:
                m = re.search(r"/language/(\d+)#rn\d+$", a.get("href") or "")
                self._row["lgid"] = int(m.group(1)) if m else None
            elif "lang" in cls:
                self._sink = "lang"
            elif "form" in cls:
                self._sink = "form"
            elif "g" in cls:
                self._sink = "gloss"
                self._row["gloss"] = ""
                self._row["noted"] = "noted" in cls
            elif "pos" in cls:
                self._sink = "pos"
            elif "src" in cls:
                self._sink = "src"
                m = re.search(r"/source/([^/]+)$", a.get("href") or "")
                if m:
                    self._row["srcabbr"] = m.group(1)
        if tag == "h4" and any("sg" in c for _, c in self._stack[:-1] if c):
            self._h4 = {"grpno": "", "name": "", "c": "", "sink": "name"}
        if self._h4 is not None and tag == "span":
            if "grpno" in cls:
                self._h4["sink"] = "grpno"
            elif "c" in cls:
                self._h4["sink"] = "c"

    def handle_endtag(self, tag):
        # pop to the matching open tag (the renderer emits well-formed markup)
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                closed = self._stack[i:]
                del self._stack[i:]
                break
        else:
            return
        for t, cls in closed:
            if "rfx" in cls:
                self._row, self._sink = None, None
            if self._row is not None and ({"lang", "g", "pos", "src"} & cls or ("form" in cls)):
                self._sink = "form" if self._in_form() and "form" not in cls else None
        if tag == "h4" and self._h4 is not None:
            h = self._h4
            self.bands.append((h["grpno"].strip(), h["name"].strip(), int(h["c"] or 0)))
            self._h4 = None
        if self._h4 is not None and tag == "span":
            self._h4["sink"] = "name"

    def _in_form(self):
        return any("form" in c for _, c in self._stack)

    def _excluded(self):
        return any({"sylpop", "notepop", "anl", "vias"} & c for _, c in self._stack)

    def handle_data(self, data):
        if self._h4 is not None:
            self._h4[self._h4["sink"]] += data
            return
        if self._row is None or self._sink is None or self._excluded():
            return
        if self._sink == "form" and any({"g", "pos"} & c for _, c in self._stack):
            return  # gloss/POS live inside .form but are their own fields
        key = self._sink
        self._row[key] = (self._row[key] or "") + data


# ───────────────────────────── legacy raw tables ─────────────────────────────

class LegacyTable(html.parser.HTMLParser):
    """Pull a raw prerendered table (thead th ids → row dicts) out of a legacy page."""

    def __init__(self, table_id):
        super().__init__(convert_charrefs=True)
        self.table_id = table_id
        self.cols = []
        self.rows = []
        self._in_table = self._in_head = False
        self._cell = None
        self._tr = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table" and a.get("id") == self.table_id:
            self._in_table = True
        if not self._in_table:
            return
        if tag == "thead":
            self._in_head = True
        elif tag == "tr":
            self._tr = []
        elif tag == "th":
            self._cell = [a.get("id") or "", ""]
        elif tag == "td":
            self._cell = [None, ""]

    def handle_endtag(self, tag):
        if not self._in_table:
            return
        if tag == "table":
            self._in_table = False
        elif tag == "thead":
            self._in_head = False
        elif tag in ("th", "td") and self._cell is not None:
            if self._tr is not None:
                self._tr.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._tr is not None:
            if self._in_head and self._tr and self._tr[0][0] is not None:
                self.cols = [c[0] for c in self._tr]
            elif not self._in_head and self.cols and len(self._tr) == len(self.cols):
                self.rows.append({k: c[1] for k, c in zip(self.cols, self._tr)})
            self._tr = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell[1] += data


# ───────────────────────────── etymon comparison ─────────────────────────────

def compare_etymon(tag, modern_html, legacy_html, protogloss, canon_of, diffs):
    mod = ModernEtymon(); mod.feed(modern_html)
    leg = LegacyTable("lexicon1"); leg.feed(legacy_html)
    lrows = {}
    for r in leg.rows:
        try:
            lrows[int(r["lexicon.rn"])] = r
        except (KeyError, ValueError):
            diffs["legacy-parse"].append(f"#{tag}: unparseable legacy row {r}")
    nattested = 0

    # 1. the two UIs must show exactly the same attestation rows
    only_m = sorted(set(mod.rows) - set(lrows))
    only_l = sorted(set(lrows) - set(mod.rows))
    if only_m:
        diffs["row-set"].append(f"#{tag}: modern-only rns {only_m[:6]}")
    if only_l:
        diffs["row-set"].append(f"#{tag}: legacy-only rns {only_l[:6]}")

    for rn in sorted(set(mod.rows) & set(lrows)):
        m, l = mod.rows[rn], lrows[rn]
        if not (l["languagenames.language"] or "").startswith("*"):
            nattested += 1  # W-NREF-STAR: the cross-view count means attested rows
        # 2. form text: pipe-blind equality (W-PIPE) — catches any character loss
        if _form_key(m["form"]) != _form_key(l["lexicon.reflex"]):
            diffs["form"].append(f"#{tag} rn{rn}: modern '{_ws(m['form'])}' vs raw '{_ws(l['lexicon.reflex'])}'")
        # 3. gloss: equal, except W-GLOSS-SUP
        lg = _ws(l["lexicon.gloss"])
        if m["noted"]:
            want_g = lg or _ws(protogloss)
        elif lg and lg != _ws(protogloss):
            want_g = lg
        else:
            want_g = None
        got_g = _ws(m["gloss"]) if m["gloss"] is not None else None
        if got_g != want_g:
            diffs["gloss"].append(f"#{tag} rn{rn}: modern {got_g!r} vs expected {want_g!r} (raw {lg!r})")
        # 4. POS chip == raw gfn
        if _ws(m["pos"]) != _ws(l["lexicon.gfn"]):
            diffs["pos"].append(f"#{tag} rn{rn}: modern '{_ws(m['pos'])}' vs raw '{_ws(l['lexicon.gfn'])}'")
        # 5. language: the canonical page for the same lect (W-LGID-CANON), same name
        want_lgid = canon_of.get(int(l["languagenames.lgid"]), int(l["languagenames.lgid"]))
        if m["lgid"] != want_lgid:
            diffs["lgid"].append(f"#{tag} rn{rn}: modern lgid {m['lgid']} vs canonical {want_lgid} (raw {l['languagenames.lgid']})")
        if _ws(m["lang"]) != _ws(l["languagenames.language"]):
            diffs["language"].append(f"#{tag} rn{rn}: modern '{_ws(m['lang'])}' vs raw '{_ws(l['languagenames.language'])}'")
        # 6. source: same source page, citation text + ': locus'
        if (m["srcabbr"] or "") != l["languagenames.srcabbr"]:
            diffs["srcabbr"].append(f"#{tag} rn{rn}: modern '{m['srcabbr']}' vs raw '{l['languagenames.srcabbr']}'")
        want_src = _ws(l["citation"]) or l["languagenames.srcabbr"]
        if l["lexicon.srcid"]:
            want_src += f": {l['lexicon.srcid']}"
        if _ws(m["src"]) != _ws(want_src):
            diffs["src"].append(f"#{tag} rn{rn}: modern '{_ws(m['src'])}' vs expected '{_ws(want_src)}'")

    # 7. subgroup bands: same (grpno, name, member-count) partition (order is W-ORDER)
    want_bands = Counter()
    for r in lrows.values():
        want_bands[(r["languagegroups.grpno"], r["languagegroups.grp"] or "—")] += 1
    got_bands = Counter()
    for grpno, name, c in mod.bands:
        if c:  # a count-less band is a synthetic header carrying only a subgroup note
            got_bands[(grpno, name)] += c
    if got_bands != want_bands:
        miss = {k: v for k, v in want_bands.items() if got_bands.get(k) != v}
        extra = {k: v for k, v in got_bands.items() if want_bands.get(k) != v}
        diffs["bands"].append(f"#{tag}: expected {dict(list(miss.items())[:3])} got {dict(list(extra.items())[:3])}")

    return nattested


# ───────────────────────────── language pages (DB oracle) ─────────────────────────────
# The original had no language page (its language view was a gnis search), so the oracle
# here is the database itself: a canonical language page must show exactly the visible
# rows of every member lgid of its lect, raw form (pipe-blind) and raw gloss intact.

def parse_language_rows(page_html):
    """Language-page reflex rows live inside lazy <script type="text/html"> templates,
    which HTMLParser treats as opaque text — parse each template body separately."""
    mod = ModernEtymon()
    mod.feed(page_html)
    for body in re.findall(r'<script type="text/html" class="seg-src">(.*?)</script>', page_html, re.S):
        mod.feed(body)
    return mod.rows


def compare_language(lgid, page_html, truth, diffs):
    rows = parse_language_rows(page_html)
    only_m = sorted(set(rows) - set(truth))
    only_d = sorted(set(truth) - set(rows))
    if only_m:
        diffs["lang-row-set"].append(f"lg{lgid}: page-only rns {only_m[:6]}")
    if only_d:
        diffs["lang-row-set"].append(f"lg{lgid}: db-only rns {only_d[:6]}")
    for rn in set(rows) & set(truth):
        m, (reflex, gloss) = rows[rn], truth[rn]
        if _form_key(m["form"]) != _form_key(reflex):
            diffs["lang-form"].append(f"lg{lgid} rn{rn}: page '{_ws(m['form'])}' vs raw '{_ws(reflex)}'")
        if _ws(m["gloss"] or "") != _ws(gloss):
            diffs["lang-gloss"].append(f"lg{lgid} rn{rn}: page {_ws(m['gloss'] or '')!r} vs raw {_ws(gloss)!r}")
    return len(rows)


# ───────────────────────────── source pages (DB oracle) ─────────────────────────────

def compare_source(abbr, page_html, truth, canon_of, diffs):
    """The 'Languages in this source' list must name every lgid of the source with its
    visible-reflex count, linking each to its canonical lect page (W-LGID-CANON)."""
    m = re.search(r'<section class="reflexes"><h3>Languages in this source</h3>(.*?)</section>', page_html, re.S)
    got = Counter()
    if m:
        for row in re.findall(r'<div class="rfx">(.*?)</div>', m.group(1), re.S):
            lk = re.search(r'<a class="lang" href="[^"]*/language/(\d+)">(.*?)</a>', row)
            ct = re.search(r'<span class="src">([\d,]+) reflex', row)
            if lk:
                got[(int(lk.group(1)), _ws(_strip_tags(lk.group(2))), int(ct.group(1).replace(",", "")) if ct else 0)] += 1
    want = Counter()
    for lgid, name, n in truth:
        # the page deliberately lists only attested, non-proto languages: a source's
        # zero-reflex languagenames rows and its *proto-lect rows (those are counted
        # in the page's 'reconstruction records' figure instead) don't get rows
        if n == 0 or (name or "").startswith("*"):
            continue
        want[(canon_of.get(lgid, lgid), _ws(name), n)] += 1
    if got != want:
        miss = list((want - got).keys())[:3]
        extra = list((got - want).keys())[:3]
        diffs["source-langs"].append(f"{abbr}: missing {miss} unexpected {extra}")


# ───────────────────────────── chapter comparison ─────────────────────────────

def compare_chapter(semkey, modern_html, legacy_html, orphan_home, page_rows, diffs):
    """A thesaurus node and the legacy chapter page must list the same etyma, with the
    same protoform/protogloss/plg facts and reflex counts."""
    leg = LegacyTable("etyma_resulttable"); leg.feed(legacy_html)
    want = {}
    for r in leg.rows:
        try:
            want[int(r["etyma.tag"])] = r
        except (KeyError, ValueError):
            diffs["legacy-parse"].append(f"{semkey}: unparseable legacy etyma row {r}")
    got = {}
    for m in re.finditer(
        r'<div class="ety-hit"><a href="[^"]*/etymon/(\d+)" class="pf2 lat">(.*?)</a>'
        r'<span class="pg2">(.*?)</span><span class="tagn">(.*?)</span></div>', modern_html, re.S
    ):
        tag, pf, pg, tagn = int(m.group(1)), m.group(2), m.group(3), m.group(4)
        got[tag] = {"pf": re.sub(r"^\*", "", _strip_tags(pf)), "pg": _strip_tags(pg), "tagn": _strip_tags(tagn)}

    # W-CHAP-ORPHAN: an etymon filed under a chapter that has no chapters row is
    # surfaced at its nearest real ancestor by the modern thesaurus; the faithful
    # legacy port (WHERE chapter = semkey) orphans it.
    only_m = [t for t in sorted(set(got) - set(want)) if orphan_home.get(t) != semkey]
    if only_m or set(want) - set(got):
        diffs["chapter-etyma"].append(
            f"{semkey}: modern-only {only_m[:6]}, legacy-only {sorted(set(want) - set(got))[:6]}"
        )
    for tag in sorted(set(got) & set(want)):
        g, w = got[tag], want[tag]
        if _form_key(g["pf"]) != _form_key(_alt(w["etyma.protoform"])):
            diffs["chapter-pform"].append(f"{semkey} #{tag}: modern '{g['pf']}' vs raw '{w['etyma.protoform']}'")
        if _ws(g["pg"]) != _ws(w["etyma.protogloss"]):
            diffs["chapter-pgloss"].append(f"{semkey} #{tag}: modern '{g['pg']}' vs raw '{w['etyma.protogloss']}'")
        if w["languagegroups.plg"] and f' {w["languagegroups.plg"]} #' not in f' {g["tagn"]}':
            diffs["chapter-plg"].append(f"{semkey} #{tag}: '{w['languagegroups.plg']}' not in '{g['tagn']}'")
        # W-NREF: the count shown on the chapter listing must equal the rows actually
        # rendered on that etymon's page (cross-view consistency)
        nm = re.search(r"· ([\d,]+) reflex", g["tagn"])
        nref = int(nm.group(1).replace(",", "")) if nm else 0
        if tag in page_rows and nref != page_rows[tag]:
            diffs["chapter-nref"].append(f"{semkey} #{tag}: chapter says {nref} reflexes, etymon page shows {page_rows[tag]}")
        if (w["etyma.public"] == "0") != ("provisional" in g["tagn"]):
            diffs["chapter-prov"].append(f"{semkey} #{tag}: public={w['etyma.public']} but tagn '{g['tagn']}'")


# ───────────────────────────── driver ─────────────────────────────

def canonical_map(db):
    """W-LGID-CANON, re-derived from the DB: per (language name, grpid), the canonical
    lgid is the variant with the most visible forms; tie → lowest lgid."""
    rows = db.execute("""
        SELECT ln.lgid, ln.language, ln.grpid, count(l.rn) AS n
        FROM languagenames ln LEFT JOIN lexicon l ON l.lgid=ln.lgid
            AND coalesce(upper(l.status),'') NOT IN ('HIDE','DELETED')
        GROUP BY ln.lgid""").fetchall()
    groups = {}
    for lgid, language, grpid, n in rows:
        groups.setdefault((language, grpid), []).append((lgid, n or 0))
    canon_of = {}
    for lst in groups.values():
        canon = max(lst, key=lambda t: (t[1], -t[0]))[0]
        for lgid, _ in lst:
            canon_of[lgid] = canon
    return canon_of


def main():
    me, le = os.path.join(SITE, "etymon"), os.path.join(SITE, "_legacy", "etymon")
    if not (os.path.isdir(me) and os.path.isdir(le)):
        sys.exit("parity: build both UIs first (stedt build render + stedt build legacy)")
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    protogloss = dict(db.execute("SELECT tag, coalesce(protogloss,'') FROM etyma"))
    canon_of = canonical_map(db)
    # W-CHAP-ORPHAN: nearest real chapter node for etyma filed under nonexistent ones
    nodes = {sk for (sk,) in db.execute("SELECT semkey FROM chapters WHERE semkey IS NOT NULL") if sk}
    orphan_home = {}
    for t, ch in db.execute("SELECT tag, chapter FROM etyma WHERE coalesce(chapter,'') != ''"):
        if ch in nodes:
            continue
        parts = ch.split(".")
        while parts:
            parts.pop()
            anc = ".".join(parts)
            if anc in nodes:
                orphan_home[t] = anc
                break

    mtags = {int(d) for d in os.listdir(me) if d.isdigit()}
    ltags = {int(d) for d in os.listdir(le) if d.isdigit()}
    both = sorted(mtags & ltags)
    diffs = {k: [] for k in ("legacy-parse", "row-set", "form", "gloss", "pos", "lgid",
                             "language", "srcabbr", "src", "bands",
                             "chapter-etyma", "chapter-pform", "chapter-pgloss",
                             "chapter-plg", "chapter-nref", "chapter-prov",
                             "lang-row-set", "lang-form", "lang-gloss", "source-langs")}
    nrows, page_rows = 0, {}
    for tag in both:
        mh = open(os.path.join(me, str(tag), "index.html"), encoding="utf8").read()
        lh = open(os.path.join(le, str(tag), "index.html"), encoding="utf8").read()
        page_rows[tag] = compare_etymon(tag, mh, lh, protogloss.get(tag, ""), canon_of, diffs)
        nrows += page_rows[tag]

    mc, lc = os.path.join(SITE, "thesaurus"), os.path.join(SITE, "_legacy", "chap")
    nchap = 0
    if os.path.isdir(mc) and os.path.isdir(lc):
        for sk in sorted(set(os.listdir(mc)) & set(os.listdir(lc))):
            mp, lp = os.path.join(mc, sk, "index.html"), os.path.join(lc, sk, "index.html")
            if os.path.isfile(mp) and os.path.isfile(lp):
                nchap += 1
                compare_chapter(sk, open(mp, encoding="utf8").read(), open(lp, encoding="utf8").read(), orphan_home, page_rows, diffs)

    # language pages: DB oracle (members of each canonical lect -> visible rows)
    members = {}
    for lgid, c in canon_of.items():
        members.setdefault(c, []).append(lgid)
    truth_rows = {}  # lgid -> {rn: (reflex, gloss)}
    for rn, lgid, reflex, gloss in db.execute(
            "SELECT rn, lgid, coalesce(reflex,''), coalesce(gloss,'') FROM lexicon l "
            "WHERE coalesce(upper(l.status),'') NOT IN ('HIDE','DELETED')"):
        truth_rows.setdefault(lgid, {})[rn] = (reflex, gloss)
    ml = os.path.join(SITE, "language")
    nlang = nlrows = 0
    if os.path.isdir(ml):
        for d in sorted(os.listdir(ml)):
            if not d.isdigit():
                continue
            lgid = int(d)
            if canon_of.get(lgid, lgid) != lgid:
                continue  # redirect stub for a non-canonical lgid
            truth = {}
            for mem in members.get(lgid, [lgid]):
                truth.update(truth_rows.get(mem, {}))
            page = open(os.path.join(ml, d, "index.html"), encoding="utf8").read()
            nlrows += compare_language(lgid, page, truth, diffs)
            nlang += 1

    # source pages: DB oracle (every lgid of the source + its visible-reflex count)
    src_truth = {}
    for abbr, lgid, name, n in db.execute(f"""
            SELECT ln.srcabbr, ln.lgid, ln.language, count(l.rn)
            FROM languagenames ln LEFT JOIN lexicon l ON l.lgid=ln.lgid
                AND coalesce(upper(l.status),'') NOT IN ('HIDE','DELETED')
            GROUP BY ln.lgid"""):
        src_truth.setdefault(abbr, []).append((lgid, name, n))
    ms = os.path.join(SITE, "source")
    nsrc = 0
    if os.path.isdir(ms):
        for d in sorted(os.listdir(ms)):
            p = os.path.join(ms, d, "index.html")
            if os.path.isfile(p) and d in src_truth:
                compare_source(d, open(p, encoding="utf8").read(), src_truth[d], canon_of, diffs)
                nsrc += 1

    print(f"parity: {len(both)} etymon pages ({nrows} shared reflex rows), {nchap} chapter pages, "
          f"{nlang} language pages ({nlrows} rows), {nsrc} source pages compared")
    skew = mtags ^ ltags
    if skew:
        print(f"parity: note — {len(mtags - ltags)} modern-only / {len(ltags - mtags)} legacy-only etymon pages skipped (partial build?)")
    bad = False
    for check, items in diffs.items():
        if not items:
            continue
        bad = True
        print(f"\nFAIL {check}: {len(items)} divergence(s)")
        for it in items[:MAX_LIST]:
            print(f"  {it}")
        if len(items) > MAX_LIST:
            print(f"  … and {len(items) - MAX_LIST} more")
    if bad:
        sys.exit(1)
    print("parity: clean — every compared fact matches the legacy oracle (modulo the documented whitelist)")


if __name__ == "__main__":
    main()
