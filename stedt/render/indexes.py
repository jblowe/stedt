"""Index/browse pages: home, about, reconstructions, languages, sources, search, thesaurus."""

import re
import json

from markupsafe import Markup

from .config import CITE_BASE, PREVIEW, TREE_INDENT_PX
from .db import ECAT, ETY_LIVE, LEX_VISIBLE, con, reflex_semkey_counts
from .text import esc, alt, natkey, rcount_txt, rfx_noun, sortkey
from .notes import render_note
from .shell import page, breadcrumb, reflex_counts, canon_lgid, etymon_href, source_reference
from .templating import env

# ---------------------------------------------------------------- views
_HOME = env.get_template("home.html")
_ABOUT = env.get_template("about.html")
_LANGUAGES = env.get_template("languages_index.html")
_SOURCES = env.get_template("sources_index.html")
_RECONSTRUCTIONS = env.get_template("reconstructions.html")
_SEARCH = env.get_template("search.html")
_THESAURUS = env.get_template("thesaurus.html")


def home():
    return page("Home", _HOME.render(preview=PREVIEW))


def not_found():
    """GitHub Pages serves /404.html for any missing path; the standard shell keeps the masthead
    search + nav, so a dead link is one step from recovery. Asset/nav URLs are root-absolute with
    the BASE prefix already applied, so they resolve from any URL depth."""
    body = (
        '<div class="sr"><h1>Page not found</h1>'
        "<p>There’s nothing at this address — the entry may have been renumbered or withdrawn.</p>"
        '<p>Try a <a href="/search">search</a>, or start from the '
        '<a href="/thesaurus">thesaurus</a>, <a href="/reconstructions">reconstructions</a>, '
        '<a href="/languages">languages</a>, or <a href="/sources">sources</a>.</p></div>'
    )
    return page("Page not found", body)


def about():
    conn = con()
    one = lambda sql: conn.execute(sql).fetchone()[0]
    ety = one(f"SELECT count(*) FROM etyma e WHERE {ETY_LIVE}")
    rfx = one(
        "SELECT count(*) FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid "
        f"WHERE ln.language NOT LIKE '*%' AND {LEX_VISIBLE}"
    )
    # a "language" is a lect = (name, subgroup), matching the Languages index header + canonicalization
    lgs = one(f"""SELECT count(*) FROM (SELECT 1 FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid
        WHERE ln.language!='' AND ln.language NOT LIKE '*%' AND {LEX_VISIBLE} GROUP BY ln.language, ln.grpid)""")
    # any visible record counts — attested or previously-published reconstruction (so a source
    # holding only reconstructions, e.g. JRO-Tilung, still counts; matches the sources index)
    src = one(f"""SELECT count(*) FROM srcbib sb WHERE EXISTS(
        SELECT 1 FROM languagenames ln JOIN lexicon l ON l.lgid=ln.lgid
        WHERE ln.srcabbr=sb.srcabbr AND {LEX_VISIBLE})""")
    conn.close()
    body = _ABOUT.render(ety=f"{ety:,}", rfx=f"{rfx:,}", lgs=f"{lgs:,}", src=f"{src:,}", cite_base=CITE_BASE)
    return page("About", body, nav="about")


def reconstructions():
    # The whole list (~4k etyma) is shipped once as compact JSON and rendered
    # client-side in windows of CHUNK rows, with an instant in-page filter. This
    # keeps the initial DOM small (~200 nodes vs ~31k) on slow devices while the
    # gloss-ordered full set stays a single, filterable, statically-hosted page.
    conn = con()
    rows = conn.execute(f"""SELECT e.tag, e.protoform, e.protogloss, g.plg AS plg, e.exemplary, e.public
        FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
        WHERE {ETY_LIVE} ORDER BY e.protogloss, e.tag""").fetchall()
    counts = reflex_counts(conn)
    conn.close()
    total = len(rows)
    data = [
        # ship the RAW protoform; the client's etymonRow applies altstar() (same as search), so the
        # reconstructions index and search render an etymon identically. Trailing fields:
        # exemplary flag, provisional flag (public=0).
        [r["tag"], r["protoform"] or "", r["protogloss"] or "", r["plg"] or "", counts.get(r["tag"], 0),
         1 if (r["exemplary"] or "") == "x" else 0, 0 if r["public"] else 1]
        for r in rows
    ]
    # < keeps the payload from breaking out of the <script> tag and stays valid JSON.
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("<", "\u003c")
    return page(
        "Reconstructions",
        _RECONSTRUCTIONS.render(total=f"{total:,}", payload=Markup(payload)),
        nav="reconstructions",
    )


def languages_index():
    conn = con()
    # every genetic-classification node, so headline subgroups (Lolo-Burmese, Bodo-Garo, Tani, …)
    # and the two "previously published reconstructions" groups appear as headings even when no
    # member language is directly attested under them.
    allgroups = conn.execute("SELECT grpid, grpno, grp, plg FROM languagegroups WHERE grpid IS NOT NULL").fetchall()
    rows = conn.execute(f"""SELECT ln.grpid AS grpid, ln.language AS language, ln.lgid AS lgid, count(*) AS n
        FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid
        WHERE ln.language NOT LIKE '*%' AND {LEX_VISIBLE}
        GROUP BY ln.lgid""").fetchall()
    conn.close()
    members, ntot = {}, 0  # grpid -> {language name: (lgid, max reflex count)}
    for r in rows:
        nm = r["language"] or ""
        if not nm:
            continue
        d = members.setdefault(r["grpid"], {})
        cur = d.get(nm)
        if cur is None or r["n"] > cur[1]:
            d[nm] = (r["lgid"], r["n"])
    for d in members.values():
        ntot += len(d)

    def block(grpno, grp, plg, grpid, langs):
        # pre-escape scalars to Markup so the template (autoescape on) emits them verbatim
        return {
            "depth": (str(grpno).count(".") if grpno else 0) * TREE_INDENT_PX,
            "grpno": Markup(esc(grpno)) if grpno else "",
            "grp": Markup(esc(grp or "—")),
            "plg": Markup(esc(plg)) if plg else "",
            "grpid": grpid,
            "langs": [
                (Markup(esc(nm)), canon_lgid(lid))
                for nm, (lid, _) in sorted(langs.items(), key=lambda kv: sortkey(kv[0]))
            ],
        }

    blocks = [
        block(g["grpno"], g["grp"], g["plg"], g["grpid"], members.get(g["grpid"], {}))
        for g in sorted(allgroups, key=lambda g: natkey(g["grpno"]))
    ]
    # any attested language whose grpid isn't a known classification node (incl. NULL) stays reachable
    known = {g["grpid"] for g in allgroups}
    leftover = {}
    for gid, d in members.items():
        if gid not in known:
            leftover.update(d)
    if leftover:
        blocks.append(block(None, "Unclassified", "", None, leftover))
    return page("Languages", _LANGUAGES.render(ntot=f"{ntot:,}", blocks=blocks), nav="languages")


def sources_index():
    conn = con()
    rows = conn.execute(f"""SELECT sb.srcabbr AS srcabbr, sb.citation AS citation, sb.author AS author,
            sb.year AS year, sb.title AS title, sb.imprint AS imprint,
            count(DISTINCT CASE WHEN l.rn IS NOT NULL AND ln.language NOT LIKE '*%' AND ln.language!='' THEN ln.lgid END) AS nlang,
            count(CASE WHEN ln.language NOT LIKE '*%' AND ln.language!='' THEN l.rn END) AS nforms,
            count(CASE WHEN ln.language LIKE '*%' THEN l.rn END) AS nproto
        FROM srcbib sb
        LEFT JOIN languagenames ln ON ln.srcabbr=sb.srcabbr
        LEFT JOIN lexicon l ON l.lgid=ln.lgid AND {LEX_VISIBLE}
        WHERE coalesce(sb.srcabbr,'')!=''
        GROUP BY sb.srcabbr
        ORDER BY coalesce(nullif(sb.author,''),nullif(sb.citation,''),sb.srcabbr) COLLATE unaccent, sb.year""").fetchall()
    conn.close()

    def item(s):
        cit = Markup(esc(s["citation"] or s["srcabbr"]))
        ref = Markup(esc(source_reference(s)))
        parts = []
        if s["nforms"]:
            parts.append(f"{s['nforms']:,} {rfx_noun(s['nforms'])}")
        if s["nproto"]:  # previously published reconstruction records ('*…' lects)
            parts.append(f"{s['nproto']:,} reconstruction record" + ("" if s["nproto"] == 1 else "s"))
        if s["nlang"]:
            parts.append(f"{s['nlang']} language" + ("" if s["nlang"] == 1 else "s"))
        return {
            "srcabbr": Markup(esc(s["srcabbr"])),
            "cit": cit,
            "ref": ref,
            "show_ref": bool(ref) and ref != cit,  # data list hides ref when it just repeats the citation
            "au": Markup(esc(sortkey(s["author"] or s["citation"] or s["srcabbr"] or ""))),
            "nforms": s["nforms"],
            "cnt_txt": " · ".join(parts),
            "nlang": s["nlang"],
        }

    # a source counts as data-bearing when it holds ANY visible records — attested forms OR
    # previously published reconstructions (JRO-Tilung holds only the latter and was misfiled
    # as 'no attested forms held in STEDT')
    data = [item(s) for s in rows if s["nforms"] or s["nproto"]]
    refonly = [item(s) for s in rows if not (s["nforms"] or s["nproto"])]
    total_forms = sum(s["nforms"] for s in rows if s["nforms"])
    return page(
        "Sources",
        _SOURCES.render(ndata=f"{len(data):,}", total_forms=f"{total_forms:,}", data=data, refonly=refonly),
        nav="sources",
    )


def search_page(q=""):
    """Static results shell — reads ?q= and renders matches client-side via window.stedtSearch,
    federated across entity types (languages / reconstructions / attested forms), each with its
    true total count and windowed infinite-scroll, so results are never silently capped."""
    return page("Search", _SEARCH.render(), q)


_ORPHANS = None


def _orphan_aliases(conn):
    """{orphan filing key: nearest existing chapters ancestor}. An etymon can be filed under a
    key with no chapters row (one today: #5763 under 8.3.3.8.3, missing upstream too); the
    original still serves that key, so rather than letting the etymon vanish from the whole
    thesaurus, list it on the nearest real ancestor node (8.3.3.8 'Pride' — where its own
    breadcrumb already points). Loaded once per process."""
    global _ORPHANS
    if _ORPHANS is None:
        have = {r[0] for r in conn.execute("SELECT semkey FROM chapters WHERE coalesce(semkey,'')!=''")}
        out = {}
        for (k,) in conn.execute(f"SELECT DISTINCT {ECAT} FROM etyma e WHERE {ETY_LIVE}"):
            if not k or k in have:
                continue
            a = k
            while "." in a:
                a = a.rsplit(".", 1)[0]
                if a in have or ("." not in a and a + ".0" in have):
                    out[k] = a
                    break
        _ORPHANS = out
    return _ORPHANS


def _with_orphans(conn, node, keys):
    """The node's filing keys plus any orphan keys that alias to it."""
    return keys + [o for o, anc in _orphan_aliases(conn).items() if anc == node]


def thesaurus(semkey=None):
    conn = con()
    if semkey is None:
        nodes = conn.execute("SELECT semkey, chaptertitle FROM chapters WHERE coalesce(semkey,'')!=''").fetchall()
        SPECIAL = {"999", "950.1", "x.x"}
        scounts = reflex_semkey_counts()  # exact per-semkey reflex counts (proto-excluded)
        # chapters carrying prose notes get a marker (the original's browser has a notes column)
        nnotes = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT id, count(*) FROM notes WHERE spec='C' AND notetype!='I' "
                "AND xmlnote IS NOT NULL GROUP BY id"
            )
        }
        tree = []
        for n in nodes:
            sk = n["semkey"]
            if sk in SPECIAL:
                continue
            if sk.endswith(".0") and sk.count(".") == 1:
                disp, depth = sk.split(".")[0], 0
            else:
                disp, depth = sk, sk.count(".")
            # both counts are exact (this node only, NOT the subtree): an integer root N also
            # owns its N.0 overview key. Reconstructions and reflexes are mostly filed at leaves,
            # so upper nodes read small/zero - that's intended (each item counted once, at home).
            own_n = _with_orphans(conn, disp, [disp, disp + ".0"] if "." not in disp else [disp])
            ph = ",".join("?" * len(own_n))
            cnt = conn.execute(
                f"SELECT count(*) FROM etyma e WHERE {ETY_LIVE} AND {ECAT} IN ({ph})",
                own_n,
            ).fetchone()[0]
            lcnt = sum(scounts.get(k, 0) for k in own_n)
            nn = sum(nnotes.get(k, 0) for k in own_n)
            tree.append((disp, depth, n["chaptertitle"], cnt, lcnt, nn))
        tree.sort(key=lambda r: natkey(r[0]))
        conn.close()
        treeinfo = [
            {
                "pad": depth * TREE_INDENT_PX,
                "disp": disp,
                "disp_esc": Markup(esc(disp)),
                "cnt": cnt,
                "lcnt": lcnt,
                # depth-0 roots get a CLASS (not inline weight) so the sorted/flattened view
                # can neutralize it — a by-count ranking mixing bold roots with plain leaves
                # read as emphasis it didn't mean
                "ti": Markup(f'<span class="ti{" d0" if depth == 0 else ""}">{esc(title)}</span>'),
                "ct": Markup(
                    (f'<span class="nnote">{nn} note{"" if nn == 1 else "s"}</span>' if nn else "")
                    + (
                        f'<span class="ct" title="reconstructions / reflexes">{cnt:,} / {lcnt:,}</span>'
                        if (cnt or lcnt)
                        else ""
                    )
                ),
            }
            for disp, depth, title, cnt, lcnt, nn in tree
        ]
        return page("Thesaurus", _THESAURUS.render(root=True, tree=treeinfo), nav="thesaurus")

    # The integer node N and the chapter N.0 are the same category-overview node; treat
    # /thesaurus/N.0 as an alias of /thesaurus/N so it doesn't render an empty, self-referential page.
    if re.fullmatch(r"\d+\.0", semkey):
        semkey = semkey.split(".")[0]
    own = [semkey, semkey + ".0"] if "." not in semkey else [semkey]
    ownph = ",".join("?" * len(own))
    title = conn.execute("SELECT chaptertitle FROM chapters WHERE semkey=?", (semkey,)).fetchone()
    if not title and "." not in semkey:
        title = conn.execute("SELECT chaptertitle FROM chapters WHERE semkey=?", (semkey + ".0",)).fetchone()
    title = title[0] if title else semkey
    cnotes = conn.execute(
        f"""SELECT xmlnote FROM notes WHERE id IN ({ownph}) AND spec='C' AND notetype!='I'
                         AND xmlnote IS NOT NULL ORDER BY ord, noteid""",
        own,
    ).fetchall()
    crumb = breadcrumb(conn, semkey)
    depth = len(semkey.split("."))
    # Children at the next depth, minus the N.0 overview (it IS this integer node).
    kids = conn.execute(
        """SELECT semkey,chaptertitle FROM chapters
        WHERE semkey LIKE ? AND (length(semkey)-length(replace(semkey,'.','')))=?
          AND semkey NOT LIKE '%.0'
        """,
        (semkey + ".%", depth),
    ).fetchall()
    kids = sorted(kids, key=lambda r: natkey(r["semkey"]))
    scounts = reflex_semkey_counts()   # semkey -> attested-form count, the same source the index uses
    kidinfo = []
    for k in kids:
        sk = k["semkey"]
        kown = _with_orphans(conn, sk, [sk, sk + ".0"] if "." not in sk else [sk])  # node-only, like the index
        kph = ",".join("?" * len(kown))
        cnt = conn.execute(
            f"SELECT count(*) FROM etyma e WHERE {ETY_LIVE} AND {ECAT} IN ({kph})", kown
        ).fetchone()[0]
        lcnt = sum(scounts.get(x, 0) for x in kown)
        # reconstructions / reflexes, formatted exactly as the thesaurus index renders each node,
        # so a recon-less but attestation-rich child no longer reads as a dead "0 etyma"
        ct = (
            Markup(f'<span class="ct" title="reconstructions / reflexes">{cnt:,} / {lcnt:,}</span>')
            if (cnt or lcnt)
            else Markup("")
        )
        kidinfo.append(
            {"semkey": sk, "semkey_esc": Markup(esc(sk)), "title": Markup(esc(k["chaptertitle"])), "ct": ct}
        )
    own_e = _with_orphans(conn, semkey, own)  # etyma filing keys: this node + orphan keys aliased here
    direct = conn.execute(
        f"""SELECT e.tag, e.protoform, e.protogloss, e.sequence, g.plg AS plg, e.exemplary, e.public
        FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
        WHERE {ECAT} IN ({",".join("?" * len(own_e))})
          AND {ETY_LIVE}
        ORDER BY e.sequence, e.protogloss""",
        own_e,
    ).fetchall()

    def seq_disp(v):
        # the curated sequence, as the original's chapter table shows it: '1' for a main root,
        # '1.1'/'1.2' for its sub-roots (the decimal marks variants of the integer root)
        try:
            f = float(v)
        except (TypeError, ValueError):
            return ""
        if f <= 0:
            return ""
        return f"{f:g}"

    dinfo = []
    if direct:
        # SYNC(etymon-row) ↔ web/src/rows.js etymonRow — keep protoform/PLG/#tag/count/exemplary identical.
        dcounts = reflex_counts(conn, [e["tag"] for e in direct])
        dinfo = [
            {
                "tag": e["tag"],
                "href": etymon_href(e["tag"]),
                "pf": Markup(esc(alt(e["protoform"]))),
                "pg": Markup(esc(e["protogloss"])),
                "tagn": Markup(
                    # leading curated-sequence label: the decimal marks sub-roots of the integer
                    # root (1 / 1.1 / 1.2 …) — the order the list is already sorted by
                    (f'<span class="seqn">{seq_disp(e["sequence"])}</span> · ' if seq_disp(e["sequence"]) else "")
                    + f'{esc(e["plg"])} #{e["tag"]}{rcount_txt(dcounts.get(e["tag"], 0))}'
                    + (' · <span class="exm">exemplary</span>' if (e["exemplary"] or "") == "x" else "")
                    + ("" if e["public"] else ' · <span class="prov">provisional</span>')
                ),
            }
            for e in direct
        ]
    # Attested forms (reflexes) filed directly under this meaning - a separate, gloss-level axis from
    # the etyma above. Loaded lazily on expand (reuses the search WASM DB); the count is static.
    nforms = sum(scounts.get(k, 0) for k in own)   # scounts computed above (kids loop)
    attest = None
    if nforms:
        attest = {"keys_json": Markup(esc(json.dumps(own, separators=(",", ":")))), "nforms": f"{nforms:,}"}
    conn.close()
    return page(
        "Thesaurus" + f": {semkey}",
        _THESAURUS.render(
            root=False,
            crumb=Markup(crumb),
            title=Markup(esc(title)),
            # drop notes that render to no text (3 chapters carry an empty '<par></par>'
            # graphical note whose image never shipped) — else an empty grey box renders
            cnotes=[
                Markup(h)
                for h in (render_note(r["xmlnote"]) for r in cnotes)
                if re.sub(r"<[^>]+>", "", h).strip()
            ],
            kids=kidinfo,
            direct=dinfo,
            ndirect=f"{len(direct):,}",
            attest=attest,
        ),
        nav="thesaurus",
    )
