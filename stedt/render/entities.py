"""Entity pages: etymon, language, source, language-group."""

import re
import urllib.parse

from markupsafe import Markup

from .config import CITE_BASE, PLG_FULL, TREE_INDENT_PX
from .db import con
from .text import esc, alt, natkey, iso_link, rcount_txt
from .notes import render_note
from .syllabify import syllabify
from .shell import page, breadcrumb, group_lineage, reflex_counts, proto_labels, canonical_languages, canon_lgid
from .shell import etymon_href, source_href, language_href, reflex_href, source_reference
from .templating import env

_SOURCE = env.get_template("source.html")
_GROUP = env.get_template("group.html")
_LANGUAGE = env.get_template("language.html")
_ETYMON = env.get_template("etymon.html")


def etymon(tag):
    conn = con()
    e = conn.execute(
        """SELECT e.*, g.plg AS plg FROM etyma e
        LEFT JOIN languagegroups g ON g.grpid=e.grpid WHERE e.tag=?""",
        (tag,),
    ).fetchone()
    if not e:
        conn.close()
        return page("Not found", "<p>No such etymon.</p>")
    notes = conn.execute(
        """SELECT xmlnote FROM notes WHERE tag=? AND spec='E' AND notetype NOT IN ('F','I')
                         AND xmlnote IS NOT NULL ORDER BY ord, noteid""",
        (tag,),
    ).fetchall()
    # Chinese comparanda (notetype='F') are a distinct class — legacy gave them their own block
    # rather than burying them in the general Notes; keep that separation.
    compar = conn.execute(
        """SELECT xmlnote FROM notes WHERE tag=? AND spec='E' AND notetype='F'
                         AND xmlnote IS NOT NULL ORDER BY ord, noteid""",
        (tag,),
    ).fetchall()
    rows = conn.execute(
        """SELECT l.rn AS rn, ln.language AS language, l.lgid AS lgid, l.reflex AS form, l.gloss, l.gfn AS gfn,
            l.srcid AS srcid, g.grp AS subgroup, g.grpno AS groupnode, g.plg AS grpplg, g.grpid AS grpid,
            sb.citation AS citation, ln.srcabbr AS srcabbr
        FROM lx_et_hash h JOIN lexicon l ON l.rn=h.rn
        JOIN languagenames ln ON ln.lgid=l.lgid
        LEFT JOIN languagegroups g ON g.grpid=ln.grpid
        LEFT JOIN srcbib sb ON sb.srcabbr=ln.srcabbr
        WHERE h.tag=? GROUP BY l.rn""",
        (tag,),
    ).fetchall()
    hptb = conn.execute(
        """SELECT h.plg, h.protoform, h.protogloss, h.pages
        FROM et_hptb_hash x JOIN hptb h ON h.hptbid=x.hptbid WHERE x.tag=? ORDER BY x.ord""",
        (tag,),
    ).fetchall()
    meso = conn.execute(
        """SELECT g.grp AS subgroup, g.grpno AS groupnode, g.grpid AS grpid, m.form, m.gloss, m.variant, m.old_note
        FROM mesoroots m LEFT JOIN languagegroups g ON g.grpid=m.grpid
        WHERE m.tag=? ORDER BY g.grpno, m.id""",
        (tag,),
    ).fetchall()
    # cross-reference labels: collect every tag mentioned in a pure tag-list field
    digit_tokens = set()
    for fld in (e["allofams"], e["xrefs"], e["possallo"]):
        if not fld:
            continue
        fs = fld.strip()
        if re.fullmatch(r"[\d,\s]+", fs):
            digit_tokens.update(int(t) for t in re.split(r"[,\s]+", fs) if t)
        else:  # also a single tag behind a relate-symbol: "↭ 686", "=1318"
            m = re.fullmatch(r"[↭=\s]*(\d+)\s*(?:\([^)]*\))?", fs)
            if m:
                digit_tokens.add(int(m.group(1)))
    labels = {}
    if digit_tokens:
        toks = list(digit_tokens)
        qm = ",".join("?" * len(toks))
        for r in conn.execute(
            f"SELECT tag,protoform,protogloss FROM etyma WHERE tag IN ({qm}) "
            f"AND coalesce(upper(status),'')!='DELETE'",
            toks,
        ):
            labels[r["tag"]] = (r["protoform"], r["protogloss"])
    # per-reflex morpheme analysis: a reflex (rn) is segmented into morphemes in lx_et_hash,
    # each tied to an etymon tag (0 = a non-etymon affix). Surface the *other* etyma a reflex
    # also belongs to (i.e. it's a compound) as links.
    rns = [r["rn"] for r in rows]
    analysis = {}
    rn_syn, rn_syn_bad = {}, set()
    for i in range(0, len(rns), 900):
        chunk = rns[i : i + 900]
        qm = ",".join("?" * len(chunk))
        for r in conn.execute(f"SELECT rn, tag, ind FROM lx_et_hash WHERE rn IN ({qm}) ORDER BY rn, ind", chunk):
            analysis.setdefault(r["rn"], []).append(r["tag"])
            if r["tag"] and r["tag"] > 0:           # syllable position -> etymon, for per-syllable links
                byind = rn_syn.setdefault(r["rn"], {})
                if r["ind"] in byind and byind[r["ind"]] != r["tag"]:
                    rn_syn_bad.add(r["rn"])
                else:
                    byind[r["ind"]] = r["tag"]
    # protoform + gloss for every etymon tagged on these reflexes (incl. this one), gated to non-DELETE
    # pages: powers the per-syllable popovers (syl_form) and the "also contains" sibling links.
    proto = proto_labels(conn, {t for ts in analysis.values() for t in ts if t and t > 0})
    # per-reflex (L) notes — the largest note class; legacy shows these as reflex footnotes.
    lnotes = {}
    for i in range(0, len(rns), 900):
        chunk = rns[i : i + 900]
        qm = ",".join("?" * len(chunk))
        for r in conn.execute(
            f"SELECT rn, xmlnote FROM notes WHERE spec='L' AND notetype!='I' "
            f"AND xmlnote IS NOT NULL AND rn IN ({qm}) ORDER BY ord, noteid",
            chunk,
        ):
            lnotes.setdefault(r["rn"], []).append(r["xmlnote"])
    ecat = e["chapter"] or e["semkey"]  # legacy files an etymon by its (more specific) chapter, not semkey
    crumb = breadcrumb(conn, ecat)
    conn.close()

    # separate attested reflexes from previously-published reconstructions (language is a *proto-form node)
    recon_rows = [r for r in rows if (r["language"] or "").startswith("*")]
    reflex_rows = [r for r in rows if not (r["language"] or "").startswith("*")]

    # group attested reflexes by subgroup, order by stammbaum (groupnode)
    groups = {}
    for r in reflex_rows:
        key = (r["groupnode"] or "zz", r["subgroup"] or "—")
        groups.setdefault(key, []).append(r)
    gkeys = sorted(groups, key=lambda k: (natkey(k[0]), k[1]))
    nsub = len(gkeys)

    jump = ""
    if nsub > 3:
        jump = (
            '<div class="jump">Jump to subgroup: '
            + " · ".join(f'<a href="#sg{i}">{esc(k[1])} ({len(groups[k])})</a>' for i, k in enumerate(gkeys))
            + "</div>"
        )

    sgs = []
    for i, k in enumerate(gkeys):
        items = sorted(groups[k], key=lambda r: ((r["language"] or ""), (r["form"] or "")))
        rfx = []
        # SYNC(reflex-row) ↔ web/src/rows.js reflexRow — keep this server-rendered reflex row's
        # fields/order/classes/links identical to the client one.
        for r in items:
            if lnotes.get(r["rn"]):
                # a lexical note rides on the gloss behind a circled-i (like the language/search/thesaurus
                # views); show the gloss even when it matches the protogloss so the icon has its anchor
                pop = "".join('<span class="np">' + render_note(x).replace('<p class="np">', "").replace("</p>", "")
                              + "</span>" for x in lnotes[r["rn"]])
                g = (f'<span class="g noted" tabindex="0">{esc(r["gloss"] or e["protogloss"])}'
                     f'<span class="notepop" role="note">{pop}</span></span>')
            elif r["gloss"] and r["gloss"] != e["protogloss"]:
                g = f'<span class="g">{esc(r["gloss"])}</span>'
            else:
                # deliberately suppress a reflex gloss identical to the etymon's protogloss (this is an
                # etymon page — repeating it on every row is noise); search/language pages always show it.
                g = ""
            pos = f'<span class="pos">{esc(r["gfn"])}</span>' if r["gfn"] else ""
            lang = f'<a class="lang" href="{language_href(r["lgid"])}">{esc(r["language"])}</a>'
            loc = f': {esc(r["srcid"])}' if r["srcid"] else ""  # per-reflex source locus (page/entry/note)
            if r["srcabbr"]:
                src = f'<a class="src" href="{source_href(r["srcabbr"])}">{esc(r["citation"] or r["srcabbr"])}{loc}</a>'
            else:
                src = f'<span class="src">{esc(r["citation"] or "")}{loc}</span>'
            # for a polymorphemic reflex (this etymon + at least one sibling), link each tagged syllable
            # to its etymon (popover preview) and mark the syllable that IS this etymon; otherwise leave
            # the form plain (marking a monomorphemic reflex's whole form would just be noise). Falls
            # back to the plain form + an "also contains" list of siblings when syllabification doesn't fit.
            syn = None if r["rn"] in rn_syn_bad else rn_syn.get(r["rn"])
            has_sibling = bool(syn) and any(t != tag for t in syn.values())
            linked = syl_form(r["form"], syn, proto, self_tag=tag) if has_sibling else None
            if linked is not None:
                form, anl = linked, ""
            else:
                form = esc(r["form"]).replace("◦", '<span class="br">◦</span>')
                seen, links = set(), []
                for mt in analysis.get(r["rn"], []):
                    if mt and mt > 0 and mt != tag and mt not in seen and mt in proto:
                        seen.add(mt)
                        links.append(f'<a href="{etymon_href(mt)}">*{esc(alt(proto[mt][0]))}</a>')
                anl = f'<span class="anl">also contains {", ".join(links)}</span>' if links else ""
            # whole row → this form's attestation (#rn on its language page), like the search/thesaurus
            # rows; the language name / "also contains" / source / note-popover sit above the overlay
            go = f'<a class="rx-go" href="{reflex_href(r["lgid"], r["rn"])}" aria-label="{esc(r["language"])}: go to this entry"></a>'
            rfx.append(
                f'<div class="rfx" id="r{r["rn"]}">{go}<a class="rnlink" href="#r{r["rn"]}" aria-label="Permalink to this entry"></a>{lang}'
                f'<span class="form">{form} {pos}{g}{anl}</span>{src}</div>'
            )
        code = "" if k[0] in (None, "zz") else f'<span class="grpno">{esc(k[0])}</span>'
        sgs.append(
            f'<div class="sg" id="sg{i}"><h4>{code}{esc(k[1])}<span class="c">{len(items)}</span></h4>'
            + "".join(rfx)
            + "</div>"
        )

    noteshtml = ""
    if notes:
        noteshtml = (
            '<section class="notes"><h3>Notes</h3>'
            + "".join(f'<div class="note-block">{render_note(r["xmlnote"])}</div>' for r in notes)
            + "</section>"
        )
    if compar:
        label = "Chinese comparand" + ("um" if len(compar) == 1 else "a")
        noteshtml += (
            f'<section class="notes"><h3>{label}</h3>'
            + "".join(f'<div class="note-block">{render_note(r["xmlnote"])}</div>' for r in compar)
            + "</section>"
        )

    nr = len(reflex_rows)
    cnt = (
        f'<span class="cnt">{nr:,} reflex{"" if nr == 1 else "es"} · '
        f'{nsub} subgroup{"" if nsub == 1 else "s"}</span>'
    )
    reflexeshtml = (
        f'<section class="reflexes etymon-rfx"><h3>Reflexes &amp; cognates{cnt}</h3>{jump}{"".join(sgs)}</section>'
        if sgs
        else ""
    )

    mesohtml = ""
    if meso:
        mr = ""
        for m in meso:
            sm = f'<span class="src">{esc(m["old_note"])}</span>' if m["old_note"] else '<span class="src"></span>'
            lab = esc(m["subgroup"] or "")
            langcell = (
                f'<a class="lang" href="/group/{m["grpid"]}">{lab}</a>'
                if m["grpid"] is not None
                else f'<span class="lang">{lab}</span>'
            )
            mr += (
                f'<div class="rfx">{langcell}'
                f'<span class="form"><span class="recon">{esc(alt(m["form"]))}</span> '
                f'<span class="g">{esc(m["gloss"])}</span></span>{sm}</div>'
            )
        mesohtml = f'<section class="meso"><h3>Intermediate reconstructions</h3>{mr}</section>'

    # previously published reconstructions (reflex rows whose "language" is a proto-form node)
    reconhtml = ""
    if recon_rows:
        rr = ""
        for r in recon_rows:
            lab = r["grpplg"] or r["subgroup"] or (r["language"] or "").lstrip("*")
            # the label is a proto-language group (e.g. PTani) — link it to its group page
            rl = (
                f'<a class="rl" href="/group/{r["grpid"]}">{esc(lab)}</a>'
                if r["grpid"] is not None
                else f'<span class="rl">{esc(lab)}</span>'
            )
            loc = f': {esc(r["srcid"])}' if r["srcid"] else ""
            if r["srcabbr"]:
                cit = f'<a class="src" href="{source_href(r["srcabbr"])}">{esc(r["citation"] or r["srcabbr"])}{loc}</a>'
            else:
                cit = f'<span class="src">{esc(r["citation"] or "")}{loc}</span>'
            gl = f' ‘{esc(r["gloss"])}’' if r["gloss"] else ""
            rr += (
                f'<div class="conn-row">{rl}'
                f'<span class="reltgt"><span class="recon">{esc(alt(r["form"]))}</span>{gl}</span>{cit}</div>'
            )
        reconhtml = f'<section class="conn"><h3>Previously reconstructed as</h3>{rr}</section>'

    # connections: HPTB reconstruction(s) + allofam / xref / possible allofam
    def rel_render(v):
        v = (v or "").strip()
        if not v:
            return ""
        if re.fullmatch(r"[\d,\s]+", v):  # tag list -> etymon links
            parts = []
            for t in re.split(r"[,\s]+", v):
                if not t:
                    continue
                lab = labels.get(int(t))
                if lab:  # only link to a built (non-DELETE) etymon, else show the bare ref
                    parts.append(f'<a class="xref" href="{etymon_href(t)}">*{esc(alt(lab[0]))} ‘{esc(lab[1])}’</a>')
                else:
                    parts.append(f'<span class="xref">#{esc(t)}</span>')
            return ", ".join(parts)
        # a field embedding a single etymon tag with a relate-symbol/parenthetical (e.g. "↭ 686",
        # "=1318", "2349 (PLB)") — link it to that etymon, not a (dead) gloss search. Keep it tight
        # (anchored ↭/= prefix + bare integer) so section refs like "3.4.5" / "8.8" don't match.
        m = re.fullmatch(r"[↭=\s]*(\d+)\s*(?:\([^)]*\))?", v)
        if m:
            t = m.group(1)
            lab = labels.get(int(t))
            if lab:
                return f'<a class="xref" href="{etymon_href(t)}">*{esc(alt(lab[0]))} ‘{esc(lab[1])}’</a>'
            return f'<span class="xref">#{esc(t)}</span>'  # DELETE/missing target: bare ref, not a dead search
        g = v.lstrip("↭").strip()  # gloss-based cross-reference
        return f'<a class="xref" href="/search?q={urllib.parse.quote(g)}">{esc(g)}</a>'

    rels = []
    for h in hptb:
        rels.append(
            f'<div class="conn-row"><span class="rl">HPTB</span>'
            f'<span class="reltgt"><span class="recon">{esc(alt(h["protoform"]))}</span> ‘{esc(h["protogloss"])}’</span>'
            f'<span class="src">pp. {esc(h["pages"])}</span></div>'
        )
    for label, fld in (("Allofam", e["allofams"]), ("See also", e["xrefs"]), ("Poss. allofam", e["possallo"])):
        if fld:
            rels.append(
                f'<div class="conn-row"><span class="rl">{label}</span>'
                f'<span class="reltgt">{rel_render(fld)}</span></div>'
            )
    connhtml = f'<section class="conn"><h3>Connections</h3>{"".join(rels)}</section>' if rels else ""

    # reconstruction analysis (the etymon's phonological structure) — exposed by neither the
    # original site nor us before; ~40% of etyma carry it. medial is always empty, so omit.
    phon_fields = [
        ("handle", e["handle"]),
        ("prefix", e["prefix"]),
        ("initial", e["initial"]),
        ("rhyme", e["rhyme"]),
        ("tone", e["tone"]),
        ("suffix", e["suffix"]),
    ]
    chips = [(lab, val) for lab, val in phon_fields if val]
    cover = " · ".join(x for x in (e["initcover"], e["rhymecover"]) if x)
    if cover:
        chips.append(("cover", cover))
    phonhtml = ""
    if chips:
        cells = "".join(
            f'<span class="pf-f"><span class="rl">{lab}</span>' f'<span class="val">{esc(val)}</span></span>'
            for lab, val in chips
        )
        phonhtml = (
            f'<section class="phon"><h3>Reconstruction analysis</h3>' f'<div class="phon-grid">{cells}</div></section>'
        )

    pf = esc(alt(e["protoform"]))
    plg_ab = e["plg"] or ""
    plg_full = esc(PLG_FULL.get(plg_ab, plg_ab))
    if plg_ab and e["grpid"] is not None:
        plg_html = f'<a href="/group/{e["grpid"]}" title="{esc(plg_ab)}">{plg_full}</a>'
    elif plg_ab:
        plg_html = f'<span title="{esc(plg_ab)}">{plg_full}</span>'
    else:
        plg_html = ""
    badges = '<span class="badge del">deleted</span>' if (e["status"] or "").upper() == "DELETE" else ""
    exm = ' · <span class="exm">exemplary</span>' if (e["exemplary"] or "") == "x" else ""

    cite_text = f"STEDT etymon #{e['tag']}, *{alt(e['protoform'])} ‘{e['protogloss']}’. {CITE_BASE}/etymon/{e['tag']} (accessed [ACCESSED])"
    bib = (
        "@misc{stedt-" + str(e["tag"]) + ",\n"
        "  title  = {{*" + alt(e["protoform"] or "") + " '" + (e["protogloss"] or "") + "'}},\n"
        "  author = {STEDT},\n"
        "  year   = {2017},\n"
        "  note   = {Sino-Tibetan Etymological Dictionary and Thesaurus (STEDT) v1.0, etymon #" + str(e["tag"]) + "},\n"
        "  url    = {" + CITE_BASE + "/etymon/" + str(e["tag"]) + "}\n"
        "}"
    )
    refs_line = f'<div>References: {esc(e["notes"])}</div>' if e["notes"] else ""
    apparatus = f"""
    <section class="apparatus"><h3>Cite this entry</h3>
      <div class="citebox">
        <div>STEDT etymon #{e['tag']}, <code>*{pf} ‘{esc(e['protogloss'])}’</code>.</div>
        <div>Stable link: <code>{esc(CITE_BASE)}/etymon/{e['tag']}</code></div>
        <div>Data: STEDT v1.0 (2017). Accessed: <span class="adate"></span>.</div>
        {refs_line}
        <div class="cite-actions">
          <button class="copybtn" data-cite="{esc(cite_text)}">Copy citation</button>
          <button class="copybtn" data-cite="{esc(bib)}">Copy BibTeX</button>
        </div>
        <details class="seg"><summary>BibTeX</summary><pre class="diff">{esc(bib)}</pre></details>
      </div>
    </section><script type="module" src="/assets/cite.js"></script>"""

    return page(
        f"*{alt(e['protoform'])} ‘{e['protogloss']}’",
        _ETYMON.render(
            tag=e["tag"],
            pf=Markup(pf),
            badges=Markup(badges),
            pg=Markup(esc(e["protogloss"])),
            plg_html=Markup(plg_html),
            exm=Markup(exm),
            crumbs=Markup(crumb or esc(ecat)),
            phonhtml=Markup(phonhtml),
            reflexeshtml=Markup(reflexeshtml),
            noteshtml=Markup(noteshtml),
            mesohtml=Markup(mesohtml),
            reconhtml=Markup(reconhtml),
            connhtml=Markup(connhtml),
            apparatus=Markup(apparatus),
        ),
        nav="reconstructions",
    )


def syl_pop(info):
    """SYNC(syllable-links) ↔ web/src/rows.js sylLink popover. The hover/focus popover for a linked
    syllable: its etymon's *protoform 'gloss'. info: (pf, pg)."""
    pfx, pgl = info
    g = f" ‘{esc(pgl)}’" if pgl else ""
    return f'<span class="sylpop">*{esc(alt(pfx))}{g}</span>'


def syl_form(reflex, syn, pf=None, self_tag=None):
    """SYNC(syllable-links) ↔ web/src/rows.js sylLink — keep the markup identical.
    Reflex surface form as HTML with each tagged syllable linked to its own etymon, each carrying a
    hover/focus popover previewing that etymon (*protoform 'gloss'). On an etymon page, pass self_tag =
    that etymon: the syllable that IS this etymon is marked but not linked (you're already here).
    Returns None to fall back to the plain form + trailing chips. pf: tag -> (protoform, protogloss)."""
    if not syn:
        return None
    syls, dl, prefix = syllabify(reflex or "")
    if any(k >= len(syls) for k in syn):       # a tag must land on a real syllable
        return None
    pf = pf or {}
    out = esc(prefix)
    for i, syl in enumerate(syls):
        tag = syn.get(i)
        base = esc(syl)
        if tag is not None and tag == self_tag:
            out += f'<span class="syl-self">{base}</span>'   # this etymon's own reflex syllable
        elif tag is not None:
            info = pf.get(tag)
            out += f'<a class="syl" href="{etymon_href(tag)}">{base}{syl_pop(info) if info else ""}</a>'
        else:
            out += base
        d = dl[i] if i < len(dl) else ""
        out += esc(d).replace("◦", '<span class="br">◦</span>')
    return out


def language(lgid):
    conn = con()
    canon_of, members = canonical_languages()
    canon = canon_of.get(lgid, lgid)
    sibs = members.get(canon, [lgid])  # every source-variant lgid of this lect
    ln = conn.execute("SELECT * FROM languagenames WHERE lgid=?", (canon,)).fetchone()
    if not ln:
        conn.close()
        return page("Not found", "<p>No such language.</p>")
    grp = conn.execute("SELECT grpid,grpno,grp,plg FROM languagegroups WHERE grpid=?", (ln["grpid"],)).fetchone()
    # all attested forms across every source, each row carrying its own source (the work) + locus
    qm = ",".join("?" * len(sibs))
    rows = conn.execute(
        f"""SELECT l.rn, l.reflex, l.gloss, l.gfn, l.semkey, l.srcid, l.lgid,
            ln.srcabbr AS srcabbr, sb.citation AS citation
        FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid
        LEFT JOIN srcbib sb ON sb.srcabbr=ln.srcabbr
        WHERE l.lgid IN ({qm})
        ORDER BY l.semkey, ln.srcabbr, l.reflex""",
        sibs,
    ).fetchall()
    total = len(rows)
    chap = {r["semkey"]: r["chaptertitle"] for r in conn.execute("SELECT semkey,chaptertitle FROM chapters")}
    lin = group_lineage(conn, grp["grpno"]) if grp else []
    # a reflex can belong to several etyma (polymorphemic); collect all, ordered by morpheme. We also
    # keep ind (syllable position) so a tagged syllable can link to its own etymon — same as search
    # (web/src/search.js byInd -> rows.js sylLink). rn_syn[rn] = {ind: tag}; a position tagged with two
    # different etyma is ambiguous, so that reflex drops to the flat trailing-chip fallback.
    rn_tags, rn_syn, rn_syn_bad = {}, {}, set()
    rns = [r["rn"] for r in rows]
    for i in range(0, len(rns), 900):
        chunk = rns[i : i + 900]
        qmk = ",".join("?" * len(chunk))
        for hr in conn.execute(f"SELECT rn, tag, ind FROM lx_et_hash WHERE tag>0 AND rn IN ({qmk}) ORDER BY rn, ind", chunk):
            rn_tags.setdefault(hr["rn"], []).append(hr["tag"])
            byind = rn_syn.setdefault(hr["rn"], {})
            if hr["ind"] in byind and byind[hr["ind"]] != hr["tag"]:
                rn_syn_bad.add(hr["rn"])
            else:
                byind[hr["ind"]] = hr["tag"]
    plabels = proto_labels(conn, {t for ts in rn_tags.values() for t in ts})
    # lexical notes per reflex (same set the etymon page shows), revealed on hover on the gloss
    lnotes = {}
    for i in range(0, len(rns), 900):
        chunk = rns[i : i + 900]
        qmk = ",".join("?" * len(chunk))
        for nr in conn.execute(
            f"SELECT rn, xmlnote FROM notes WHERE spec='L' AND notetype!='I' "
            f"AND xmlnote IS NOT NULL AND rn IN ({qmk}) ORDER BY ord, noteid",
            chunk,
        ):
            lnotes.setdefault(nr["rn"], []).append(nr["xmlnote"])
    # a lect's ISO / short-name may live on a source-variant sibling, not the canonical lgid;
    # back-fill from any sibling so the lect's own page shows them (group() back-fills the same way)
    sil, lgab = ln["silcode"] or "", ln["lgabbr"] or ""
    if (not sil or not lgab) and len(sibs) > 1:
        for sr in conn.execute(f"SELECT silcode, lgabbr FROM languagenames WHERE lgid IN ({qm})", sibs):
            sil = sil or (sr["silcode"] or "")
            lgab = lgab or (sr["lgabbr"] or "")
    conn.close()

    crumb_links = ['<a href="/languages">Languages</a>'] + [
        f'<a href="/group/{gg["grpid"]}">{(esc(gg["grpno"]) + " ") if gg["grpno"] else ""}{esc(gg["grp"])}</a>'
        for gg in lin
    ]
    nsrc = len({r["srcabbr"] for r in rows if r["srcabbr"]})
    meta = []
    if lgab:
        meta.append(Markup(f"<span><b>abbr</b> {esc(lgab)}</span>"))
    if sil:
        meta.append(Markup(f"<span><b>ISO 639-3</b> {iso_link(sil)}</span>"))
    if nsrc > 1:
        meta.append(Markup(f"<span><b>{nsrc}</b> sources</span>"))
    meta.append(Markup(f"<span><b>{total:,}</b> reflexes</span>"))

    groups = {}
    for r in rows:
        sk = r["semkey"] or ""
        groups.setdefault(sk.split(".")[0] if sk else "", []).append(r)
    keys = sorted(groups, key=lambda k: (k == "", natkey(k)))
    openall = total < 100

    def seginfo(key):
        items = groups[key]
        ttl = "(unclassified)" if key == "" else (chap.get(key) or chap.get(key + ".0") or f"Chapter {key}")
        rfx = []
        # SYNC(reflex-row) ↔ web/src/rows.js reflexRow — keep this server-rendered reflex row's
        # fields/order/classes/links identical to the client one.
        for r in items:
            sk = r["semkey"] or ""
            cat = chap.get(sk) or sk
            catcell = (
                f'<a class="lang" href="/thesaurus/{esc(sk)}">{esc(cat)}</a>' if sk else '<span class="lang">—</span>'
            )
            pos = f'<span class="pos">{esc(r["gfn"])}</span>' if r["gfn"] else ""
            # when each tagged syllable lands cleanly, link the syllables in place (shows which
            # morpheme is which etymon); otherwise fall back to the plain form + trailing via chips.
            syn = None if r["rn"] in rn_syn_bad else rn_syn.get(r["rn"])
            linked = syl_form(r["reflex"], syn, plabels)
            vias = []
            if linked is not None:
                form = linked
            else:
                form = esc(r["reflex"]).replace("◦", '<span class="br">◦</span>')
                seen = set()
                for t in rn_tags.get(r["rn"], []):
                    if t in plabels and t not in seen:
                        seen.add(t)
                        vias.append(f'<a class="via" href="{etymon_href(t)}">*{esc(alt(plabels[t][0]))}</a>')
            # un-segmented etyma trail the gloss as inline chips (same geometry as the search rows);
            # syllable-linked or etymon-less rows have none.
            via = f'<span class="vias">{" ".join(vias)}</span>' if vias else ""
            # each row shows the source it is attested in (the work) + the locus within it
            loc = f': {esc(r["srcid"])}' if r["srcid"] else ""
            if r["srcabbr"]:
                src = f'<a class="src" href="{source_href(r["srcabbr"])}">{esc(r["citation"] or r["srcabbr"])}{loc}</a>'
            else:
                src = f'<span class="src">{esc(r["citation"] or "")}{loc}</span>'
            if lnotes.get(r["rn"]):
                # the popover lives inside the inline gloss <span>, so render each note as an inline
                # <span class="np"> (not render_note's block <p>) — valid markup + cleanly separable
                pop = "".join(
                    '<span class="np">' + render_note(x).replace('<p class="np">', "").replace("</p>", "") + "</span>"
                    for x in lnotes[r["rn"]]
                )
                gl = (
                    f'<span class="g noted" tabindex="0">{esc(r["gloss"])}'
                    f'<span class="notepop" role="note">{pop}</span></span>'
                )
            else:
                gl = f'<span class="g">{esc(r["gloss"])}</span>'
            rfx.append(
                f'<div class="rfx" id="rn{r["rn"]}"><a class="rnlink" href="#rn{r["rn"]}" aria-label="Permalink to this entry"></a>{catcell}'
                f'<span class="form">{form} {pos}{gl}{via}</span>'
                f"{src}</div>"
            )
        return {"open": openall, "ttl": Markup(esc(ttl)), "n": len(items), "rfx": Markup("".join(rfx))}

    segs = [seginfo(key) for key in keys]
    return page(
        ln["language"],
        _LANGUAGE.render(
            lang=Markup(esc(ln["language"])),
            crumbs=Markup(" &nbsp;›&nbsp; ".join(crumb_links)),
            meta=meta,
            openall=openall,
            segs=segs,
        ),
        nav="languages",
    )


def source(srcabbr):
    conn = con()
    s = conn.execute("SELECT * FROM srcbib WHERE srcabbr=?", (srcabbr,)).fetchone()
    if not s:
        conn.close()
        return page("Not found", "<p>No such source.</p>")
    notes = conn.execute(
        """SELECT xmlnote FROM notes WHERE id=? AND spec='S' AND notetype!='I'
                         AND xmlnote IS NOT NULL ORDER BY ord, noteid""",
        (srcabbr,),
    ).fetchall()
    langs = conn.execute(
        """SELECT ln.lgid AS lgid, ln.language AS language, ln.lgabbr AS lgabbr,
            ln.silcode AS silcode, g.grp AS subgroup, g.grpno AS grpno, g.grpid AS grpid,
            count(l.rn) AS n
        FROM languagenames ln LEFT JOIN lexicon l ON l.lgid=ln.lgid
        LEFT JOIN languagegroups g ON g.grpid=ln.grpid
        WHERE ln.srcabbr=? AND ln.language!='' AND ln.language NOT LIKE '*%' GROUP BY ln.lgid
        HAVING n>0 ORDER BY ln.language""",
        (srcabbr,),
    ).fetchall()
    conn.close()
    total = sum(l["n"] for l in langs)
    # the visible reference line includes the imprint (via the shared formatter), like the index and
    # the copy-citation — so the venue isn't relegated to a separate chip on the detail page alone.
    cite = source_reference(s)
    meta = []
    meta.append(Markup(f"<span><b>{len(langs)}</b> languages</span>"))
    meta.append(Markup(f"<span><b>{total:,}</b> reflexes</span>"))

    def langinfo(l):
        bits = [esc(x) for x in (l["grpno"], l["subgroup"]) if x]
        grp = " ".join(bits)
        grplink = f'<a href="/group/{l["grpid"]}">{grp}</a>' if (l["grpid"] is not None and grp) else grp
        iso = f' · ISO {iso_link(l["silcode"])}' if l["silcode"] else ""
        ab = f' <span class="lgab">{esc(l["lgabbr"])}</span>' if l["lgabbr"] else ""
        return {
            "canon": canon_lgid(l["lgid"]),
            "language": Markup(esc(l["language"])),
            "ab": Markup(ab),
            "grplink": Markup(grplink),
            "iso": Markup(iso),
            "n_fmt": f"{l['n']:,}",
        }

    langinfos = [langinfo(l) for l in langs]

    citehtml = (
        Markup(
            f'<div class="pg" style="font-variant:normal;font-size:16px;color:var(--soft);letter-spacing:0">{esc(cite)}</div>'
        )
        if cite
        else Markup("")
    )

    # copy-ready "Cite this source" apparatus (parallels the etymon page; wires the previously
    # orphaned .citebox CSS). Access date is a fill-in blank, like the etymon citebox (static site).
    src_url = f"{CITE_BASE}/source/{s['srcabbr']}"
    cite_full = cite or (s["citation"] or s["srcabbr"])
    cite_as = f"{cite_full} — via STEDT, {src_url} (accessed [ACCESSED])."
    # BibTeX for the source, parallel to the etymon citebox so both cite-boxes offer it.
    # imprint is free text (series/publisher/place), so keep it in note rather than mis-splitting it.
    bibkey = "stedt-src-" + re.sub(r"[^A-Za-z0-9]+", "-", s["srcabbr"] or "source").strip("-")
    bib_lines = ["@misc{" + bibkey + ","]
    if s["author"]:
        bib_lines.append("  author = {" + s["author"] + "},")
    if s["title"]:
        bib_lines.append("  title  = {{" + s["title"] + "}},")
    if s["year"]:
        bib_lines.append("  year   = {" + str(s["year"]) + "},")
    _note = "; ".join(
        x
        for x in (
            s["imprint"],
            "Accessed via STEDT (Sino-Tibetan Etymological Dictionary and Thesaurus) v1.0, source "
            + (s["srcabbr"] or ""),
        )
        if x
    )
    bib_lines.append("  note   = {" + _note + "},")
    bib_lines.append("  url    = {" + src_url + "}")
    bib_lines.append("}")
    src_bib = "\n".join(bib_lines)
    apparatus = Markup(f"""
    <section class="apparatus"><h3>Cite this source</h3>
      <div class="citebox">
        <div><code>{esc(cite_full)} — via STEDT, {esc(src_url)} (accessed <span class="adate"></span>).</code></div>
        <div>Stable link: <code>{esc(src_url)}</code></div>
        <div class="cite-actions">
          <button class="copybtn" data-cite="{esc(cite_as)}">Copy citation</button>
          <button class="copybtn" data-cite="{esc(src_bib)}">Copy BibTeX</button>
        </div>
        <details class="seg"><summary>BibTeX</summary><pre class="diff">{esc(src_bib)}</pre></details>
      </div>
    </section><script type="module" src="/assets/cite.js"></script>""")
    return page(
        s["citation"] or s["srcabbr"],
        _SOURCE.render(
            srcabbr=Markup(esc(s["srcabbr"])),
            cit_title=Markup(esc(s["citation"] or s["srcabbr"])),
            citehtml=citehtml,
            meta=meta,
            notes=[Markup(render_note(r["xmlnote"])) for r in notes],
            langs=langinfos,
            apparatus=apparatus,
        ),
        nav="sources",
    )


def group(grpid):
    conn = con()
    g = conn.execute("SELECT * FROM languagegroups WHERE grpid=?", (grpid,)).fetchone()
    if not g:
        conn.close()
        return page("Not found", "<p>No such group.</p>")
    grpno = g["grpno"]
    lin = group_lineage(conn, grpno)
    depth = str(grpno).count(".") if grpno is not None else 0
    children = (
        conn.execute(
            """SELECT grpid, grpno, grp, plg FROM languagegroups
        WHERE grpno LIKE ? AND (length(grpno)-length(replace(grpno,'.','')))=?
        ORDER BY grpno""",
            (str(grpno) + ".%", depth + 1),
        ).fetchall()
        if grpno is not None
        else []
    )
    childinfo = []
    for ch in children:
        # count canonical member lects (distinct non-proto name == one lect within a grpid),
        # not raw language×source rows, so the tally matches the subgroup's own page header
        nl = conn.execute(
            """SELECT count(DISTINCT ln.language) FROM languagenames ln
            JOIN lexicon l ON l.lgid=ln.lgid
            WHERE ln.grpid=? AND ln.language NOT LIKE '*%'""",
            (ch["grpid"],),
        ).fetchone()[0]
        childinfo.append((ch, nl))
    # member lects directly attested at this node: collapse the per-source lgids of one lect onto its
    # canonical page (summing forms, merging sources), and drop proto-forms — they are this group's own
    # reconstruction (the plg + Reconstructions section), not member languages.
    langrows = conn.execute(
        """SELECT ln.lgid AS lgid, ln.language AS language, ln.lgabbr AS lgabbr,
            ln.silcode AS silcode, ln.srcabbr AS srcabbr, sb.citation AS citation, count(l.rn) AS n
        FROM languagenames ln LEFT JOIN srcbib sb ON sb.srcabbr=ln.srcabbr
        JOIN lexicon l ON l.lgid=ln.lgid
        WHERE ln.grpid=? AND ln.language NOT LIKE '*%'
        GROUP BY ln.lgid HAVING n>0""",
        (grpid,),
    ).fetchall()
    canon_of = canonical_languages()[0]
    lects = {}
    for r in langrows:
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
    langs = sorted(lects.values(), key=lambda d: (d["language"] or "").lower())
    recons = conn.execute(
        """SELECT e.tag AS tag, e.protoform AS protoform, e.protogloss AS protogloss, e.exemplary AS exemplary
        FROM etyma e WHERE e.grpid=? AND coalesce(upper(e.status),'')!='DELETE'
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
    crumb_links = ['<a href="/languages">Languages</a>'] + [
        f'<a href="/group/{gg["grpid"]}">{(esc(gg["grpno"]) + " ") if gg["grpno"] else ""}{esc(gg["grp"])}</a>'
        for gg in lin
    ]
    meta = []
    if langs:
        meta.append(Markup(f"<span><b>{len(langs)}</b> languages</span>"))
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

    def subinfo(ch, nl):
        code = f'<span class="grpno">{esc(ch["grpno"])}</span>' if ch["grpno"] else ""
        lab = code + esc(ch["grp"]) + (f' <span class="plg2">({esc(ch["plg"])})</span>' if ch["plg"] else "")
        return {"grpid": ch["grpid"], "lab": Markup(lab), "nl": nl}

    subs = [subinfo(ch, nl) for ch, nl in childinfo]

    def langinfo(l):
        ab = f' <span class="lgab">{esc(l["lgabbr"])}</span>' if l["lgabbr"] else ""
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
            "n_fmt": f"{l['n']:,}",
        }

    langinfos = [langinfo(l) for l in langs]

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
            recons=reconinfos,
            nrecons=len(recons),
        ),
        nav="languages",
    )
