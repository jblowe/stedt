"""Page chrome (masthead/nav/footer) + shared, DB-querying view helpers."""

from markupsafe import Markup

from .config import _CSS_VER, _JS_VER
from .db import ETY_LIVE, LEX_VISIBLE, chunked_in, con
from .templating import env
from .text import esc

_NAV = [
    ("thesaurus", "/thesaurus", "Thesaurus"),
    ("reconstructions", "/reconstructions", "Reconstructions"),
    ("languages", "/languages", "Languages"),
    ("sources", "/sources", "Sources"),
    ("about", "/about", "About"),
]

_BASE = env.get_template("base.html")


_DESC = (
    "The Sino-Tibetan Etymological Dictionary and Thesaurus: reconstructions, reflexes, "
    "languages and sources for the comparative study of Sino-Tibetan."
)


def page(title, body, q="", nav="", desc=""):
    # title/q are pre-escaped with esc() (html.escape's entity choices, e.g. &#x27;/&quot;) and
    # body is already-rendered HTML, so all three pass as Markup — emitted verbatim, not re-escaped.
    return _BASE.render(
        title=Markup(esc(title)),
        body=Markup(body),
        q=Markup(esc(q)),
        nav=nav,
        nav_items=_NAV,
        css_ver=_CSS_VER,
        js_ver=_JS_VER,
        desc=Markup(esc(desc or _DESC)),
    )


def breadcrumb(conn, semkey, ancestors_only=False):
    """Linked chapter chain for a filing key. The etymon page wants the full chain (the filing node
    is an ancestor of the etymon); a thesaurus node page passes ancestors_only=True so the crumb
    never names the page itself — the current page is the h1, never its own crumb (sitewide rule)."""
    parts = (semkey or "").split(".")
    out = []
    for i in range(1, len(parts) + 1 - (1 if ancestors_only else 0)):
        sk = ".".join(parts[:i])
        r = conn.execute("SELECT chaptertitle FROM chapters WHERE semkey=?", (sk,)).fetchone()
        if not r and "." not in sk:  # integer chapter level: borrow the N.0 overview title
            r = conn.execute("SELECT chaptertitle FROM chapters WHERE semkey=?", (sk + ".0",)).fetchone()
        if r:
            out.append(f'<a href="/thesaurus/{sk}">{esc(r[0])}</a>')
    return " &nbsp;›&nbsp; ".join(out)


def group_lineage(conn, grpno):
    """Genetic lineage (ancestors incl. self) by walking grpno prefixes."""
    out = []
    if not grpno:
        return out
    parts = str(grpno).split(".")
    for i in range(1, len(parts) + 1):
        r = conn.execute("SELECT grpid,grpno,grp FROM languagegroups WHERE grpno=?", (".".join(parts[:i]),)).fetchone()
        if r:
            out.append(r)
    return out


def reflex_counts(conn, tags=None):
    """Map {etymon tag: number of attested reflexes}. tags=None counts every etymon in one pass;
    pass a tag set to limit it. Excludes proto-form stand-ins (language '*…') so the count matches
    the etymon page's own, reflex_semkey_counts(), and the search query — those are reconstructions,
    not attested reflexes."""
    JW = (
        "FROM lx_et_hash h JOIN lexicon l ON l.rn=h.rn JOIN languagenames ln ON ln.lgid=l.lgid "
        f"WHERE h.tag>0 AND ln.language NOT LIKE '*%' AND {LEX_VISIBLE}"
    )
    if tags is None:
        rows = conn.execute(f"SELECT h.tag AS tag, count(DISTINCT h.rn) n {JW} GROUP BY h.tag")
        return {r["tag"]: r["n"] for r in rows}
    out = {}
    for r in chunked_in(conn, f"SELECT h.tag AS tag, count(DISTINCT h.rn) n {JW} AND h.tag IN ({{qm}}) GROUP BY h.tag",
                        [t for t in tags if t]):
        out[r["tag"]] = r["n"]
    return out


def proto_labels(conn, tags):
    """Map {tag: (protoform, protogloss, plg, mesoroots, family)} for a set of etymon tags,
    restricted to non-DELETE etyma (only those have a built page, so callers can gate links on
    membership). Feeds the syllable popover's elink-style card:
    - mesoroots: [(plg, form, gloss, grpno), …] in Stammbaum order (grp0..grp4, variant — the
      original elink popup's ORDER BY); grpno anchors the link to the etymon page's meso row.
    - family: [(seq, tag, plg, protoform, protogloss), …] — the computed allofam family (same
      chapter, same integer sequence; the original's elink allofams query), [] when the etymon
      stands alone. seq is the raw curated sequence (callers format the label)."""
    tags = [t for t in tags if t]
    out = {}
    fam_key = {}  # (chapter, int seq) -> [tags interested]
    for r in chunked_in(
        conn,
        f"""SELECT e.tag, e.protoform, e.protogloss, g.plg AS plg, e.chapter, e.sequence
        FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
        WHERE e.tag IN ({{qm}}) AND {ETY_LIVE}""",
        tags,
    ):
        out[r["tag"]] = (r["protoform"], r["protogloss"], r["plg"], [], [])
        try:
            if (r["chapter"] or "") and r["sequence"] is not None and float(r["sequence"]) >= 1:
                fam_key.setdefault((r["chapter"], int(float(r["sequence"]))), []).append(r["tag"])
        except (TypeError, ValueError):
            pass
    for r in chunked_in(
        conn,
        """SELECT m.tag, g.plg AS plg, m.form, m.gloss, g.grpno AS grpno FROM mesoroots m
        LEFT JOIN languagegroups g ON g.grpid=m.grpid WHERE m.tag IN ({qm})
        ORDER BY g.grp0, g.grp1, g.grp2, g.grp3, g.grp4, m.variant""",
        tags,
    ):
        if r["tag"] in out:
            out[r["tag"]][3].append((r["plg"], r["form"], r["gloss"], r["grpno"]))
    for r in chunked_in(
        conn,
        f"""SELECT e.tag, e.sequence, e.chapter, e.protoform, e.protogloss, g.plg AS plg
        FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
        WHERE e.chapter IN ({{qm}}) AND CAST(e.sequence AS INTEGER) > 0 AND {ETY_LIVE}
        ORDER BY e.sequence""",
        sorted({c for c, _ in fam_key}),
    ):
        for t in fam_key.get((r["chapter"], int(float(r["sequence"]))), []):
            out[t][4].append((r["sequence"], r["tag"], r["plg"], r["protoform"], r["protogloss"]))
    for v in out.values():
        if len(v[4]) < 2:  # an etymon alone in its sequence has no family to show
            v[4].clear()
    return out


def source_reference(s):
    """A source's full reference: 'Author. Year. Title. Imprint' — the ONE formatter shared by the
    sources index, the source page's reference line, and its copy-citation, so the imprint/venue can't
    appear in one and vanish from another. s is a srcbib row (author, year, title, imprint)."""
    final = (".", "?", "!", "。", "？", "！")  # already sentence-final: don't add another period
    au = (s["author"] or "").rstrip()
    if au and not au.endswith("."):
        au += "."
    yr = (str(s["year"]).rstrip() if s["year"] else "")
    if yr and not yr.endswith("."):  # 'n.d.' already carries its period
        yr += "."
    base = " ".join(x for x in (au, yr, s["title"]) if x)
    if s["imprint"]:
        sep = "" if base.rstrip().endswith(final) else "."  # avoid 'Title.. Imprint' / 'vadimus?.'
        base = (base.rstrip() + sep + " " + s["imprint"]) if base else s["imprint"]
    return base


_CANON = None


def canonical_languages():
    """Collapse the source-variant lgids of one (language name, subgroup) to a single canonical
    page — the most-attested lgid — so a 'language' is a lect (not a language×source pair) and its
    words from every source live on one page; the other lgids redirect to it. Variants almost
    always agree on subgroup/ISO, so grouping by (name, grpid) is safe and won't merge homonyms in
    different branches. Returns (canon_of {lgid: canonical_lgid}, members {canonical_lgid: [lgids]})."""
    global _CANON
    if _CANON is None:
        conn = con()
        rows = conn.execute(f"""SELECT ln.lgid AS lgid, ln.language AS language, ln.grpid AS grpid,
                count(l.rn) AS n
            FROM languagenames ln LEFT JOIN lexicon l ON l.lgid=ln.lgid AND {LEX_VISIBLE}
            GROUP BY ln.lgid""").fetchall()
        conn.close()
        groups = {}
        for r in rows:
            groups.setdefault((r["language"], r["grpid"]), []).append((r["lgid"], r["n"] or 0))
        canon_of, members = {}, {}
        for lst in groups.values():
            canon = max(lst, key=lambda t: (t[1], -t[0]))[0]  # most forms; tie -> lowest lgid
            ids = sorted(t[0] for t in lst)
            members[canon] = ids
            for lid in ids:
                canon_of[lid] = canon
        _CANON = (canon_of, members)
    return _CANON


def canon_lgid(lgid):
    """The canonical lgid for a language×source lgid, so internal links skip the redirect hop."""
    return canonical_languages()[0].get(lgid, lgid)


# SYNC(entity-urls) ↔ web/src/rows.js {etymonHref,sourceHref,languageHref,reflexHref,categoryHref}.
# Canonical site-relative URLs — the ONE place each entity's address is built server-side (mirrors
# the client builders in web/src/rows.js). Language links resolve to the canonical lgid here so they
# skip the redirect hop; the client builders use the raw lgid and rely on the redirect. The build
# step (stedt/build/static.py rewrite()) applies the /stedt base prefix to these.
def etymon_href(tag):
    return f"/etymon/{tag}"


def source_href(srcabbr):
    return f"/source/{esc(srcabbr)}"


def language_href(lgid):
    return f"/language/{canon_lgid(lgid)}"


def reflex_href(lgid, rn):
    return f"/language/{canon_lgid(lgid)}#rn{rn}"
