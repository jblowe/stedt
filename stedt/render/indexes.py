"""Index/browse pages: home, about, reconstructions, languages, sources, search, thesaurus."""

import re
import json

from markupsafe import Markup

from .config import CITE_BASE, PREVIEW, TREE_INDENT_PX
from .db import con, reflex_semkey_counts
from .text import esc, alt, natkey, rcount_txt
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


def about():
    conn = con()
    one = lambda sql: conn.execute(sql).fetchone()[0]
    ety = one("SELECT count(*) FROM etyma e WHERE coalesce(upper(e.status),'')!='DELETE'")
    rfx = one("SELECT count(*) FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid WHERE ln.language NOT LIKE '*%'")
    # a "language" is a lect = (name, subgroup), matching the Languages index header + canonicalization
    lgs = one("""SELECT count(*) FROM (SELECT 1 FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid
        WHERE ln.language!=\'\' AND ln.language NOT LIKE \'*%\' GROUP BY ln.language, ln.grpid)""")
    src = one("""SELECT count(*) FROM srcbib sb WHERE EXISTS(
        SELECT 1 FROM languagenames ln JOIN lexicon l ON l.lgid=ln.lgid WHERE ln.srcabbr=sb.srcabbr)""")
    conn.close()
    body = _ABOUT.render(ety=f"{ety:,}", rfx=f"{rfx:,}", lgs=f"{lgs:,}", src=f"{src:,}", cite_base=CITE_BASE)
    return page("About", body, nav="about")


def reconstructions():
    # The whole list (~4k etyma) is shipped once as compact JSON and rendered
    # client-side in windows of CHUNK rows, with an instant in-page filter. This
    # keeps the initial DOM small (~200 nodes vs ~31k) on slow devices while the
    # gloss-ordered full set stays a single, filterable, statically-hosted page.
    conn = con()
    OK = "coalesce(upper(e.status),'')!='DELETE'"
    rows = conn.execute(f"""SELECT e.tag, e.protoform, e.protogloss, g.plg AS plg
        FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
        WHERE {OK} ORDER BY e.protogloss, e.tag""").fetchall()
    counts = reflex_counts(conn)
    conn.close()
    total = len(rows)
    data = [
        # ship the RAW protoform; the client's etymonRow applies altstar() (same as search), so the
        # reconstructions index and search render an etymon identically.
        [r["tag"], r["protoform"] or "", r["protogloss"] or "", r["plg"] or "", counts.get(r["tag"], 0)]
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
    rows = conn.execute("""SELECT ln.grpid AS grpid, ln.language AS language, ln.lgid AS lgid, count(*) AS n
        FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid
        WHERE ln.language NOT LIKE '*%'
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
                for nm, (lid, _) in sorted(langs.items(), key=lambda kv: kv[0].lower())
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
    rows = conn.execute("""SELECT sb.srcabbr AS srcabbr, sb.citation AS citation, sb.author AS author,
            sb.year AS year, sb.title AS title, sb.imprint AS imprint,
            count(DISTINCT CASE WHEN l.rn IS NOT NULL AND ln.language NOT LIKE '*%' AND ln.language!='' THEN ln.lgid END) AS nlang,
            count(CASE WHEN ln.language NOT LIKE '*%' AND ln.language!='' THEN l.rn END) AS nforms
        FROM srcbib sb
        LEFT JOIN languagenames ln ON ln.srcabbr=sb.srcabbr
        LEFT JOIN lexicon l ON l.lgid=ln.lgid
        WHERE coalesce(sb.srcabbr,'')!=''
        GROUP BY sb.srcabbr
        ORDER BY lower(coalesce(nullif(sb.author,''),nullif(sb.citation,''),sb.srcabbr)), sb.year""").fetchall()
    conn.close()

    def item(s):
        cit = Markup(esc(s["citation"] or s["srcabbr"]))
        ref = Markup(esc(source_reference(s)))
        return {
            "srcabbr": Markup(esc(s["srcabbr"])),
            "cit": cit,
            "ref": ref,
            "show_ref": bool(ref) and ref != cit,  # data list hides ref when it just repeats the citation
            "au": Markup(esc((s["author"] or s["citation"] or s["srcabbr"] or "").lower())),
            "nforms": s["nforms"],
            "nforms_fmt": f"{s['nforms']:,}",
            "nlang": s["nlang"],
        }

    data = [item(s) for s in rows if s["nforms"]]
    refonly = [item(s) for s in rows if not s["nforms"]]
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


# Legacy files an etymon under its (more specific) `chapter`; `semkey` is only a fallback for
# the lone live etymon whose chapter doesn't resolve. Used for thesaurus placement + counts.
ECAT = "coalesce(nullif(e.chapter,''),e.semkey)"


def thesaurus(semkey=None):
    conn = con()
    if semkey is None:
        nodes = conn.execute("SELECT semkey, chaptertitle FROM chapters WHERE coalesce(semkey,'')!=''").fetchall()
        SPECIAL = {"999", "950.1", "x.x"}
        scounts = reflex_semkey_counts()  # exact per-semkey reflex counts (proto-excluded)
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
            own_n = [disp, disp + ".0"] if "." not in disp else [disp]
            ph = ",".join("?" * len(own_n))
            cnt = conn.execute(
                f"SELECT count(*) FROM etyma e WHERE coalesce(upper(e.status),'')!='DELETE' " f"AND {ECAT} IN ({ph})",
                own_n,
            ).fetchone()[0]
            lcnt = sum(scounts.get(k, 0) for k in own_n)
            tree.append((disp, depth, n["chaptertitle"], cnt, lcnt))
        tree.sort(key=lambda r: natkey(r[0]))
        conn.close()
        treeinfo = [
            {
                "pad": depth * TREE_INDENT_PX,
                "disp": disp,
                "disp_esc": Markup(esc(disp)),
                "ti": Markup(
                    f'<span class="ti" style="font-weight:600">{esc(title)}</span>'
                    if depth == 0
                    else f'<span class="ti">{esc(title)}</span>'
                ),
                "ct": Markup(
                    f'<span class="ct" title="reconstructions / reflexes">{cnt:,} / {lcnt:,}</span>'
                    if (cnt or lcnt)
                    else ""
                ),
            }
            for disp, depth, title, cnt, lcnt in tree
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
        kown = [sk, sk + ".0"] if "." not in sk else [sk]  # node-only, matching the index (not subtree)
        kph = ",".join("?" * len(kown))
        cnt = conn.execute(
            f"SELECT count(*) FROM etyma e WHERE coalesce(upper(e.status),'')!='DELETE' " f"AND {ECAT} IN ({kph})", kown
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
    direct = conn.execute(
        f"""SELECT e.tag, e.protoform, e.protogloss, g.plg AS plg
        FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
        WHERE {ECAT} IN ({ownph})
          AND coalesce(upper(e.status),'')!='DELETE'
        ORDER BY e.sequence, e.protogloss""",
        own,
    ).fetchall()
    dinfo = []
    if direct:
        dcounts = reflex_counts(conn, [e["tag"] for e in direct])
        dinfo = [
            {
                "tag": e["tag"],
                "href": etymon_href(e["tag"]),
                "pf": Markup(esc(alt(e["protoform"]))),
                "pg": Markup(esc(e["protogloss"])),
                "tagn": Markup(f'{esc(e["plg"])} #{e["tag"]}{rcount_txt(dcounts.get(e["tag"], 0))}'),
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
            cnotes=[Markup(render_note(r["xmlnote"])) for r in cnotes],
            kids=kidinfo,
            direct=dinfo,
            ndirect=f"{len(direct):,}",
            attest=attest,
        ),
        nav="thesaurus",
    )
