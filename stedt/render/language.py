"""Language (lect) page: every attested form across its sources, grouped by chapter."""

from markupsafe import Markup

from .db import LEX_VISIBLE, con
from .text import esc, alt, natkey, iso_link, rfx_noun
from .notes import note_label, render_note
from .rows import disp_form, syl_form, lgab_span
from .shell import page, group_lineage, proto_labels, canonical_languages
from .shell import etymon_href, source_href, language_href
from .templating import env

_LANGUAGE = env.get_template("language.html")


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
        WHERE l.lgid IN ({qm}) AND {LEX_VISIBLE}
        ORDER BY l.semkey, ln.srcabbr, l.reflex COLLATE unaccent""",
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
            f"SELECT rn, xmlnote, notetype FROM notes WHERE spec='L' AND notetype!='I' "
            f"AND xmlnote IS NOT NULL AND rn IN ({qmk}) ORDER BY ord, noteid",
            chunk,
        ):
            lnotes.setdefault(nr["rn"], []).append((nr["notetype"], nr["xmlnote"]))
    # a lect's ISO / short-name / Namkung page may live on a source-variant sibling, not the
    # canonical lgid; back-fill from any sibling so the lect's own page shows them (group() too).
    # ISO keeps EVERY distinct sibling code (6 lects' sources disagree, e.g. Tujia tji/tjs) —
    # asserting only the canonical variant's code would misdescribe the other variants' records.
    lgab, pi_page = ln["lgabbr"] or "", ln["pi_page"] or ""
    sils = [ln["silcode"]] if ln["silcode"] else []
    if len(sibs) > 1:
        for sr in conn.execute(f"SELECT silcode, lgabbr, pi_page FROM languagenames WHERE lgid IN ({qm})", sibs):
            if sr["silcode"] and sr["silcode"] not in sils:
                sils.append(sr["silcode"])
            lgab = lgab or (sr["lgabbr"] or "")
            pi_page = pi_page or (sr["pi_page"] or "")
    # per-source breakdown — the detail canonicalization folds away (which sources record this
    # lect, under what short name / ISO, how many entries each); shown as its own section when
    # the page merges more than one source variant. Mirrors the original's language-by-source rows.
    nbysib = {}
    for r in rows:
        nbysib[r["lgid"]] = nbysib.get(r["lgid"], 0) + 1
    variants = []
    if len(sibs) > 1:
        for sr in conn.execute(
            f"""SELECT ln2.lgid, ln2.srcabbr, ln2.lgabbr, ln2.silcode, sb.citation
            FROM languagenames ln2 LEFT JOIN srcbib sb ON sb.srcabbr=ln2.srcabbr
            WHERE ln2.lgid IN ({qm}) ORDER BY ln2.srcabbr""",
            sibs,
        ):
            if not nbysib.get(sr["lgid"]):
                continue  # variant contributes no visible records
            mid = []
            if sr["lgabbr"]:
                mid.append("as" + lgab_span(sr["lgabbr"]))
            if sr["silcode"]:
                mid.append("ISO " + iso_link(sr["silcode"]))
            n = nbysib[sr["lgid"]]
            variants.append(
                {
                    "cit": Markup(
                        f'<a class="lang" href="{source_href(sr["srcabbr"])}">{esc(sr["citation"] or sr["srcabbr"])}</a>'
                        if sr["srcabbr"]
                        else esc(sr["citation"] or "")
                    ),
                    "mid": Markup(" · ".join(mid)),
                    "n_txt": f"{n:,} {rfx_noun(n)}",
                }
            )
    # other lects recorded under the same ISO code — the original's 'other sources which include
    # this language' discovery path (Manyak / Menia / Muya), lost when names differ
    seealso = []
    if sils:
        qs = ",".join("?" * len(sils))
        for sr in conn.execute(
            f"""SELECT DISTINCT ln2.language, ln2.lgid FROM languagenames ln2
            WHERE ln2.silcode IN ({qs}) AND ln2.language NOT LIKE '*%' ORDER BY ln2.language""",
            sils,
        ):
            cid = canon_of.get(sr["lgid"], sr["lgid"])
            if cid != canon and (sr["language"] or "") != (ln["language"] or ""):
                if all(cid != s[1] for s in seealso):
                    seealso.append((sr["language"], cid))
    conn.close()

    crumb_links = ['<a href="/languages">Languages</a>'] + [
        f'<a href="/group/{gg["grpid"]}">{(esc(gg["grpno"]) + " ") if gg["grpno"] else ""}{esc(gg["grp"])}</a>'
        for gg in lin
    ]
    nsrc = len({r["srcabbr"] for r in rows if r["srcabbr"]})
    meta = []
    if lgab:
        meta.append(Markup(f"<span><b>abbr</b> {esc(lgab)}</span>"))
    if sils:
        meta.append(Markup(f"<span><b>ISO 639-3</b> {' / '.join(iso_link(s) for s in sils)}</span>"))
    if nsrc > 1:
        meta.append(Markup(f"<span><b>{nsrc}</b> sources</span>"))
    if pi_page:
        # print citation into the phonological-inventory monograph (the original's viewer for it
        # is dead upstream, but the page number remains a usable reference)
        meta.append(Markup(f"<span><b>phon. inventory</b> Namkung 1996, p. {esc(str(pi_page))}</span>"))
    meta.append(Markup(f"<span><b>{total:,}</b> {rfx_noun(total)}</span>"))
    if seealso:
        links = ", ".join(f'<a href="{language_href(cid)}">{esc(nm)}</a>' for nm, cid in seealso)
        meta.append(Markup(f"<span><b>same ISO</b> {links}</span>"))

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
                form = disp_form(r["reflex"])
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
                    '<span class="np">' + note_label(nt)
                    + render_note(x).replace('<p class="np">', "").replace("</p>", "") + "</span>"
                    for nt, x in lnotes[r["rn"]]
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
            variants=variants,
            openall=openall,
            segs=segs,
        ),
        nav="languages",
    )
