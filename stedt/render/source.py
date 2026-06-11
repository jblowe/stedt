"""Source (bibliography entry) page: its languages, reconstruction sets, and citation apparatus."""

import re

from markupsafe import Markup

from .config import CITE_BASE
from .db import LEX_VISIBLE, con
from .text import cite_tail, esc, iso_link, plural, rfx_noun
from .notes import render_note
from .shell import page, canon_lgid, source_reference
from .templating import env

_SOURCE = env.get_template("source.html")


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
        f"""SELECT ln.lgid AS lgid, ln.language AS language, ln.lgabbr AS lgabbr,
            ln.silcode AS silcode, g.grp AS subgroup, g.grpno AS grpno, g.grpid AS grpid,
            count(l.rn) AS n
        FROM languagenames ln LEFT JOIN lexicon l ON l.lgid=ln.lgid AND {LEX_VISIBLE}
        LEFT JOIN languagegroups g ON g.grpid=ln.grpid
        WHERE ln.srcabbr=? AND ln.language!='' AND ln.language NOT LIKE '*%' GROUP BY ln.lgid
        HAVING n>0 ORDER BY ln.language COLLATE unaccent""",
        (srcabbr,),
    ).fetchall()
    # previously published reconstruction sets ('*Tibeto-Burman' …) held in this source — a third
    # of some reconstruction sources' records, and JRO-Tilung's ONLY records; the original lists
    # them among the source's languages, we give them their own labeled section
    plangs = conn.execute(
        f"""SELECT ln.lgid AS lgid, ln.language AS language, ln.lgabbr AS lgabbr,
            ln.silcode AS silcode, g.grp AS subgroup, g.grpno AS grpno, g.grpid AS grpid,
            count(l.rn) AS n
        FROM languagenames ln LEFT JOIN lexicon l ON l.lgid=ln.lgid AND {LEX_VISIBLE}
        LEFT JOIN languagegroups g ON g.grpid=ln.grpid
        WHERE ln.srcabbr=? AND ln.language LIKE '*%' GROUP BY ln.lgid
        HAVING n>0 ORDER BY ln.language COLLATE unaccent""",
        (srcabbr,),
    ).fetchall()
    conn.close()
    total = sum(l["n"] for l in langs)
    ptotal = sum(l["n"] for l in plangs)
    # the visible reference line includes the imprint (via the shared formatter), like the index and
    # the copy-citation — so the venue isn't relegated to a separate chip on the detail page alone.
    cite = source_reference(s)
    meta = []
    if langs:  # a reconstruction-only source (JRO-Tilung) shouldn't lead with '0 languages · 0 reflexes'
        meta.append(Markup(f"<span><b>{len(langs)}</b> {plural(len(langs), 'language')}</span>"))
        meta.append(Markup(f"<span><b>{total:,}</b> {rfx_noun(total)}</span>"))
    if plangs:
        meta.append(Markup(f"<span><b>{ptotal:,}</b> {plural(ptotal, 'reconstruction record')}</span>"))

    def langinfo(l, noun=None):
        bits = [esc(x) for x in (l["grpno"], l["subgroup"]) if x]
        grp = " ".join(bits)
        grplink = f'<a href="/group/{l["grpid"]}">{grp}</a>' if (l["grpid"] is not None and grp) else grp
        # the source's own short name follows the language name ('Jingpho (Assam) as
        # KACHIN(ASSAM)') — and only when it differs from it: the bare chip both echoed the
        # name uselessly ('Kadu KADU') and read as unexplained decoration
        ab = (l["lgabbr"] or "").strip()
        as_ab = (f' <span class="asab">as <span class="lgab">{esc(ab)}</span></span>'
                 if ab and ab.lower() != (l["language"] or "").strip().lower() else "")
        mid = []
        if grplink:
            mid.append(grplink)
        if l["silcode"]:
            mid.append(f"ISO {iso_link(l['silcode'])}")
        return {
            "canon": canon_lgid(l["lgid"]),
            "language": Markup(esc(l["language"])),
            "ab2": Markup(as_ab),
            "mid": Markup(" · ".join(mid)),
            "n_txt": f"{l['n']:,} {noun(l['n']) if noun else rfx_noun(l['n'])}",
        }

    langinfos = [langinfo(l) for l in langs]
    planginfos = [langinfo(l, noun=lambda n: plural(n, "record")) for l in plangs]

    citehtml = (
        Markup(
            f'<div class="pg citeline">{esc(cite)}</div>'
        )
        if cite
        else Markup("")
    )

    # copy-ready "Cite this source" apparatus (parallels the etymon page; wires the previously
    # orphaned .citebox CSS). Access date is a fill-in blank, like the etymon citebox (static site).
    src_url = f"{CITE_BASE}/source/{s['srcabbr']}"
    cite_full = cite or (s["citation"] or s["srcabbr"])
    cite_as = f"{cite_full} — via STEDT, {cite_tail(src_url)}"
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
        <div><code>{esc(cite_full)} — via STEDT, {esc(src_url)} (accessed <span class="adate">[date]</span>).</code></div>
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
            plangs=planginfos,
            apparatus=apparatus,
        ),
        nav="sources",
    )
