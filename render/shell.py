"""Page chrome (masthead/nav/footer) + shared, DB-querying view helpers."""
from .config import _CSS_VER, _JS_VER
from .db import con
from .text import esc

_NAV = [("thesaurus", "/thesaurus", "Thesaurus"),
        ("reconstructions", "/reconstructions", "Reconstructions"),
        ("languages", "/languages", "Languages"),
        ("sources", "/sources", "Sources"),
        ("about", "/about", "About")]


def page(title, body, q="", nav=""):
    nav_parts = []
    for key, href, label in _NAV:
        cls = ' class="active"' if nav == key else ''
        nav_parts.append(f'<a href="{href}"{cls}>{label}</a>')
    navhtml = "".join(nav_parts)
    search_box = (f'<form class="hsearch" action="/search" method="get">'
                  f'<input name="q" placeholder="search…" value="{esc(q)}" autocomplete="off"></form>')
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · STEDT</title>
<link rel="icon" href="data:,">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;1,9..144,400&family=Charis+SIL:ital,wght@0,400;0,700;1,400;1,700&family=Noto+Serif+SC:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/site.css?v={_CSS_VER}"></head><body>
<div class="top"></div>
<header class="mast">
  <div class="brand">
    <span class="wm"><a href="/">STEDT</a></span>
    <span class="sub">Sino-Tibetan Etymological Dictionary &amp; Thesaurus</span>
  </div>
  <nav class="main">{navhtml}</nav>
  {search_box}
</header>
<main>{body}</main>
<footer>Preview interface for STEDT · <a href="https://github.com/larc-iu/stedt">github.com/larc-iu/stedt</a> · <a href="/_legacy/" rel="nofollow">Legacy interface</a></footer>
<script src="/static/site.js?v={_JS_VER}"></script>
<script type="module" src="/assets/stedt-search.js"></script>
</body></html>"""

def breadcrumb(c, semkey):
    parts = (semkey or "").split('.')
    out = []
    for i in range(1, len(parts) + 1):
        sk = '.'.join(parts[:i])
        r = c.execute("SELECT chaptertitle FROM chapters WHERE semkey=?", (sk,)).fetchone()
        if not r and '.' not in sk:  # integer chapter level: borrow the N.0 overview title
            r = c.execute("SELECT chaptertitle FROM chapters WHERE semkey=?", (sk + '.0',)).fetchone()
        if r: out.append(f'<a href="/thesaurus/{sk}">{esc(r[0])}</a>')
    return ' &nbsp;›&nbsp; '.join(out)

def group_lineage(c, grpno):
    """Genetic lineage (ancestors incl. self) by walking grpno prefixes."""
    out = []
    if not grpno: return out
    parts = str(grpno).split('.')
    for i in range(1, len(parts) + 1):
        r = c.execute("SELECT grpid,grpno,grp FROM languagegroups WHERE grpno=?", ('.'.join(parts[:i]),)).fetchone()
        if r: out.append(r)
    return out

def reflex_counts(c, tags=None):
    """Map {etymon tag: number of attested reflexes}. tags=None counts every etymon in one pass;
    pass a tag set to limit it. Excludes proto-form stand-ins (language '*…') so the count matches
    the etymon page's own, reflex_semkey_counts(), and the search query — those are reconstructions,
    not attested reflexes."""
    JW = ("FROM lx_et_hash h JOIN lexicon l ON l.rn=h.rn JOIN languagenames ln ON ln.lgid=l.lgid "
          "WHERE h.tag>0 AND ln.language NOT LIKE '*%'")
    if tags is None:
        rows = c.execute(f"SELECT h.tag AS tag, count(DISTINCT h.rn) n {JW} GROUP BY h.tag")
        return {r['tag']: r['n'] for r in rows}
    tags = [t for t in tags if t]
    out = {}
    for i in range(0, len(tags), 900):
        chunk = tags[i:i + 900]; qm = ','.join('?' * len(chunk))
        for r in c.execute(f"SELECT h.tag AS tag, count(DISTINCT h.rn) n {JW} "
                           f"AND h.tag IN ({qm}) GROUP BY h.tag", chunk):
            out[r['tag']] = r['n']
    return out

def proto_labels(c, tags):
    """Map {tag: protoform} for a set of etymon tags, restricted to non-DELETE etyma (only
    those have a built page, so callers can gate links on membership)."""
    tags = [t for t in tags if t]
    out = {}
    for i in range(0, len(tags), 900):
        chunk = tags[i:i + 900]
        qm = ','.join('?' * len(chunk))
        for r in c.execute(f"SELECT tag,protoform FROM etyma WHERE tag IN ({qm}) "
                           f"AND coalesce(upper(status),'')!='DELETE'", chunk):
            out[r['tag']] = r['protoform']
    return out

_CANON = None
def canonical_languages():
    """Collapse the source-variant lgids of one (language name, subgroup) to a single canonical
    page — the most-attested lgid — so a 'language' is a lect (not a language×source pair) and its
    words from every source live on one page; the other lgids redirect to it. Variants almost
    always agree on subgroup/ISO, so grouping by (name, grpid) is safe and won't merge homonyms in
    different branches. Returns (canon_of {lgid: canonical_lgid}, members {canonical_lgid: [lgids]})."""
    global _CANON
    if _CANON is None:
        c = con()
        rows = c.execute("""SELECT ln.lgid AS lgid, ln.language AS language, ln.grpid AS grpid,
                count(l.rn) AS n
            FROM languagenames ln LEFT JOIN lexicon l ON l.lgid=ln.lgid
            GROUP BY ln.lgid""").fetchall()
        c.close()
        groups = {}
        for r in rows:
            groups.setdefault((r['language'], r['grpid']), []).append((r['lgid'], r['n'] or 0))
        canon_of, members = {}, {}
        for lst in groups.values():
            canon = max(lst, key=lambda t: (t[1], -t[0]))[0]   # most forms; tie -> lowest lgid
            ids = sorted(t[0] for t in lst)
            members[canon] = ids
            for lid in ids:
                canon_of[lid] = canon
        _CANON = (canon_of, members)
    return _CANON

def canon_lgid(lgid):
    """The canonical lgid for a language×source lgid, so internal links skip the redirect hop."""
    return canonical_languages()[0].get(lgid, lgid)
