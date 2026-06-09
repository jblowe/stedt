"""Entity pages: etymon, language, source, language-group."""
import re
import urllib.parse

from .config import CITE_BASE, PLG_FULL
from .db import con
from .text import esc, alt, natkey, iso_link, suggest_edit_url, rcount_txt
from .notes import render_note
from .shell import page, breadcrumb, group_lineage, reflex_counts, proto_labels, canonical_languages, canon_lgid

def etymon(tag):
    c = con()
    e = c.execute("""SELECT e.*, g.plg AS plg FROM etyma e
        LEFT JOIN languagegroups g ON g.grpid=e.grpid WHERE e.tag=?""", (tag,)).fetchone()
    if not e:
        c.close(); return page("Not found", "<p>No such etymon.</p>")
    notes = c.execute("""SELECT xmlnote FROM notes WHERE tag=? AND spec='E' AND notetype!='I'
                         AND xmlnote IS NOT NULL ORDER BY ord, noteid""", (tag,)).fetchall()
    rows = c.execute("""SELECT l.rn AS rn, ln.language AS language, l.lgid AS lgid, l.reflex AS form, l.gloss, l.gfn AS gfn,
            l.srcid AS srcid, g.grp AS subgroup, g.grpno AS groupnode, g.plg AS grpplg,
            sb.citation AS citation, ln.srcabbr AS srcabbr
        FROM lx_et_hash h JOIN lexicon l ON l.rn=h.rn
        JOIN languagenames ln ON ln.lgid=l.lgid
        LEFT JOIN languagegroups g ON g.grpid=ln.grpid
        LEFT JOIN srcbib sb ON sb.srcabbr=ln.srcabbr
        WHERE h.tag=? GROUP BY l.rn""", (tag,)).fetchall()
    hptb = c.execute("""SELECT h.plg, h.protoform, h.protogloss, h.pages
        FROM et_hptb_hash x JOIN hptb h ON h.hptbid=x.hptbid WHERE x.tag=? ORDER BY x.ord""", (tag,)).fetchall()
    meso = c.execute("""SELECT g.grp AS subgroup, g.grpno AS groupnode, g.grpid AS grpid, m.form, m.gloss, m.variant, m.old_note
        FROM mesoroots m LEFT JOIN languagegroups g ON g.grpid=m.grpid
        WHERE m.tag=? ORDER BY g.grpno, m.id""", (tag,)).fetchall()
    # cross-reference labels: collect every tag mentioned in a pure tag-list field
    digit_tokens = set()
    for fld in (e['allofams'], e['xrefs'], e['possallo']):
        if not fld: continue
        fs = fld.strip()
        if re.fullmatch(r'[\d,\s]+', fs):
            digit_tokens.update(int(t) for t in re.split(r'[,\s]+', fs) if t)
        else:                                  # also a single tag behind a relate-symbol: "↭ 686", "=1318"
            m = re.fullmatch(r'[↭=\s]*(\d+)\s*(?:\([^)]*\))?', fs)
            if m: digit_tokens.add(int(m.group(1)))
    labels = {}
    if digit_tokens:
        toks = list(digit_tokens); qm = ','.join('?' * len(toks))
        for r in c.execute(f"SELECT tag,protoform,protogloss FROM etyma WHERE tag IN ({qm}) "
                           f"AND coalesce(upper(status),'')!='DELETE'", toks):
            labels[r['tag']] = (r['protoform'], r['protogloss'])
    # per-reflex morpheme analysis: a reflex (rn) is segmented into morphemes in lx_et_hash,
    # each tied to an etymon tag (0 = a non-etymon affix). Surface the *other* etyma a reflex
    # also belongs to (i.e. it's a compound) as links.
    rns = [r['rn'] for r in rows]
    analysis = {}
    for i in range(0, len(rns), 900):
        chunk = rns[i:i + 900]; qm = ','.join('?' * len(chunk))
        for r in c.execute(f"SELECT rn, tag FROM lx_et_hash WHERE rn IN ({qm}) ORDER BY rn, ind", chunk):
            analysis.setdefault(r['rn'], []).append(r['tag'])
    # label only sibling etyma that actually have a (non-DELETE) page, so "also contains" never 404s
    morph_tags = list({t for ts in analysis.values() for t in ts if t and t != tag})
    morph_labels = {}
    for i in range(0, len(morph_tags), 900):
        chunk = morph_tags[i:i + 900]; qm = ','.join('?' * len(chunk))
        for r in c.execute(f"SELECT tag, protoform FROM etyma WHERE tag IN ({qm}) "
                           f"AND coalesce(upper(status),'')!='DELETE'", chunk):
            morph_labels[r['tag']] = r['protoform']
    # per-reflex (L) notes — the largest note class; legacy shows these as reflex footnotes.
    lnotes = {}
    for i in range(0, len(rns), 900):
        chunk = rns[i:i + 900]; qm = ','.join('?' * len(chunk))
        for r in c.execute(f"SELECT rn, xmlnote FROM notes WHERE spec='L' AND notetype!='I' "
                           f"AND xmlnote IS NOT NULL AND rn IN ({qm}) ORDER BY ord, noteid", chunk):
            lnotes.setdefault(r['rn'], []).append(r['xmlnote'])
    ecat = e['chapter'] or e['semkey']   # legacy files an etymon by its (more specific) chapter, not semkey
    crumb = breadcrumb(c, ecat)
    c.close()

    # separate attested reflexes from previously-published reconstructions (language is a *proto-form node)
    recon_rows = [r for r in rows if (r['language'] or '').startswith('*')]
    reflex_rows = [r for r in rows if not (r['language'] or '').startswith('*')]

    # group attested reflexes by subgroup, order by stammbaum (groupnode)
    groups = {}
    for r in reflex_rows:
        key = (r['groupnode'] or 'zz', r['subgroup'] or '—')
        groups.setdefault(key, []).append(r)
    gkeys = sorted(groups, key=lambda k: (natkey(k[0]), k[1]))
    nsub = len(gkeys)

    jump = ""
    if nsub > 3:
        jump = '<div class="jump">Jump to subgroup: ' + ' · '.join(
            f'<a href="#sg{i}">{esc(k[1])} ({len(groups[k])})</a>' for i, k in enumerate(gkeys)) + '</div>'

    sgs = []
    for i, k in enumerate(gkeys):
        items = sorted(groups[k], key=lambda r: ((r['language'] or ''), (r['form'] or '')))
        rfx = []
        for r in items:
            form = esc(r['form']).replace('◦', '<span class="br">◦</span>')
            g = f'<span class="g">{esc(r["gloss"])}</span>' if (r['gloss'] and r['gloss'] != e['protogloss']) else ''
            pos = f'<span class="pos">{esc(r["gfn"])}</span>' if r['gfn'] else ''
            lang = f'<a class="lang" href="/language/{canon_lgid(r["lgid"])}">{esc(r["language"])}</a>'
            loc = f': {esc(r["srcid"])}' if r['srcid'] else ''  # per-reflex source locus (page/entry/note)
            if r['srcabbr']:
                src = f'<a class="src" href="/source/{esc(r["srcabbr"])}">{esc(r["citation"] or r["srcabbr"])}{loc}</a>'
            else:
                src = f'<span class="src">{esc(r["citation"] or "")}{loc}</span>'
            seen, links = set(), []
            for mt in analysis.get(r['rn'], []):
                if mt and mt > 0 and mt != tag and mt not in seen and mt in morph_labels:
                    seen.add(mt)
                    links.append(f'<a href="/etymon/{mt}">*{esc(alt(morph_labels[mt]))}</a>')
            anl = f'<span class="anl">also contains {", ".join(links)}</span>' if links else ''
            note = ''.join(f'<div class="rfxnote">{render_note(x)}</div>' for x in lnotes.get(r['rn'], []))
            rfx.append(f'<div class="rfx" id="r{r["rn"]}">{lang}'
                       f'<span class="form"><a href="/language/{canon_lgid(r["lgid"])}#rn{r["rn"]}">{form}</a> {g}{pos}{anl}</span>{src}{note}</div>')
        code = '' if k[0] in (None, 'zz') else f'<span class="grpno">{esc(k[0])}</span>'
        sgs.append(f'<div class="sg" id="sg{i}"><h4>{code}{esc(k[1])}<span class="c">{len(items)}</span></h4>'
                   + ''.join(rfx) + '</div>')

    noteshtml = ""
    if notes:
        noteshtml = ('<section class="notes"><h3>Notes</h3>'
                     + ''.join(f'<div class="note-block">{render_note(r["xmlnote"])}</div>' for r in notes)
                     + '</section>')

    cnt = f'<span class="cnt">{len(reflex_rows)} reflexes · {nsub} subgroups</span>'
    reflexeshtml = (f'<section class="reflexes etymon-rfx"><h3>Reflexes &amp; cognates{cnt}</h3>{jump}{"".join(sgs)}</section>'
                    if sgs else '')

    mesohtml = ''
    if meso:
        mr = ''
        for m in meso:
            sm = f'<span class="src">{esc(m["old_note"])}</span>' if m['old_note'] else '<span class="src"></span>'
            lab = esc(m['subgroup'] or '')
            langcell = (f'<a class="lang" href="/group/{m["grpid"]}">{lab}</a>'
                        if m['grpid'] is not None else f'<span class="lang">{lab}</span>')
            mr += (f'<div class="rfx">{langcell}'
                   f'<span class="form"><span class="recon">{esc(alt(m["form"]))}</span> '
                   f'<span class="g">{esc(m["gloss"])}</span></span>{sm}</div>')
        mesohtml = f'<section class="meso"><h3>Intermediate reconstructions</h3>{mr}</section>'

    # previously published reconstructions (reflex rows whose "language" is a proto-form node)
    reconhtml = ''
    if recon_rows:
        rr = ''
        for r in recon_rows:
            lab = r['grpplg'] or r['subgroup'] or (r['language'] or '').lstrip('*')
            loc = f': {esc(r["srcid"])}' if r['srcid'] else ''
            if r['srcabbr']:
                cit = f'<a class="src" href="/source/{esc(r["srcabbr"])}">{esc(r["citation"] or r["srcabbr"])}{loc}</a>'
            else:
                cit = f'<span class="src">{esc(r["citation"] or "")}{loc}</span>'
            gl = f' ‘{esc(r["gloss"])}’' if r['gloss'] else ''
            rr += (f'<div class="conn-row"><span class="rl">{esc(lab)}</span>'
                   f'<span class="reltgt"><span class="recon">{esc(alt(r["form"]))}</span>{gl}</span>{cit}</div>')
        reconhtml = f'<section class="conn"><h3>Previously reconstructed as</h3>{rr}</section>'

    # connections: HPTB reconstruction(s) + allofam / xref / possible allofam
    def rel_render(v):
        v = (v or '').strip()
        if not v: return ''
        if re.fullmatch(r'[\d,\s]+', v):  # tag list -> etymon links
            parts = []
            for t in re.split(r'[,\s]+', v):
                if not t: continue
                lab = labels.get(int(t))
                if lab:  # only link to a built (non-DELETE) etymon, else show the bare ref
                    parts.append(f'<a class="xref" href="/etymon/{t}">*{esc(alt(lab[0]))} ‘{esc(lab[1])}’</a>')
                else:
                    parts.append(f'<span class="xref">#{esc(t)}</span>')
            return ', '.join(parts)
        # a field embedding a single etymon tag with a relate-symbol/parenthetical (e.g. "↭ 686",
        # "=1318", "2349 (PLB)") — link it to that etymon, not a (dead) gloss search. Keep it tight
        # (anchored ↭/= prefix + bare integer) so section refs like "3.4.5" / "8.8" don't match.
        m = re.fullmatch(r'[↭=\s]*(\d+)\s*(?:\([^)]*\))?', v)
        if m:
            t = m.group(1); lab = labels.get(int(t))
            if lab:
                return f'<a class="xref" href="/etymon/{t}">*{esc(alt(lab[0]))} ‘{esc(lab[1])}’</a>'
            return f'<span class="xref">#{esc(t)}</span>'   # DELETE/missing target: bare ref, not a dead search
        g = v.lstrip('↭').strip()  # gloss-based cross-reference
        return f'<a class="xref" href="/search?q={urllib.parse.quote(g)}">{esc(g)}</a>'
    conn = []
    for h in hptb:
        conn.append(f'<div class="conn-row"><span class="rl">HPTB</span>'
                    f'<span class="reltgt"><span class="lat">{esc(h["protoform"])}</span> ‘{esc(h["protogloss"])}’</span>'
                    f'<span class="src">pp. {esc(h["pages"])}</span></div>')
    for label, fld in (('Allofam', e['allofams']), ('See also', e['xrefs']), ('Poss. allofam', e['possallo'])):
        if fld:
            conn.append(f'<div class="conn-row"><span class="rl">{label}</span>'
                        f'<span class="reltgt">{rel_render(fld)}</span></div>')
    connhtml = f'<section class="conn"><h3>Connections</h3>{"".join(conn)}</section>' if conn else ''

    # reconstruction analysis (the etymon's phonological structure) — exposed by neither the
    # original site nor us before; ~40% of etyma carry it. medial is always empty, so omit.
    phon_fields = [('handle', e['handle']), ('prefix', e['prefix']), ('initial', e['initial']),
                   ('rhyme', e['rhyme']), ('tone', e['tone']), ('suffix', e['suffix'])]
    chips = [(lab, val) for lab, val in phon_fields if val]
    cover = ' · '.join(x for x in (e['initcover'], e['rhymecover']) if x)
    if cover: chips.append(('cover', cover))
    phonhtml = ''
    if chips:
        cells = ''.join(f'<span class="pf-f"><span class="rl">{lab}</span>'
                        f'<span class="val">{esc(val)}</span></span>' for lab, val in chips)
        phonhtml = (f'<section class="phon"><h3>Reconstruction analysis</h3>'
                    f'<div class="phon-grid">{cells}</div></section>')

    pf = esc(alt(e['protoform']))
    plg_ab = e['plg'] or ''
    plg_full = esc(PLG_FULL.get(plg_ab, plg_ab))
    if plg_ab and e['grpid'] is not None:
        plg_html = f'<a href="/group/{e["grpid"]}" title="{esc(plg_ab)}">{plg_full}</a>'
    elif plg_ab:
        plg_html = f'<span title="{esc(plg_ab)}">{plg_full}</span>'
    else:
        plg_html = ''
    badges = '<span class="badge del">deleted</span>' if (e['status'] or '').upper() == 'DELETE' else ''
    exm = ' · <span class="exm">exemplary</span>' if (e['exemplary'] or '') == 'x' else ''

    cite_text = f"STEDT etymon #{e['tag']}, *{alt(e['protoform'])} ‘{e['protogloss']}’. {CITE_BASE}/etymon/{e['tag']} (accessed [ACCESSED])"
    bib = ("@misc{stedt-" + str(e['tag']) + ",\n"
           "  title  = {{*" + alt(e['protoform'] or '') + " '" + (e['protogloss'] or '') + "'}},\n"
           "  author = {STEDT},\n"
           "  year   = {2017},\n"
           "  note   = {Sino-Tibetan Etymological Dictionary and Thesaurus (STEDT) v1.0, etymon #" + str(e['tag']) + "},\n"
           "  url    = {" + CITE_BASE + "/etymon/" + str(e['tag']) + "}\n"
           "}")
    refs_line = f'<div>References: {esc(e["notes"])}</div>' if e['notes'] else ''
    copy_js = ("<script>(function(){var D=new Date().toISOString().slice(0,10);"
               "document.querySelectorAll('.adate').forEach(function(e){e.textContent=D;});"
               "document.querySelectorAll('.copybtn').forEach(function(b){b.addEventListener('click',function(){"
               "navigator.clipboard.writeText((b.dataset.cite||'').replace(/\\[ACCESSED\\]/g,D));"
               "b.textContent='Copied';});});})();</script>")
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
          <a href="{suggest_edit_url(e)}" target="_blank" rel="noopener">Suggest an edit</a>
          <a href="https://github.com/larc-iu/stedt/edit/main/data/etyma/{e['tag']}.yaml"
             target="_blank" rel="noopener">Edit on GitHub</a>
        </div>
        <details class="seg"><summary>BibTeX</summary><pre class="diff">{esc(bib)}</pre></details>
      </div>
    </section>{copy_js}"""

    body = f"""
    <div class="ety-head">
      <span class="etno">STEDT #{e['tag']}</span>
      <div class="pf">{pf}{badges}</div>
      <div class="pg">{esc(e['protogloss'])}</div>
      <div class="pl">{plg_html}{exm}</div>
      <div class="crumbs">Semantic domain: {crumb or esc(ecat)}</div>
    </div>
    {phonhtml}
    {reflexeshtml}
    {noteshtml}
    {mesohtml}
    {reconhtml}
    {connhtml}
    {apparatus}"""
    return page(f"*{alt(e['protoform'])} ‘{e['protogloss']}’", body, nav="reconstructions")

def language(lgid):
    c = con()
    canon_of, members = canonical_languages()
    canon = canon_of.get(lgid, lgid)
    sibs = members.get(canon, [lgid])     # every source-variant lgid of this lect
    ln = c.execute("SELECT * FROM languagenames WHERE lgid=?", (canon,)).fetchone()
    if not ln:
        c.close(); return page("Not found", "<p>No such language.</p>")
    grp = c.execute("SELECT grpid,grpno,grp,plg FROM languagegroups WHERE grpid=?", (ln['grpid'],)).fetchone()
    # all attested forms across every source, each row carrying its own source (the work) + locus
    qm = ','.join('?' * len(sibs))
    rows = c.execute(f"""SELECT l.rn, l.reflex, l.gloss, l.gfn, l.semkey, l.srcid, l.lgid,
            ln.srcabbr AS srcabbr, sb.citation AS citation
        FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid
        LEFT JOIN srcbib sb ON sb.srcabbr=ln.srcabbr
        WHERE l.lgid IN ({qm})
        ORDER BY l.semkey, ln.srcabbr, l.reflex""", sibs).fetchall()
    total = len(rows)
    chap = {r['semkey']: r['chaptertitle'] for r in c.execute("SELECT semkey,chaptertitle FROM chapters")}
    lin = group_lineage(c, grp['grpno']) if grp else []
    # a reflex can belong to several etyma (polymorphemic); collect all, ordered by morpheme.
    rn_tags = {}
    rns = [r['rn'] for r in rows]
    for i in range(0, len(rns), 900):
        chunk = rns[i:i + 900]; qmk = ','.join('?' * len(chunk))
        for hr in c.execute(f"SELECT rn, tag FROM lx_et_hash WHERE tag>0 AND rn IN ({qmk}) ORDER BY rn, ind", chunk):
            rn_tags.setdefault(hr['rn'], []).append(hr['tag'])
    plabels = proto_labels(c, {t for ts in rn_tags.values() for t in ts})
    # lexical notes per reflex (same set the etymon page shows), revealed on hover on the gloss
    lnotes = {}
    for i in range(0, len(rns), 900):
        chunk = rns[i:i + 900]; qmk = ','.join('?' * len(chunk))
        for nr in c.execute(f"SELECT rn, xmlnote FROM notes WHERE spec='L' AND notetype!='I' "
                            f"AND xmlnote IS NOT NULL AND rn IN ({qmk}) ORDER BY ord, noteid", chunk):
            lnotes.setdefault(nr['rn'], []).append(nr['xmlnote'])
    # a lect's ISO / short-name may live on a source-variant sibling, not the canonical lgid;
    # back-fill from any sibling so the lect's own page shows them (group() back-fills the same way)
    sil, lgab = ln['silcode'] or '', ln['lgabbr'] or ''
    if (not sil or not lgab) and len(sibs) > 1:
        for sr in c.execute(f"SELECT silcode, lgabbr FROM languagenames WHERE lgid IN ({qm})", sibs):
            sil = sil or (sr['silcode'] or '')
            lgab = lgab or (sr['lgabbr'] or '')
    c.close()

    crumb_links = ['<a href="/languages">Languages</a>'] + \
                  [f'<a href="/group/{gg["grpid"]}">{(esc(gg["grpno"]) + " ") if gg["grpno"] else ""}{esc(gg["grp"])}</a>' for gg in lin]
    nsrc = len({r['srcabbr'] for r in rows if r['srcabbr']})
    meta = []
    if lgab: meta.append(f'<span><b>abbr</b> {esc(lgab)}</span>')
    if sil: meta.append(f'<span><b>ISO 639-3</b> {iso_link(sil)}</span>')
    if nsrc > 1: meta.append(f'<span><b>{nsrc}</b> sources</span>')
    meta.append(f'<span><b>{total:,}</b> reflexes</span>')

    groups = {}
    for r in rows:
        sk = r['semkey'] or ''
        groups.setdefault(sk.split('.')[0] if sk else '', []).append(r)
    keys = sorted(groups, key=lambda k: (k == '', natkey(k)))
    openall = total < 100
    segs = []
    for key in keys:
        items = groups[key]
        ttl = '(unclassified)' if key == '' else (chap.get(key) or chap.get(key + '.0') or f'Chapter {key}')
        rfx = []
        for r in items:
            sk = r['semkey'] or ''
            cat = chap.get(sk) or sk
            catcell = (f'<a class="lang" href="/thesaurus/{esc(sk)}">{esc(cat)}</a>'
                       if sk else '<span class="lang">—</span>')
            form = esc(r['reflex']).replace('◦', '<span class="br">◦</span>')
            pos = f'<span class="pos">{esc(r["gfn"])}</span>' if r['gfn'] else ''
            seen, vias = set(), []
            for t in rn_tags.get(r['rn'], []):
                if t in plabels and t not in seen:
                    seen.add(t)
                    vias.append(f'<a class="via" href="/etymon/{t}">› *{esc(alt(plabels[t]))}</a>')
            via = f'<span class="anl">{" ".join(vias)}</span>' if vias else ''
            # each row shows the source it is attested in (the work) + the locus within it
            loc = f': {esc(r["srcid"])}' if r['srcid'] else ''
            if r['srcabbr']:
                src = f'<a class="src" href="/source/{esc(r["srcabbr"])}">{esc(r["citation"] or r["srcabbr"])}{loc}</a>'
            else:
                src = f'<span class="src">{esc(r["citation"] or "")}{loc}</span>'
            if lnotes.get(r['rn']):
                # the popover lives inside the inline gloss <span>, so render each note as an inline
                # <span class="np"> (not render_note's block <p>) — valid markup + cleanly separable
                pop = ''.join('<span class="np">' + render_note(x).replace('<p class="np">', '').replace('</p>', '')
                              + '</span>' for x in lnotes[r['rn']])
                gl = (f'<span class="g noted" tabindex="0">{esc(r["gloss"])}'
                      f'<span class="notepop" role="note">{pop}</span></span>')
            else:
                gl = f'<span class="g">{esc(r["gloss"])}</span>'
            rfx.append(f'<div class="rfx" id="rn{r["rn"]}">{catcell}'
                       f'<span class="form">{form} {gl}{pos}{via}</span>'
                       f'{src}</div>')
        # A big lect (Tibetan: ~7,700 forms) would otherwise build tens of thousands of DOM nodes
        # the reader never scrolls to. Each section ships its rows as inert <script> text and
        # materialises them the first time it opens (or on load if it starts open) — see the IIFE.
        segs.append(f'<details class="seg"{" open" if openall else ""}><summary>{esc(ttl)}'
                    f'<span class="c">{len(items)}</span></summary>'
                    f'<div class="seg-body"></div>'
                    f'<script type="text/html" class="seg-src">{"".join(rfx)}</script></details>')

    body = f"""
    <div class="ety-head">
      <div class="plg">Language</div>
      <div class="pagetitle">{esc(ln['language'])}</div>
      <div class="crumbs">{' &nbsp;›&nbsp; '.join(crumb_links)}</div>
      <div class="metabar">{''.join(meta)}</div>
    </div>
    <section class="reflexes"><h3>Attested forms{'' if openall else '<button type="button" class="toggle-all" data-all="0">Expand all</button>'}</h3>{''.join(segs)}</section>
    <script>
    /* Sections render their rows lazily: each <details> carries its forms as inert <script>
       text and materialises them the first time it opens (or on load if it starts open), so a
       7,700-form lect doesn't build ~50k DOM nodes the reader never looks at. reveal() also
       handles a #rn<id> deep link (e.g. from a thesaurus 'attested forms' link) that points
       into a section not yet opened, and tags the row with .rn-target for the highlight — a
       lazily-injected row can't be relied on to match :target (the fragment was already set
       before it existed), so the class is applied explicitly rather than left to CSS. */
    (function(){{
      function fill(d){{
        if(d.dataset.filled) return;
        var s=d.querySelector('script.seg-src'), b=d.querySelector('.seg-body');
        if(s&&b){{ b.innerHTML=s.textContent; d.dataset.filled='1'; }}
      }}
      var segs=[].slice.call(document.querySelectorAll('details.seg'));
      segs.forEach(function(d){{
        d.addEventListener('toggle',function(){{ if(d.open) fill(d); }});
        if(d.open) fill(d);
      }});
      var btn=document.querySelector('.toggle-all');
      if(btn) btn.addEventListener('click',function(){{
        var open=btn.getAttribute('data-all')!=='1';
        segs.forEach(function(d){{ if(open) fill(d); d.open=open; }});
        btn.setAttribute('data-all',open?'1':'0');
        btn.textContent=open?'Collapse all':'Expand all';
      }});
      function reveal(){{
        var prev=document.querySelector('.rfx.rn-target'); if(prev) prev.classList.remove('rn-target');
        var h=location.hash; if(!h||h.length<2) return;
        var id; try{{id=decodeURIComponent(h.slice(1));}}catch(e){{return;}}
        var el=document.getElementById(id);
        if(!el){{
          var needle='id="'+id+'"';
          for(var i=0;i<segs.length;i++){{
            var s=segs[i].querySelector('script.seg-src');
            if(s&&s.textContent.indexOf(needle)>=0){{ fill(segs[i]); segs[i].open=true; break; }}
          }}
          el=document.getElementById(id);
        }}
        if(!el) return;
        var d=el.closest('details'); if(d&&!d.open){{ fill(d); d.open=true; }}
        el.classList.add('rn-target');
        el.scrollIntoView({{block:'center'}});
        // A cold load scrolls before web fonts arrive; their reflow can nudge the row off its
        // mark, so re-settle once fonts are ready — but only if this row is still the target.
        if(document.fonts&&document.fonts.ready) document.fonts.ready.then(function(){{
          if(location.hash.slice(1)===id) el.scrollIntoView({{block:'center'}});
        }});
      }}
      window.addEventListener('hashchange',reveal); reveal();
    }})();
    </script>"""
    return page(ln['language'], body, nav="languages")

def source(srcabbr):
    c = con()
    s = c.execute("SELECT * FROM srcbib WHERE srcabbr=?", (srcabbr,)).fetchone()
    if not s:
        c.close(); return page("Not found", "<p>No such source.</p>")
    notes = c.execute("""SELECT xmlnote FROM notes WHERE id=? AND spec='S'
                         AND xmlnote IS NOT NULL ORDER BY ord, noteid""", (srcabbr,)).fetchall()
    langs = c.execute("""SELECT ln.lgid AS lgid, ln.language AS language, ln.lgabbr AS lgabbr,
            ln.silcode AS silcode, g.grp AS subgroup, g.grpno AS grpno, g.grpid AS grpid,
            count(l.rn) AS n
        FROM languagenames ln LEFT JOIN lexicon l ON l.lgid=ln.lgid
        LEFT JOIN languagegroups g ON g.grpid=ln.grpid
        WHERE ln.srcabbr=? AND ln.language!='' AND ln.language NOT LIKE '*%' GROUP BY ln.lgid
        HAVING n>0 ORDER BY ln.language""", (srcabbr,)).fetchall()
    c.close()
    total = sum(l['n'] for l in langs)
    _au = (s['author'] or '').rstrip()
    if _au and not _au.endswith('.'): _au += '.'
    cite = ' '.join(x for x in (_au, f"{s['year']}." if s['year'] else '', s['title']) if x)
    meta = []
    if s['imprint']: meta.append(f'<span><b>imprint</b> {esc(s["imprint"])}</span>')
    meta.append(f'<span><b>{len(langs)}</b> languages</span>')
    meta.append(f'<span><b>{total:,}</b> forms</span>')

    def langrow(l):
        bits = [esc(x) for x in (l['grpno'], l['subgroup']) if x]
        grp = ' '.join(bits)
        grplink = (f'<a href="/group/{l["grpid"]}">{grp}</a>' if (l['grpid'] is not None and grp) else grp)
        iso = f' · ISO {iso_link(l["silcode"])}' if l['silcode'] else ''
        ab = f' <span class="lgab">{esc(l["lgabbr"])}</span>' if l['lgabbr'] else ''
        return (f'<div class="rfx"><span><a class="lang" href="/language/{canon_lgid(l["lgid"])}">'
                f'{esc(l["language"])}</a>{ab}</span><span class="subg">{grplink}{iso}</span>'
                f'<span class="src">{l["n"]:,} forms</span></div>')
    rows = ''.join(langrow(l) for l in langs)

    noteshtml = ''
    if notes:
        noteshtml = ('<section class="notes"><h3>Notes</h3>'
                     + ''.join(f'<div class="note-block">{render_note(r["xmlnote"])}</div>' for r in notes)
                     + '</section>')
    citehtml = f'<div class="pg" style="font-variant:normal;font-size:16px;color:var(--soft);letter-spacing:0">{esc(cite)}</div>' if cite else ''

    # copy-ready "Cite this source" apparatus (parallels the etymon page; wires the previously
    # orphaned .citebox CSS). Access date is a fill-in blank, like the etymon citebox (static site).
    src_url = f"{CITE_BASE}/source/{s['srcabbr']}"
    cite_full = cite
    if s['imprint']:
        sep = '' if cite_full.rstrip().endswith('.') else '.'   # avoid "Title.. Imprint"
        cite_full = (cite_full.rstrip() + sep + ' ' + s['imprint']) if cite_full else s['imprint']
    cite_full = cite_full or (s['citation'] or s['srcabbr'])
    cite_as = f"{cite_full} — via STEDT, {src_url} (accessed [ACCESSED])."
    # BibTeX for the source, parallel to the etymon citebox so both cite-boxes offer it.
    # imprint is free text (series/publisher/place), so keep it in note rather than mis-splitting it.
    bibkey = 'stedt-src-' + re.sub(r'[^A-Za-z0-9]+', '-', s['srcabbr'] or 'source').strip('-')
    bib_lines = ['@misc{' + bibkey + ',']
    if s['author']: bib_lines.append('  author = {' + s['author'] + '},')
    if s['title']:  bib_lines.append('  title  = {{' + s['title'] + '}},')
    if s['year']:   bib_lines.append('  year   = {' + str(s['year']) + '},')
    _note = '; '.join(x for x in (s['imprint'],
        'Accessed via STEDT (Sino-Tibetan Etymological Dictionary and Thesaurus) v1.0, source '
        + (s['srcabbr'] or '')) if x)
    bib_lines.append('  note   = {' + _note + '},')
    bib_lines.append('  url    = {' + src_url + '}')
    bib_lines.append('}')
    src_bib = '\n'.join(bib_lines)
    copy_js = ("<script>(function(){var D=new Date().toISOString().slice(0,10);"
               "document.querySelectorAll('.adate').forEach(function(e){e.textContent=D;});"
               "document.querySelectorAll('.copybtn').forEach(function(b){b.addEventListener('click',function(){"
               "navigator.clipboard.writeText((b.dataset.cite||'').replace(/\\[ACCESSED\\]/g,D));"
               "b.textContent='Copied';});});})();</script>")
    apparatus = f"""
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
    </section>{copy_js}"""
    body = f"""
    <div class="ety-head">
      <div class="plg">Source · {esc(s['srcabbr'])}</div>
      <div class="pagetitle">{esc(s['citation'] or s['srcabbr'])}</div>
      {citehtml}
      <div class="crumbs"><a href="/sources">Sources</a> &nbsp;›&nbsp; {esc(s['srcabbr'])}</div>
      <div class="metabar">{''.join(meta)}</div>
    </div>
    {noteshtml}
    <section class="reflexes"><h3>Languages in this source</h3>{rows}</section>
    {apparatus}"""
    return page(s['citation'] or s['srcabbr'], body, nav="sources")

def group(grpid):
    c = con()
    g = c.execute("SELECT * FROM languagegroups WHERE grpid=?", (grpid,)).fetchone()
    if not g:
        c.close(); return page("Not found", "<p>No such group.</p>")
    grpno = g['grpno']
    lin = group_lineage(c, grpno)
    depth = str(grpno).count('.') if grpno is not None else 0
    children = c.execute("""SELECT grpid, grpno, grp, plg FROM languagegroups
        WHERE grpno LIKE ? AND (length(grpno)-length(replace(grpno,'.','')))=?
        ORDER BY grpno""", (str(grpno) + '.%', depth + 1)).fetchall() if grpno is not None else []
    childinfo = []
    for ch in children:
        # count canonical member lects (distinct non-proto name == one lect within a grpid),
        # not raw language×source rows, so the tally matches the subgroup's own page header
        nl = c.execute("""SELECT count(DISTINCT ln.language) FROM languagenames ln
            JOIN lexicon l ON l.lgid=ln.lgid
            WHERE ln.grpid=? AND ln.language NOT LIKE '*%'""", (ch['grpid'],)).fetchone()[0]
        childinfo.append((ch, nl))
    # member lects directly attested at this node: collapse the per-source lgids of one lect onto its
    # canonical page (summing forms, merging sources), and drop proto-forms — they are this group's own
    # reconstruction (the plg + Reconstructions section), not member languages.
    langrows = c.execute("""SELECT ln.lgid AS lgid, ln.language AS language, ln.lgabbr AS lgabbr,
            ln.silcode AS silcode, ln.srcabbr AS srcabbr, sb.citation AS citation, count(l.rn) AS n
        FROM languagenames ln LEFT JOIN srcbib sb ON sb.srcabbr=ln.srcabbr
        JOIN lexicon l ON l.lgid=ln.lgid
        WHERE ln.grpid=? AND ln.language NOT LIKE '*%'
        GROUP BY ln.lgid HAVING n>0""", (grpid,)).fetchall()
    canon_of = canonical_languages()[0]
    lects = {}
    for r in langrows:
        cid = canon_of.get(r['lgid'], r['lgid'])
        d = lects.get(cid)
        if d is None:
            d = lects[cid] = {'lgid': cid, 'language': r['language'], 'lgabbr': r['lgabbr'],
                              'silcode': r['silcode'], 'n': 0, 'srcs': {}}
        d['n'] += r['n']
        if not d['silcode'] and r['silcode']: d['silcode'] = r['silcode']
        if r['srcabbr']: d['srcs'].setdefault(r['srcabbr'], r['citation'])
    langs = sorted(lects.values(), key=lambda d: (d['language'] or '').lower())
    recons = c.execute("""SELECT e.tag AS tag, e.protoform AS protoform, e.protogloss AS protogloss
        FROM etyma e WHERE e.grpid=? AND coalesce(upper(e.status),'')!='DELETE'
        ORDER BY e.sequence, e.protogloss""", (grpid,)).fetchall()
    rcounts = reflex_counts(c, [r['tag'] for r in recons])
    # the complete genetic tree, so every group page offers one-click cross-branch navigation
    alltree = c.execute(
        "SELECT grpid, grpno, grp FROM languagegroups WHERE grpid IS NOT NULL AND grpno IS NOT NULL").fetchall()
    c.close()

    plg = g['plg'] or ''
    head = (f'<span class="grpno">{esc(grpno)}</span>' if grpno else '') + esc(g['grp'] or '—')
    plg_html = f' <span class="plg2">({esc(plg)})</span>' if plg else ''

    def treerow(t):
        depth = str(t['grpno']).count('.')
        lab = f'<span class="grpno">{esc(t["grpno"])}</span>{esc(t["grp"] or "")}'
        inner = (f'<span class="here">{lab}</span>' if t['grpid'] == grpid
                 else f'<a href="/group/{t["grpid"]}">{lab}</a>')
        return f'<div style="padding-left:{depth*16}px">{inner}</div>'
    tree = ''.join(treerow(t) for t in sorted(alltree, key=lambda t: natkey(t['grpno'])))
    treehtml = (f'<details class="seg" open><summary>Family tree<span class="c">{len(alltree)} groups</span></summary>'
                f'<div class="lgtree">{tree}</div></details>')
    crumb_links = ['<a href="/languages">Languages</a>'] + \
                  [f'<a href="/group/{gg["grpid"]}">{(esc(gg["grpno"]) + " ") if gg["grpno"] else ""}{esc(gg["grp"])}</a>' for gg in lin]
    meta = []
    if langs: meta.append(f'<span><b>{len(langs)}</b> languages</span>')
    if recons: meta.append(f'<span><b>{len(recons):,}</b> reconstructions</span>')

    def subitem(ch, nl):
        code = f'<span class="grpno">{esc(ch["grpno"])}</span>' if ch['grpno'] else ''
        lab = code + esc(ch['grp']) + (f' <span class="plg2">({esc(ch["plg"])})</span>' if ch['plg'] else '')
        return (f'<li><a class="row" href="/group/{ch["grpid"]}">'
                f'<span class="ti">{lab}</span><span class="ct">{nl} languages</span></a></li>')
    subhtml = ('<section class="thes grpsec"><h3>Subgroups</h3><ul>'
               + ''.join(subitem(ch, nl) for ch, nl in childinfo) + '</ul></section>') if childinfo else ''

    def langrow(l):
        ab = f' <span class="lgab">{esc(l["lgabbr"])}</span>' if l['lgabbr'] else ''
        mid = []
        srcs = list(l['srcs'].items())
        if len(srcs) == 1:
            sab, cit = srcs[0]
            mid.append(f'<a href="/source/{esc(sab)}">{esc(cit or sab)}</a>')
        elif len(srcs) > 1:
            mid.append(f'{len(srcs)} sources')
        if l['silcode']:
            mid.append('ISO ' + iso_link(l['silcode']))
        # same row primitive as the Reconstructions list below (and as language/reconstruction rows
        # on the search page), so the group page's two entity lists share one rhythm
        return (f'<div class="ety-hit"><span class="rf"><a href="/language/{l["lgid"]}">{esc(l["language"])}</a>{ab}</span>'
                f'<span class="gl2">{" · ".join(mid)}</span>'
                f'<span class="tagn">{l["n"]:,} forms</span></div>')
    langhtml = (f'<div class="ety-list grpsec"><h3>Languages<span class="cnt">{len(langs)}</span></h3>'
                + ''.join(langrow(l) for l in langs) + '</div>') if langs else ''

    reconhtml = ''
    if recons:
        items = ''.join(
            f'<div class="ety-hit"><a href="/etymon/{r["tag"]}" class="pf2 lat">{esc(alt(r["protoform"]))}</a>'
            f'<span class="pg2">{esc(r["protogloss"])}</span>'
            f'<span class="tagn">{esc(plg)} #{r["tag"]}{rcount_txt(rcounts.get(r["tag"], 0))}</span></div>' for r in recons)
        reconhtml = (f'<div class="ety-list grpsec"><h3>Reconstructions<span class="cnt">{len(recons)}</span>'
                     f'</h3>{items}</div>')

    body = f"""
    <div class="ety-head">
      <div class="plg">Language group</div>
      <div class="pagetitle">{head}{plg_html}</div>
      <div class="crumbs">{' &nbsp;›&nbsp; '.join(crumb_links)}</div>
      <div class="metabar">{''.join(meta)}</div>
    </div>
    {treehtml}
    {subhtml}
    {langhtml}
    {reconhtml}"""
    return page(g['grp'] or "Group", body, nav="languages")
