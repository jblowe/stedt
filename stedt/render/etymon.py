"""Etymon page: the reconstruction with its reflexes, notes, and connections."""

import re
import urllib.parse

from markupsafe import Markup

from .config import CITE_BASE, PLG_FULL
from .db import ETY_LIVE, LEX_VISIBLE, con
from .text import cite_tail, esc, alt, natkey, sortkey
from .notes import note_label, render_note
from .rows import disp_form, syl_form
from .shell import page, breadcrumb, proto_labels
from .shell import etymon_href, source_href, language_href, reflex_href
from .templating import env

def _grp_norm(s):
    s = (s or "").lstrip("*").lower()
    s = re.sub(r"\([^)]*\)", "", s)  # parenthetical qualifiers: '(Ao Group)', '(previously published …)'
    s = re.sub(r"/.*$", "", s)  # slash-alternative tail: 'Northern Naga/Konyakian'
    return re.sub(r"[^a-z0-9]", "", s)


def _is_own_proto(language, grp):
    """True when a proto-lect row ('*Tibeto-Burman') IS its group's own proto-language, so the
    group's plg (PTB) labels it faithfully; False for guest reconstructions merely filed in a
    group ('*Tibeto-Karen' in the TB bucket, '*Common Lahu' under Central Loloish, '*Kuki'
    under Kuki-Chin) — those must keep their published attribution verbatim. Equality after
    qualifier-stripping, NOT a prefix test: 'Kuki' is a prefix of 'Kuki-Chin' but a different
    published taxon."""
    lang = _grp_norm(language)
    return bool(lang) and lang == _grp_norm(grp)


def _seq_label(s):
    """Allofam label from the curated sequence: integer -> '1', fraction -> '1a'/'1b'…
    (twin of legacy/render.py _fmt_seq — same labels on both UIs)."""
    try:
        f = float(s)
    except (TypeError, ValueError):
        return s or ""
    if f == int(f):
        return str(int(f))
    frac = str(s).split(".")[-1]
    return str(int(f)) + (chr(ord("a") - 1 + int(frac[0])) if frac and frac[0].isdigit() else "")


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
        """SELECT xmlnote, id FROM notes WHERE tag=? AND spec='E' AND notetype NOT IN ('F','I')
                         AND xmlnote IS NOT NULL ORDER BY ord, noteid""",
        (tag,),
    ).fetchall()
    # a note whose id carries a grpid is anchored to that subgroup in the reflex table — the
    # original renders it as a footnote on the band. The anchor can be an ANCESTOR of the bands
    # actually present (e.g. 'Tani' over a page banded 1.1.1.1 Western Tani …), so placement is
    # "first band at or under the anchor", matching the original's sorted-position behavior.
    anchored = []  # (grpno, grp name, note row)
    if any(n["id"] for n in notes):
        unanchored = []
        for n in notes:
            gr = conn.execute("SELECT grpno, grp FROM languagegroups WHERE grpid=?", (n["id"],)).fetchone() if n["id"] else None
            if gr and gr["grpno"]:
                anchored.append((gr["grpno"], gr["grp"] or "", n))
            else:
                unanchored.append(n)
        notes = unanchored
    # Chinese comparanda (notetype='F') are a distinct class — legacy gave them their own block
    # rather than burying them in the general Notes; keep that separation.
    compar = conn.execute(
        """SELECT xmlnote FROM notes WHERE tag=? AND spec='E' AND notetype='F'
                         AND xmlnote IS NOT NULL ORDER BY ord, noteid""",
        (tag,),
    ).fetchall()
    rows = conn.execute(
        f"""SELECT l.rn AS rn, ln.language AS language, ln.lgsort AS lgsort, l.lgid AS lgid, l.reflex AS form, l.gloss, l.gfn AS gfn,
            l.srcid AS srcid, g.grp AS subgroup, g.grpno AS groupnode, g.plg AS grpplg, g.grpid AS grpid,
            sb.citation AS citation, ln.srcabbr AS srcabbr
        FROM lx_et_hash h JOIN lexicon l ON l.rn=h.rn
        JOIN languagenames ln ON ln.lgid=l.lgid
        LEFT JOIN languagegroups g ON g.grpid=ln.grpid
        LEFT JOIN srcbib sb ON sb.srcabbr=ln.srcabbr
        WHERE h.tag=? AND {LEX_VISIBLE} GROUP BY l.rn""",
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
    # computed allofam family: etyma in one chapter sharing the integer part of the curated
    # sequence are allofams of one root — how the original derives its Allofams box (the
    # allofams/xrefs text fields are EMPTY for most family members, so without this the
    # family is invisible; cf. the same query in legacy/render.py).
    family = []
    seq = e["sequence"]
    try:
        seq_ok = seq is not None and float(seq) >= 1  # sequence is REAL; 0/0.0 = unsequenced
    except (TypeError, ValueError):
        seq_ok = False
    if (e["chapter"] or "") and seq_ok:
        family = conn.execute(
            f"""SELECT tag, sequence, protoform, protogloss FROM etyma e
            WHERE chapter=? AND CAST(sequence AS INTEGER)>0
              AND CAST(sequence AS INTEGER)=CAST(? AS INTEGER)
              AND {ETY_LIVE} ORDER BY sequence""",
            (e["chapter"], seq),
        ).fetchall()
        if len(family) < 2:  # just this etymon: no family to show
            family = []
    # cross-reference labels: collect every standalone number in the three xref fields — a
    # superset of what rel_render below will link (comma/semicolon lists, '↭ 686', and numbers
    # embedded in prose), so the labels dict can serve them all. Dotted section refs ('3.4.5')
    # are excluded by the lookarounds.
    digit_tokens = set()
    for fld in (e["allofams"], e["xrefs"], e["possallo"]):
        if fld:
            digit_tokens.update(int(t) for t in re.findall(r"(?<![\w.])\d+(?![\w.])", fld))
    labels = {}
    if digit_tokens:
        toks = list(digit_tokens)
        qm = ",".join("?" * len(toks))
        for r in conn.execute(
            f"SELECT tag,protoform,protogloss FROM etyma e WHERE tag IN ({qm}) AND {ETY_LIVE}",
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
            f"SELECT rn, xmlnote, notetype FROM notes WHERE spec='L' AND notetype!='I' "
            f"AND xmlnote IS NOT NULL AND rn IN ({qm}) ORDER BY ord, noteid",
            chunk,
        ):
            lnotes.setdefault(r["rn"], []).append((r["notetype"], r["xmlnote"]))
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

    # place each anchored note at the first band at-or-under its anchor; no such band -> general list
    sg_notes_at = {}  # section index -> [(grp name, note row)]
    for grpno, grp, n in anchored:
        idx = next((i for i, k in enumerate(gkeys) if k[0] == grpno or (k[0] or "").startswith(grpno + ".")), None)
        if idx is None:
            notes = list(notes) + [n]
        else:
            sg_notes_at.setdefault(idx, []).append((grp, n))

    jump = ""
    if nsub > 3:
        jump = (
            '<div class="jump">Jump to subgroup: '
            + " · ".join(f'<a href="#sg{i}">{esc(k[1])} ({len(groups[k])})</a>' for i, k in enumerate(gkeys))
            + "</div>"
        )

    sgs = []
    for i, k in enumerate(gkeys):
        # SYNC(reflex-order) ↔ web/src/search.js shapeSortReflexes: order by the curated
        # languagenames.lgsort (the original's ORDER BY … lgsort, reflex, srcabbr, srcid — it
        # interleaves Inscriptional Burmese with Written, as the curators filed them), display
        # name only as fallback.
        items = sorted(
            groups[k],
            key=lambda r: (sortkey(r["lgsort"] or r["language"]), sortkey(r["form"]), r["srcabbr"] or "", str(r["srcid"] or "")),
        )
        rfx = []
        # SYNC(reflex-row) ↔ web/src/rows.js reflexRow — keep this server-rendered reflex row's
        # fields/order/classes/links identical to the client one.
        for r in items:
            if lnotes.get(r["rn"]):
                # a lexical note rides on the gloss behind a circled-i (like the language/search/thesaurus
                # views); show the gloss even when it matches the protogloss so the icon has its anchor
                pop = "".join('<span class="np">' + note_label(nt)
                              + render_note(x).replace('<p class="np">', "").replace("</p>", "")
                              + "</span>" for nt, x in lnotes[r["rn"]])
                g = (f'<span class="g noted" tabindex="0" aria-describedby="np{r["rn"]}">{esc(r["gloss"] or e["protogloss"])}'
                     f'<span class="notepop" role="note" id="np{r["rn"]}">{pop}</span></span>')
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
                form = disp_form(r["form"])
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
        # subgroup-anchored notes render on their band, like the original's band footnotes; the
        # group-name lead-in states the scope (the anchor may cover several adjacent bands)
        sgn = "".join(
            '<div class="note-block sgnote">'
            + render_note(n["xmlnote"]).replace(
                '<p class="np">', f'<p class="np"><span class="sgnote-scope">{esc(grp)} —</span> ', 1
            )
            + "</div>"
            for grp, n in sg_notes_at.get(i, [])
        )
        sgs.append(
            f'<div class="sg" id="sg{i}"><h4>{code}{esc(k[1])}<span class="c">{len(items)}</span></h4>'
            + sgn
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
            # variant letters mark co-reconstructed alternants of one mesoroot: '(a) tsa EAT,
            # (b) tsaat RICE' are a pair, not independent reconstructions (60 mesoroots)
            var = f"({esc(m['variant'])}) " if m["variant"] else ""
            mr += (
                f'<div class="rfx">{langcell}'
                f'<span class="form">{var}<span class="recon">{esc(alt(m["form"]))}</span> '
                f'<span class="g">{esc(m["gloss"])}</span></span>{sm}</div>'
            )
        mesohtml = f'<section class="meso"><h3>Intermediate reconstructions</h3>{mr}</section>'

    # previously published reconstructions (reflex rows whose "language" is a proto-form node)
    reconhtml = ""
    if recon_rows:
        rr = ""
        # Stammbaum order (then form), like the original's ORDER BY grp0..grp4 — not DB order,
        # which scattered one scholar's PTB attributions across the list
        recon_rows = sorted(recon_rows, key=lambda r: (natkey(r["groupnode"] or ""), sortkey(r["form"] or "")))
        for r in recon_rows:
            if _is_own_proto(r["language"], r["subgroup"]) and r["grpplg"]:
                lab = r["grpplg"]
            else:
                lab = (r["language"] or "").strip()  # keep the published name, star and all
            # the label names a proto-language — link it to its group page
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
                f'<span class="reltgt"><span class="recon">{disp_form(alt(r["form"]))}</span>{gl}</span>{cit}</div>'
            )
        reconhtml = f'<section class="conn"><h3>Previously reconstructed as</h3>{rr}</section>'

    # connections: HPTB reconstruction(s) + allofam / xref / possible allofam
    def rel_render(v):
        v = (v or "").strip()
        if not v:
            return ""
        # tag list -> etymon links; the curators separate with ',' or ';' and sometimes lead with
        # the relate-symbol ('↭ 3350; 568; 570')
        if re.fullmatch(r"[↭=\s]*[\d][\d,;\s]*", v):
            parts = []
            for t in re.split(r"[,;\s]+", v.lstrip("↭= ")):
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
        # mixed prose with embedded tags ('↭ *l-kok 486, include PT 3244'): link each standalone
        # number that names a built etymon, in place; the prose stays prose. A search link on the
        # whole string returned 0 results for every such field.
        def _tagtok(mm):
            t = int(mm.group(0))
            if t in labels:
                return f'<a class="xref" href="{etymon_href(mm.group(0))}">#{mm.group(0)}</a>'
            return mm.group(0)

        linked = re.sub(r"(?<![\w.])\d+(?![\w.])", _tagtok, esc(v))
        if "<a " in linked:
            return f'<span class="xref">{linked}</span>'
        g = v.lstrip("↭").strip()  # gloss-based cross-reference
        return f'<a class="xref" href="/search?q={urllib.parse.quote(g)}">{esc(g)}</a>'

    rels = []
    if family:
        fam = []
        for a in family:
            # the #tag disambiguates etyma sharing one curated sequence (e.g. 208/212 both '4')
            # and matches the legacy/original label shape ('1a #695 *lak …')
            lab = (
                f'{esc(_seq_label(a["sequence"]))} #{a["tag"]} '
                f'<span class="recon">{esc(alt(a["protoform"]))}</span>'
                f' ‘{esc(a["protogloss"])}’'
            )
            # each member is its own non-breaking chip (.fam), so a 10-member family wraps at
            # member boundaries instead of mid-label
            fam.append(
                f'<span class="fam"><b>{lab}</b></span>'
                if a["tag"] == tag
                else f'<span class="fam"><a href="{etymon_href(a["tag"])}">{lab}</a></span>'
            )
        rels.append(
            f'<div class="conn-row"><span class="rl">Allofams</span>'
            f'<span class="reltgt famlist">{"".join(fam)}</span></div>'
        )
    for h in hptb:
        # an HPTB reconstruction can sit at a different level than this etymon (130 etyma cite a
        # PLB/PNN/PKar form under a PTB headword) — say which, or the attribution misleads
        hplg = (h["plg"] or "").strip()
        lvl = f' <span class="plg2">({esc(hplg)})</span>' if hplg and hplg != (e["plg"] or "") else ""
        rels.append(
            f'<div class="conn-row"><span class="rl">HPTB{lvl}</span>'
            f'<span class="reltgt"><span class="recon">{esc(alt(h["protoform"]))}</span> ‘{esc(h["protogloss"])}’</span>'
            # 'p.' for a single page, 'pp.' for a range/list (842 of 1,500 hptb refs are one page)
            f'<span class="src">{"pp." if re.search(r"[-–,;]", str(h["pages"] or "")) else "p."} {esc(h["pages"])}</span></div>'
        )
    for label, fld in (("Allofam", e["allofams"]), ("See also", e["xrefs"]), ("Poss. allofam", e["possallo"])):
        if fld:
            # pluralize the curated label by how many refs it actually carries — an 'Allofam' row
            # listing two targets read as a typo next to the computed 'Allofams' family above
            n_refs = len(re.findall(r"(?<![\w.])\d+(?![\w.])", fld))
            if n_refs > 1 and not label.endswith("s"):
                label += "s"
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
    if not e["public"]:  # original marks these '(provisional)' in red on the heading
        exm += (
            ' · <span class="prov" title="This etymon is provisional and should not be considered'
            ' an official STEDT reconstruction.">provisional</span>'
        )

    cite_text = f"STEDT etymon #{e['tag']}, *{alt(e['protoform'])} ‘{e['protogloss']}’. " + cite_tail(
        f"{CITE_BASE}/etymon/{e['tag']}"
    )
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
        <div>Data: STEDT v1.0 (2017). Accessed: <span class="adate">[date]</span>.</div>
        {refs_line}
        <div class="cite-actions">
          <button class="copybtn" data-cite="{esc(cite_text)}">Copy citation</button>
          <button class="copybtn" data-cite="{esc(bib)}">Copy BibTeX</button>
        </div>
        <details class="seg"><summary>BibTeX</summary><pre class="diff">{esc(bib)}</pre></details>
      </div>
    </section><script type="module" src="/assets/cite.js"></script>"""

    return page(
        # the #tag is the citable identity (About says so) — without it, homophonous etyma
        # (#2621/#5521 *d-k-ruk 'SIX') share an identical <title>
        f"*{alt(e['protoform'])} ‘{e['protogloss']}’ #{e['tag']}",
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
        desc=f"Sino-Tibetan etymon #{e['tag']}, *{alt(e['protoform'])} ‘{e['protogloss']}’: "
        "reflexes, reconstructions, and sources.",
    )
