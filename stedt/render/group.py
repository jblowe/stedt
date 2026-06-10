"""Language-group page: lineage, subgroups, member lects, and the group's reconstructions."""

from markupsafe import Markup

from .config import PLG_FULL, TREE_INDENT_PX
from .db import ETY_LIVE, LEX_VISIBLE, con
from .text import esc, alt, natkey, iso_link, plural, rcount_txt, rfx_noun, sortkey
from .rows import lgab_span
from .shell import page, group_lineage, reflex_counts, canonical_languages
from .shell import etymon_href, source_href
from .templating import env

_GROUP = env.get_template("group.html")


def group(grpid):
    conn = con()
    g = conn.execute("SELECT * FROM languagegroups WHERE grpid=?", (grpid,)).fetchone()
    if not g:
        conn.close()
        return page("Not found", "<p>No such group.</p>")
    grpno = g["grpno"]
    lin = group_lineage(conn, grpno)
    # Children are the descendants whose NEAREST EXISTING ancestor is this node — not "exactly one
    # dot deeper": the Stammbaum skips levels (Sinitic is '9', its children are 9.0.1/9.0.2/9.0.3
    # with no '9.0' row), the same prefix-walk group_lineage() does upward.
    if grpno is not None:
        desc = conn.execute(
            "SELECT grpid, grpno, grp, plg FROM languagegroups WHERE grpno LIKE ? ORDER BY grpno",
            (str(grpno) + ".%",),
        ).fetchall()
        have = {d["grpno"] for d in desc} | {str(grpno)}

        def _nearest(no):
            parts = str(no).split(".")
            for k in range(len(parts) - 1, 0, -1):
                p = ".".join(parts[:k])
                if p in have:
                    return p
            return None

        children = [d for d in desc if _nearest(d["grpno"]) == str(grpno)]
    else:
        children = []
    childinfo = []
    for ch in children:
        # count canonical member lects (distinct non-proto name == one lect within a grpid),
        # not raw language×source rows, so the tally matches the subgroup's own page header;
        # a node holding only reconstruction sets (groups 1/2) is labeled by those instead of
        # reading '0 languages'
        nl, nproto = conn.execute(
            f"""SELECT count(DISTINCT CASE WHEN ln.language NOT LIKE '*%' THEN ln.language END),
                      count(DISTINCT CASE WHEN ln.language LIKE '*%' THEN ln.language END)
            FROM languagenames ln
            JOIN lexicon l ON l.lgid=ln.lgid
            WHERE ln.grpid=? AND {LEX_VISIBLE}""",
            (ch["grpid"],),
        ).fetchone()
        # a branch node whose lects all live in deeper subgroups (e.g. Tibeto-Kanauri, Sal) has no
        # direct members — count its subtree by grpno prefix so the row doesn't read '0 languages'
        nsub = 0
        if not nl and not nproto and ch["grpno"]:
            nsub = conn.execute(
                f"""SELECT count(DISTINCT ln.language) FROM languagenames ln
                JOIN languagegroups g ON g.grpid=ln.grpid
                JOIN lexicon l ON l.lgid=ln.lgid
                WHERE (g.grpno=? OR g.grpno LIKE ?) AND ln.language NOT LIKE '*%' AND {LEX_VISIBLE}""",
                (ch["grpno"], str(ch["grpno"]) + ".%"),
            ).fetchone()[0]
        childinfo.append((ch, nl, nproto, nsub))
    # member lects directly attested at this node: collapse the per-source lgids of one lect onto its
    # canonical page (summing forms, merging sources), and drop proto-forms — they are this group's own
    # reconstruction (the plg + Reconstructions section), not member languages.
    langrows = conn.execute(
        f"""SELECT ln.lgid AS lgid, ln.language AS language, ln.lgabbr AS lgabbr,
            ln.silcode AS silcode, ln.srcabbr AS srcabbr, sb.citation AS citation, count(l.rn) AS n
        FROM languagenames ln LEFT JOIN srcbib sb ON sb.srcabbr=ln.srcabbr
        JOIN lexicon l ON l.lgid=ln.lgid
        WHERE ln.grpid=? AND ln.language NOT LIKE '*%' AND {LEX_VISIBLE}
        GROUP BY ln.lgid HAVING n>0""",
        (grpid,),
    ).fetchall()
    # previously published reconstruction sets filed at this node ('*Tibeto-Burman' per source…):
    # the original lists them as group members; their /language pages exist but were reachable
    # from nowhere. Same per-source collapse as the member lects, own section below.
    protorows = conn.execute(
        f"""SELECT ln.lgid AS lgid, ln.language AS language, ln.lgabbr AS lgabbr,
            ln.silcode AS silcode, ln.srcabbr AS srcabbr, sb.citation AS citation, count(l.rn) AS n
        FROM languagenames ln LEFT JOIN srcbib sb ON sb.srcabbr=ln.srcabbr
        JOIN lexicon l ON l.lgid=ln.lgid
        WHERE ln.grpid=? AND ln.language LIKE '*%' AND {LEX_VISIBLE}
        GROUP BY ln.lgid HAVING n>0""",
        (grpid,),
    ).fetchall()
    canon_of = canonical_languages()[0]

    def collapse(rows_in):
        lects = {}
        for r in rows_in:
            cid = canon_of.get(r["lgid"], r["lgid"])
            d = lects.get(cid)
            if d is None:
                d = lects[cid] = {
                    "lgid": cid,
                    "language": r["language"],
                    "lgabbr": r["lgabbr"],
                    "silcode": r["silcode"],
                    "n": 0,
                    "srcs": {},
                }
            d["n"] += r["n"]
            if not d["silcode"] and r["silcode"]:
                d["silcode"] = r["silcode"]
            if r["srcabbr"]:
                d["srcs"].setdefault(r["srcabbr"], r["citation"])
        return sorted(lects.values(), key=lambda d: sortkey(d["language"]))

    langs = collapse(langrows)
    protos = collapse(protorows)
    recons = conn.execute(
        f"""SELECT e.tag AS tag, e.protoform AS protoform, e.protogloss AS protogloss, e.exemplary AS exemplary,
            e.public AS public
        FROM etyma e WHERE e.grpid=? AND {ETY_LIVE}
        ORDER BY e.sequence, e.protogloss""",
        (grpid,),
    ).fetchall()
    rcounts = reflex_counts(conn, [r["tag"] for r in recons])
    # the complete genetic tree, so every group page offers one-click cross-branch navigation
    alltree = conn.execute(
        "SELECT grpid, grpno, grp FROM languagegroups WHERE grpid IS NOT NULL AND grpno IS NOT NULL"
    ).fetchall()
    conn.close()

    plg = g["plg"] or ""
    head = (f'<span class="grpno">{esc(grpno)}</span>' if grpno else "") + esc(g["grp"] or "—")
    # show the full proto-language name (abbr in the tooltip), matching the etymon page's PLG link —
    # so clicking "Proto-Lolo-Burmese" there no longer lands on a header reading only "(PLB)".
    plg_html = f' <span class="plg2" title="{esc(plg)}">({esc(PLG_FULL.get(plg, plg))})</span>' if plg else ""
    # ancestors only — the current group is the h1 below, never its own crumb (sitewide rule)
    crumb_links = ['<a href="/languages">Languages</a>'] + [
        f'<a href="/group/{gg["grpid"]}">{(esc(gg["grpno"]) + " ") if gg["grpno"] else ""}{esc(gg["grp"])}</a>'
        for gg in lin[:-1]
    ]
    meta = []
    if langs:
        meta.append(Markup(f"<span><b>{len(langs)}</b> {plural(len(langs), 'language')}</span>"))
    if recons:
        meta.append(Markup(f"<span><b>{len(recons):,}</b> reconstructions</span>"))

    def treeitem(t):
        d = str(t["grpno"]).count(".")
        lab = f'<span class="grpno">{esc(t["grpno"])}</span>{esc(t["grp"] or "")}'
        inner = (
            f'<span class="here">{lab}</span>' if t["grpid"] == grpid else f'<a href="/group/{t["grpid"]}">{lab}</a>'
        )
        return {"pad": d * TREE_INDENT_PX, "inner": Markup(inner)}

    tree = [treeitem(t) for t in sorted(alltree, key=lambda t: natkey(t["grpno"]))]

    def subinfo(ch, nl, nproto, nsub):
        code = f'<span class="grpno">{esc(ch["grpno"])}</span>' if ch["grpno"] else ""
        lab = code + esc(ch["grp"]) + (f' <span class="plg2">({esc(ch["plg"])})</span>' if ch["plg"] else "")
        if nl:
            ct = f"{nl} language" + ("" if nl == 1 else "s")
        elif nproto:
            ct = f"{nproto} reconstruction set" + ("" if nproto == 1 else "s")
        elif nsub:
            # branch node: members live in deeper subgroups, say so instead of '0 languages'
            ct = f"{nsub} language" + ("" if nsub == 1 else "s") + " in subgroups"
        else:
            ct = ""  # truly empty node — show nothing, like the thesaurus index at 0
        return {"grpid": ch["grpid"], "lab": Markup(lab), "ct": ct}

    subs = [subinfo(ch, nl, nproto, nsub) for ch, nl, nproto, nsub in childinfo]

    def langinfo(l, noun=None):
        ab = lgab_span(l["lgabbr"])
        mid = []
        srcs = list(l["srcs"].items())
        if len(srcs) == 1:
            sab, cit = srcs[0]
            mid.append(f'<a href="{source_href(sab)}">{esc(cit or sab)}</a>')
        elif len(srcs) > 1:
            mid.append(f"{len(srcs)} sources")
        if l["silcode"]:
            mid.append("ISO " + iso_link(l["silcode"]))
        # shares the .ety-hit visual shell with the Reconstructions list below + the search rows, but
        # populates the columns for THIS context: the member row carries subgroup/source/ISO in the
        # middle and the reflex count on the right, where a search language suggestion puts the count
        # in the middle and an entity-type label on the right.
        return {
            "lgid": l["lgid"],
            "language": Markup(esc(l["language"])),
            "ab": Markup(ab),
            "mid": Markup(" · ".join(mid)),
            "n_txt": f"{l['n']:,} {noun(l['n']) if noun else rfx_noun(l['n'])}",
        }

    langinfos = [langinfo(l) for l in langs]
    protoinfos = [langinfo(l, noun=lambda n: "record" if n == 1 else "records") for l in protos]

    def reconinfo(r):
        # SYNC(etymon-row) ↔ web/src/rows.js etymonRow — keep protoform/PLG/#tag/count/exemplary identical.
        return {
            "tag": r["tag"],
            "href": etymon_href(r["tag"]),
            "protoform": Markup(esc(alt(r["protoform"]))),
            "protogloss": Markup(esc(r["protogloss"])),
            "tagn": Markup(
                f'{esc(plg)} #{r["tag"]}{rcount_txt(rcounts.get(r["tag"], 0))}'
                + (' · <span class="exm">exemplary</span>' if (r["exemplary"] or "") == "x" else "")
                + ("" if r["public"] else ' · <span class="prov">provisional</span>')
            ),
        }

    reconinfos = [reconinfo(r) for r in recons]

    return page(
        g["grp"] or "Group",
        _GROUP.render(
            pagetitle=Markup(head + plg_html),
            crumbs=Markup(" &nbsp;›&nbsp; ".join(crumb_links)),
            meta=meta,
            tree=tree,
            ntree=len(alltree),
            subs=subs,
            langs=langinfos,
            nlangs=len(langs),
            protos=protoinfos,
            nprotos=len(protos),
            recons=reconinfos,
            nrecons=len(recons),
        ),
        nav="languages",
    )
