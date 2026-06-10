#!/usr/bin/env python3
"""Render library for the /_legacy/ rootcanal clone — pixel-faithful static pages.

Reproduces rootcanal's PUBLIC (logged-out) Template-Toolkit output as HTML from stedt.sqlite, loading
rootcanal's verbatim CSS/JS (copied by stedt.legacy.build_site). The dynamic behavior (search, sortable tables,
elink popups, autosuggest) is supplied at runtime by src/legacy-shim.js, which intercepts the original
AJAX endpoints and answers them from legacy.sqlite3 in WASM. Every page is noindex'd.

`chrome()` mirrors web/header.tt's guest branch; per-page functions mirror splash.tt / index.tt /
etymon.tt. self_base/self_url/baseRef are set to the legacy base (BASE), so all asset/link/AJAX URLs
stay inside the subtree. Reuses render.con() for the DB connection.
"""

import os
import html as _html

from stedt import render  # reuse con() + helpers; same stedt.sqlite schema

BASE = os.environ.get("STEDT_LEGACY_BASE", "/_legacy").rstrip("/")
VER = os.environ.get("STEDT_LEGACY_VER", "")


def esc(s):
    return _html.escape("" if s is None else str(s))


def _lnote(xml, notetype=None):
    """The renderer's note XML→HTML, with etymon xref links rebased into the legacy subtree
    (render_note emits root-absolute /etymon/N, which would 404 under /_legacy/). Source-quoted
    notes (notetype 'O') get the original's '[Source note]' prefix inside the first paragraph."""
    h = render.render_note(xml).replace('href="/etymon/', f'href="{BASE}/etymon/')
    lab = render.note_label(notetype)
    return h.replace('<p class="np">', f'<p class="np">{lab}', 1) if lab else h


# ---------------------------------------------------------------------------------- shared chrome
def chrome(title, body, vert_tog=False, cognates=None, extra_scripts=""):
    """web/header.tt, guest branch: external rootcanal CSS/JS + the legacy-shim module (first, so its
    XHR patch is installed before any AJAX), noindex meta, guest header (login/tools forms removed)."""
    cog = ""
    if cognates:
        cog = (
            '<style type="text/css">'
            + "".join(f".r{n} {{ background-color:yellow; }} " for n in cognates)
            + "".join(f".u{n} {{ background-color:#6FF; }} " for n in cognates)
            + "</style>"
        )
    tog = ""
    if vert_tog:
        tog = (
            f'<img id="spinner" src="{BASE}/img/spinner.gif" style="display:none;">&nbsp;'
            f'<a href="#" onclick="return vert_tog()"><img title="Rotate View" '
            f'src="{BASE}/img/toggle.png" alt="toggle" id="tog-img" border="0"></a>&nbsp;'
        )
    return f"""﻿<!DOCTYPE html>
<html lang="en">
<head>
\t<meta charset="utf-8">
\t<meta name="robots" content="noindex,nofollow">
\t<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ctext x='8' y='20.5' text-anchor='middle' font-family='Georgia,serif' font-size='26' fill='%239c2b25'%3E*%3C/text%3E%3C/svg%3E">
\t<title>{esc(title)}</title>
\t<script>window.STEDT_BASE="{BASE}";window.STEDT_LEGACY_DB_VERSION="{VER}";</script>
\t<script type="module" src="{BASE}/assets/legacy-shim.js"></script>
\t<link rel="stylesheet" href="{BASE}/styles/rootcanal.css">
\t<link rel="stylesheet" href="{BASE}/styles/autoSuggest.css">
\t<link rel="stylesheet" href="{BASE}/styles/opentip.css">
\t<style>.recon::before{{content:"*"}}</style><!-- SYNC(recon-star) ↔ static/site.css .recon::before:
\t  render_note strips the literal leading '*' from <reconstruction> (the main UI's CSS re-supplies
\t  it); vendored rootcanal.css has no such rule, so the legacy shell must add the twin or every
\t  note reconstruction renders starless here. Also stars the xref-injected recon labels. -->
\t{cog}
\t<script src="{BASE}/scriptaculous/lib/prototype.js"></script>
\t<script src="{BASE}/scriptaculous/src/scriptaculous.js?load=effects,dragdrop,controls"></script>
\t<script src="{BASE}/js/opentip.js"></script>
\t<script src="{BASE}/js/excanvas.js"></script>
\t<script src="{BASE}/js/tablekit.js"></script>
\t<script src="{BASE}/js/jquery-1.8.0.js"></script>
\t<script src="{BASE}/js/jquery.autoSuggest.js"></script>
</head>
<body>
<div id="header">
<span class="right">
{tog}<script>
$.noConflict();
var baseRef = '{BASE}/';
var stedtuserprivs = 2;   // the public 'guest' account (privs=2) — shows rn/analysis/semkey columns
</script>
<a href="https://stedt.berkeley.edu/documentation" target="_blank">help</a>
<script src="{BASE}/js/stedtconfig.js"></script>
<script>
// guest can't edit, so repoint the would-be edit links (dead on static) to read-only targets:
// semkey -> its thesaurus chapter (the meaningful node) instead of /edit/glosswords.
setup.lexicon['lexicon.semkey'].transform = function (v, key, rec, n) {{
  if (!v) return v;
  var t = rec[n + 1] ? ' title="' + rec[n + 1].replace(/&/g, '&amp;') + '"' : '';
  return '<a href="' + baseRef + 'chap/' + v + '" target="stedt_chapters"' + t + '>' + v + '</a>';
}};
setup.etyma['etyma.semkey'].transform = function (v) {{
  return v ? '<a href="' + baseRef + 'chap/' + v + '" target="stedt_chapters">' + v + '</a>' : v;
}};
</script>
</span>
<a href="{BASE}/" title="Search Home"><img src="{BASE}/img/splashy32x32.gif" alt="STEDT Logo" width="32" height="32" class="left" border=0></a>
<b>{esc(title)}</b>
<hr style="clear:both; margin-left:45px">
</div>
{body}
{extra_scripts}
</body>
</html>"""


# ------------------------------------------------------------------------------------ splash page
def legacy_splash():
    """web/splash.tt, guest branch: logo + the two-field simple search (gloss + autosuggested language)
    posting to {BASE}/gnis, with the show/hide examples. Dead guest-tools/login forms removed."""
    body = f"""<div id="splash">
<center>
<br>
<a href="https://stedt.berkeley.edu/" title="STEDT Home Page">
<img src="{BASE}/img/stedt_bw.jpg" alt="STEDT Logo" border="0" width="447" height="128"></a>
<br><br><br>
<form id="simple_search" method="get" action="{BASE}/gnis">
<table>
<tr>
\t<td></td>
\t<th id="gloss_header"><span style="float: left">gloss</span><span id="gloss_help" style="float: right; cursor: help;">?&nbsp;</span></th>
\t<th><span style="float: left">language</span><span id="lg_help" style="float: right; cursor: help;">?&nbsp;</span></th>
\t<td></td>
</tr>
<tr>
\t<td></td>
\t<td><input type="text" name="t" id="simple_searchgloss" size="25" maxlength="128" style="height:32px"></td>
\t<td><input type="text" name="lg" id="simple_searchlg" size="25" maxlength="96"></td>
\t<td valign="middle"><input type="submit" title="Click to search!" name="search" value="Search">
\t<input type="button" title="Click to clear the search form" name="clear" value="Clear" onclick="clear_splash()"></td>
</tr>
<tr>
\t<td><a href="#" onclick="Effect.multiple(['example1', 'example2', 'example3'], function(el){{Effect.toggle(el,'appear',{{ duration: 0.25 }});}}); return false;">Show/hide examples</a>&nbsp;</td>
\t<td colspan=2></td>
\t<td><a href="{BASE}/gnis">More search options...</a></td>
</tr>
<tr id="example1" style="display: none; text-align: left;">
\t<td><i>gloss only:</i></td>
\t<td><b>dog</b></td>
\t<td>-</td>
\t<td><a href="#" onclick="clear_splash();$('simple_searchgloss').value='dog';return false">Try it!</a></td>
</tr>
<tr id="example2" style="display:none; text-align: left;">
\t<td><i>language only:</i></td>
\t<td>-</td>
\t<td>Paangkhua</td>
\t<td><a href="#" onclick="clear_splash();$('lg-auto').value='Paangkhua';return false">Try it!</a></td>
</tr>
<tr id="example3" style="display:none; text-align: left;">
\t<td><i>gloss &amp; lang:</i></td>
\t<td><b>hit</b></td>
\t<td>Lotha</td>
\t<td><a href="#" onclick="clear_splash();$('simple_searchgloss').value='hit';$('lg-auto').value='Lotha';return false">Try it!</a></td>
</tr>
</table>
</form>
<div style="height:10ex"></div>
<div class="footer">
<a href="{BASE}/group/1" target="stedt_grps">Language Groups Browser</a>
| <a href="{BASE}/source" target="_blank">Source Bibliography</a>
| <a href="{BASE}/chapters" target="_blank">Chapter Browser</a>
<hr>
<small>
<a href="https://stedt.berkeley.edu/">STEDT Home Page</a> |
<a href="https://stedt.berkeley.edu/contact" target="_blank">Contact Us</a>
</small>
</div>
</center>
</div>"""
    scripts = f"""<script>
$('simple_searchgloss').focus();
$('gloss_help').addTip('One or more English words. Multiple glosses can be entered, separated by commas, e.g. <i>frog, snail</i>', 'Gloss search field', {{className:'standard', delay: 0.3, hideTrigger: 'closeButton', fixed: true, target: 'gloss_header', stem: true, targetJoint: ['left','top'], tipJoint: ['right','bottom'], stemSize: 20, autoOffset: true, offset: [17,7]}});
$('lg_help').addTip('Values are from the "standardized" list of language names; type a few characters and the "autosuggest" feature will help you narrow down your selection.', 'Language search field', {{className:'standard', delay: 0.3, hideTrigger: 'closeButton', fixed: true, target: true, stem: true, targetJoint: ['right','top'], tipJoint: ['left','bottom']}});
$('simple_search').observe('submit',function(e){{e.stop();
var s = Form.serializeElements(this.select('input:not(:submit,:button,:reset)','select').findAll(Form.Element.getValue));
if (s) document.location = '{BASE}/gnis?' + s;
else if (!$('example1').visible()) Effect.multiple(['example1', 'example2', 'example3'], function(el){{Effect.toggle(el,'appear',{{ duration: 0.25 }});}});
}});
jQuery('input[name=lg]').autoSuggest('{BASE}/autosuggest/lgs',{{
\tasHtmlID:"lg-auto", startText:"", selectedItemProp:"s", selectedValuesProp:"v", searchObjProps:"s"
}});
function clear_splash() {{
\t$('simple_search').reset();
\tif ($('as-values-lg-auto')) $('as-values-lg-auto').value='';
\tjQuery('.as-selection-item').remove();
}}
</script>"""
    return chrome("STEDT Database", body, extra_scripts=scripts)


# -------------------------------------------------------------------------------- gnis search page
def _grp_options():
    c = render.con()
    rows = c.execute("SELECT grpno, grp FROM languagegroups ORDER BY grp0,grp1,grp2,grp3,grp4").fetchall()
    c.close()
    return "".join(f'<option value="{esc(r[0])}">{esc(r[0])} {esc(r[1])}</option>' for r in rows)


def legacy_gnis():
    """web/index.tt, guest branch: the dual resizable Etyma/Lexicon panes with empty result tables.
    On load (or with ?t=/?lg= from the splash), a small bootstrap fires the two searches via the same
    do_search path simplesearch.js uses — which the shim answers from WASM."""
    body = f"""<div id="etyma" class="vert">
<div class="panetitle">Etyma</div>
<div align="center">
<form id="etyma_search" method="post">
<table>
<tr><th>proto-form</th><th>proto-gloss</th></tr>
<tr><td><input type="text" title="Type a proto-form" name="f" id="etyma_searchform" size="15" maxlength="128"></td>
<td><input name="s" type="text" title="Type an English word" size="20" id="etyma_searchgloss" maxlength="128"></td>
<td><input name="btn" type="submit" value="Search"></td></tr></table>
</form>
</div>
<div id="etyma_status"></div>
<div id="etyma_results"></div>
<div id="addform"></div>
<div id="debug"></div>
</div>

<div id="dragger" class="vert"></div>

<div id="lexicon" class="vert">
<div class="panetitle"><b>Lexicon</b></div>
<div align="center">
<form id="lexicon_search" method="post">
<table>
<tr><th>form</th><th>gloss</th><th>language</th><th>language group</th></tr>
<tr><td><input type="text" name="f" title="Type a linguistic form" id="lexicon_searchform" size="24" maxlength="128"></td>
<td><input name="s" title="Type an English word" type="text" size="24" maxlength="128" id="lexicon_searchgloss"></td>
<td><input name="lg" title="Type a language name" type="text" size="32" maxlength="96" id="lexicon_searchlg"></td>
<td><select name="lggrp" title="Choose a subgroup" id="lexicon_searchlggrp">
<option selected="selected" value=""></option>
{_grp_options()}
</select>
</td>
<td><input name="btn" type="submit" value="Search"><input type="button" name="clear" value="Clear" onclick="this.form.reset(); if($('as-values-lg-auto'))$('as-values-lg-auto').value='';jQuery('.as-selection-item').remove()"></td></tr></table>
</form>
</div>
<div id="lexicon_status"></div>
<div id="lexicon_results"></div>
</div>

<script src="{BASE}/js/simplesearch.js"></script>
<script>
// Static equivalent of the server-side combo(): on load, feed the splash's params (t=gloss, f=form,
// lg/lggrp) to BOTH panes and fire each search via the same path do_search uses — answered by the
// shim from WASM. (Runs after simplesearch.js's dom:loaded init, which sets up autosuggest + the
// per-pane re-search forms.)
document.observe("dom:loaded", function () {{
  var q = document.URL.toQueryParams();
  function un(v) {{ return (v || '').replace(/\\+/g, ' '); }}
  function run(tbl) {{
    var p = {{ tbl: tbl }};
    if (q.t) p.s = un(q.t);                         // gloss / proto-gloss
    if (q.f) p.f = un(q.f);                          // form / proto-form (or tag)
    if (tbl === 'lexicon') {{
      if (q.lg) p.lg = un(q.lg);
      if (q['as_values_lg-auto']) p['as_values_lg-auto'] = q['as_values_lg-auto'];
      if (q.lggrp) p.lggrp = q.lggrp;
    }}
    new Ajax.Request(baseRef + 'search/ajax', {{ method: 'get', parameters: p,
      onSuccess: ajax_make_table,
      onFailure: function (t) {{ $(tbl + '_status').update('Error: ' + t.responseText); }} }});
  }}
  // mirror index.tt: the etyma gloss box shows the incoming 't'
  if (q.t && $('etyma_searchgloss')) $('etyma_searchgloss').value = un(q.t);
  if (q.t || q.lg || q.f || q['as_values_lg-auto'] || q.lggrp) {{ run('etyma'); run('lexicon'); }}
}});
</script>"""
    return chrome("STEDT Database", body, vert_tog=True)


# ------------------------------------------------------------------------------- etymon page
import json as _json

ETYMON_FIELDS = [
    "lexicon.rn",
    "analysis",
    "languagenames.lgid",
    "lexicon.reflex",
    "lexicon.gloss",
    "lexicon.gfn",
    "languagenames.language",
    "languagegroups.grpid",
    "languagegroups.grpno",
    "languagegroups.grp",
    "languagegroups.genetic",
    "citation",
    "languagenames.srcabbr",
    "lexicon.srcid",
    "notes.rn",
]


def _alt_stars(pf):
    """etymon.tt: asterisk each alternant (after ⪤ / OR / ~ / =) then prefix '*'."""
    for d in ("⪤", "OR", "~", " ="):
        pf = pf.replace(d + " ", d + " *")
    return "*" + pf


def _breadcrumbs(c, chapter):
    """Ancestor chapters of a chapter semkey (e.g. 2.1.11 -> 2.0, 2.1, 2.1.11), linking to /chap/."""
    if not chapter:
        return []
    parts = str(chapter).split(".")
    cands = [parts[0] + ".0"] + [".".join(parts[:i]) for i in range(2, len(parts) + 1)] + [str(chapter)]
    seen, out = set(), []
    for k in cands:
        if k in seen:
            continue
        seen.add(k)
        r = c.execute("SELECT semkey, chaptertitle FROM chapters WHERE semkey=?", (k,)).fetchone()
        if r:
            out.append((r["semkey"], r["chaptertitle"]))
    out.sort(key=lambda kv: (len(str(kv[0]).split(".")), str(kv[0])))
    return out


def legacy_etymon(tag):
    c = render.con()
    e = c.execute(
        """SELECT e.tag, e.chapter, e.sequence, e.protoform, e.protogloss, e.public, g.plg
                     FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
                     WHERE e.tag=? AND coalesce(upper(e.status),'')!='DELETE'""",
        (tag,),
    ).fetchone()
    if not e:
        c.close()
        raise ValueError(f"no etymon #{tag}")
    plg, pf, pg = e["plg"] or "", e["protoform"] or "", e["protogloss"] or ""

    # allofams: same chapter & same integer sequence (FLOOR), non-DELETE
    allo = c.execute(
        """SELECT tag, sequence, protoform, protogloss FROM etyma
                        WHERE chapter=? AND sequence!='0' AND sequence!='0.0'
                          AND CAST(sequence AS INTEGER)=CAST(? AS INTEGER)
                          AND coalesce(upper(status),'')!='DELETE' ORDER BY sequence""",
        (e["chapter"], e["sequence"]),
    ).fetchall()

    # mesoroots
    meso = c.execute(
        """SELECT m.grpid, g.grpno, g.grp, g.plg, m.form, m.gloss, m.variant, g.genetic
                        FROM mesoroots m LEFT JOIN languagegroups g ON g.grpid=m.grpid
                        WHERE m.tag=? ORDER BY g.grp0,g.grp1,g.grp2,g.grp3,g.grp4, m.variant""",
        (tag,),
    ).fetchall()
    meso = [dict(m) for m in meso]

    # reflexes (Tags.pm::etymon, guest 15 cols); analysis computed in Python (version-safe)
    recs = c.execute(
        """SELECT l.rn, ln.lgid, l.reflex, l.gloss, l.gfn, ln.language, g.grpid, g.grpno,
                          g.grp, g.genetic, sb.citation, ln.srcabbr, l.srcid,
                          (SELECT COUNT(*) FROM notes WHERE notes.rn=l.rn) AS num_notes
                        FROM lexicon l JOIN lx_et_hash h ON h.rn=l.rn AND h.tag=?
                          LEFT JOIN languagenames ln ON ln.lgid=l.lgid
                          LEFT JOIN languagegroups g ON g.grpid=ln.grpid
                          LEFT JOIN srcbib sb ON sb.srcabbr=ln.srcabbr
                        WHERE coalesce(l.status,'') NOT IN ('HIDE','DELETED')
                        GROUP BY l.rn
                        ORDER BY g.grp0,g.grp1,g.grp2,g.grp3,g.grp4, ln.lgsort, l.reflex COLLATE unaccent, ln.srcabbr, l.srcid""",
        (tag,),
    ).fetchall()
    rns = [r["rn"] for r in recs]
    ana = {}
    if rns:
        qm = ",".join("?" * len(rns))
        for rn, ts in c.execute(
            f"SELECT rn, tag_str FROM lx_et_hash WHERE rn IN ({qm}) AND tag_str IS NOT NULL " f"ORDER BY rn, ind", rns
        ):
            ana.setdefault(rn, []).append(str(ts))

    def cell(v):
        return f"<td>{esc(v)}</td>"

    # reflex-level notes (spec='L', non-internal) become numbered footnotes, sequentially in reflex
    # order; the notes.rn column carries the footnote NUMBERS (etymon.js turns them into ^n links —
    # emitting the raw count there made it render a bogus #foot<count> link).
    lex_notes = {}
    if rns:
        qm = ",".join("?" * len(rns))
        for rn, xml, nt in c.execute(
            f"SELECT rn, xmlnote, notetype FROM notes WHERE rn IN ({qm}) AND spec='L' "
            f"AND notetype!='I' AND xmlnote IS NOT NULL ORDER BY rn, ord, noteid",
            rns,
        ):
            lex_notes.setdefault(rn, []).append((nt, xml))

    # subgroup-anchored etymon notes (notes.id = grpid): etymon.js places each as a footnote
    # marker on the first band at-or-under its grpno (it shift()s a sorted list while streaming
    # bands), so emit them sorted by grpno with page-order footnote numbers interleaved below.
    sg_pending = [
        (gr["grpno"], r["notetype"], r["xmlnote"])
        for r in c.execute(
            "SELECT id, notetype, xmlnote FROM notes WHERE tag=? AND spec='E' AND coalesce(id,'')!='' "
            "AND notetype!='I' AND xmlnote IS NOT NULL ORDER BY ord, noteid",
            (tag,),
        )
        if (gr := c.execute("SELECT grpno FROM languagegroups WHERE grpid=?", (r["id"],)).fetchone()) and gr["grpno"]
    ]
    sg_pending.sort(key=lambda t: t[0])
    subgroupnotes = []

    footnotes = []  # (num, html)
    rows_html = ""
    for r in recs:
        while sg_pending and r["grpno"] and sg_pending[0][0] <= r["grpno"]:
            grpno, nt, xml = sg_pending.pop(0)
            footnotes.append((len(footnotes) + 1, _lnote(xml, nt)))
            subgroupnotes.append({"grpno": grpno, "ind": footnotes[-1][0]})
        nums = []
        for nt, xml in lex_notes.get(r["rn"], []):
            footnotes.append((len(footnotes) + 1, _lnote(xml, nt)))
            nums.append(footnotes[-1][0])
        notes_col = " ".join(str(x) for x in nums) if nums else "0"
        vals = [
            r["rn"],
            ",".join(ana.get(r["rn"], [])),
            r["lgid"],
            r["reflex"],
            r["gloss"],
            r["gfn"],
            r["language"],
            r["grpid"],
            r["grpno"],
            r["grp"],
            r["genetic"],
            r["citation"],
            r["srcabbr"],
            r["srcid"],
            notes_col,
        ]
        rows_html += "<tr>" + "".join(cell(v) for v in vals) + "</tr>\n"
    for grpno, nt, xml in sg_pending:  # anchors with no band on this page: still footnoted at the end
        footnotes.append((len(footnotes) + 1, _lnote(xml, nt)))
        subgroupnotes.append({"grpno": grpno, "ind": footnotes[-1][0]})

    # notes (spec=E, not comparanda 'F', not internal 'I', not subgroup-anchored) + comparanda ('F')
    notes = c.execute(
        """SELECT xmlnote FROM notes WHERE tag=? AND spec='E' AND coalesce(id,'')=''
                         AND notetype NOT IN ('F','I') AND xmlnote IS NOT NULL ORDER BY ord, noteid""",
        (tag,),
    ).fetchall()
    comp = c.execute(
        """SELECT xmlnote FROM notes WHERE tag=? AND notetype='F'
                        AND xmlnote IS NOT NULL ORDER BY ord, noteid""",
        (tag,),
    ).fetchall()
    all_grps = {
        r["grpno"]: {
            "grpid": r["grpid"],
            "grpno": r["grpno"],
            "grp": r["grp"],
            "genetic": str(r["genetic"]) if r["genetic"] is not None else "0",
        }
        for r in c.execute("SELECT grpid, grpno, grp, genetic FROM languagegroups")
    }
    crumbs = _breadcrumbs(c, e["chapter"])
    c.close()

    # ---- assemble markup (etymon.tt guest branch) ----
    allobox = ""
    if len(allo) > 1:
        items = "".join(
            (
                f'<li><b>{esc(_fmt_seq(a["sequence"]))} #{a["tag"]} *{esc(a["protoform"])} {esc(a["protogloss"])}</b></li>'
                if a["tag"] == tag
                else f'<li><a href="{BASE}/etymon/{a["tag"]}">{esc(_fmt_seq(a["sequence"]))} #{a["tag"]} '
                f'*{esc(a["protoform"])} {esc(a["protogloss"])}</a></li>'
            )
            for a in allo
        )
        allobox = f'<div class="right" id="allofambox"><b>Allofams:</b><ul>{items}</ul></div>'

    crumbs_html = ""
    for i, (sk, ti) in enumerate(crumbs):
        if i == len(crumbs) - 1:
            crumbs_html += f'<a href="{BASE}/chap/{esc(sk)}">{esc(sk)} <b>{esc(ti)}</b></a>'
        else:
            crumbs_html += f"{esc(sk)} <b>{esc(ti)}</b> &gt; "

    prov = (
        ""
        if e["public"]
        else ' <span id="prov_heading" style="color:red; cursor:help; font-size:medium">(provisional)</span>'
    )
    heading = (
        f'<table><tr><td style="padding: 10px;">'
        f"<h1>#{tag} {esc(plg)} {esc(_alt_stars(pf))} {esc(pg)}{prov}</h1></td></tr></table>"
    )

    meso_html = ""
    if meso:
        lis = "".join(
            f'<li><a href="#{esc(m["grpno"])}">{esc(m["plg"])} *{esc(m["form"])} {esc(m["gloss"])}</a></li>'
            for m in meso
        )
        meso_html = f'Reconstructed mesoroots below:\n<ul class="mesolist">{lis}</ul>'

    notes_html = "".join(f'<div class="notepreview">{_lnote(n["xmlnote"])}</div>' for n in notes)

    table_html = ""
    if recs:
        ths = "".join(f'<th id="{f}">{esc(f.split(".")[-1])}</th>' for f in ETYMON_FIELDS)
        table_html = (
            f'{len(recs)} records <span class="r{tag}">tagged by <b>stedt</b></span> under this etymon.\n'
            f'<table id="lexicon1" tag="{tag}" class="hangindent">\n'
            f"<thead><tr>{ths}</tr></thead>\n<tbody>\n{rows_html}</tbody></table>"
        )

    comp_html = ""
    if comp:
        label = "Chinese comparand" + ("um" if len(comp) == 1 else "a")
        comp_html = f"<h2>{label}</h2>" + "".join(_lnote(n["xmlnote"]) for n in comp)

    # reflex-note endnotes (rootcanal lists these at the bottom; the notes.rn column links to them)
    footnotes_html = "".join(
        f'<div class="footnote" id="foot{num}"><a href="#toof{num}" class="left">^ {num}.</a> '
        f'<div class="notepreview">{html}</div></div>\n'
        for num, html in footnotes
    )

    body = (
        f"{allobox}\n<p>{crumbs_html}</p>\n{heading}\n{meso_html}\n{notes_html}\n{table_html}\n{comp_html}\n"
        f"<br>\n{footnotes_html}"
    )

    scripts = f"""<script>
var footnote_counter = {len(footnotes)};
skipped_roots[{tag}] = true;
num_tables = 2;
var stedt_other_username = '';
var uid2 = '';
var mesoroots = {_json.dumps(meso)};
var subgroupnotes = {_json.dumps(subgroupnotes)};
var all_subgroups = {_json.dumps(all_grps)};
</script>
<script src="{BASE}/js/etymon.js"></script>
<script src="{BASE}/js/notes.js"></script>"""
    return chrome(f"STEDT Etymon #{tag}", body, cognates=[tag], extra_scripts=scripts)


def _fmt_seq(s):
    """etymon.tt allofam sequence: integer -> int; .N -> letter (a..)."""
    try:
        f = float(s)
    except (TypeError, ValueError):
        return s or ""
    if f == int(f):
        return str(int(f))
    frac = str(s).split(".")[-1]
    return str(int(f)) + (chr(ord("a") - 1 + int(frac[0])) if frac and frac[0].isdigit() else "")


# ----------------------------------------------------------------------- source / group / chapter
# 16-col etyma result table (gnis/chapter format); num_recs/num_notes/num_comparanda via subqueries.
ETYMA16 = [
    "etyma.tag",
    "num_recs",
    "chapters.chaptertitle",
    "etyma.chapter",
    "etyma.sequence",
    "etyma.protoform",
    "etyma.protogloss",
    "etyma.grpid",
    "languagegroups.plg",
    "languagegroups.grpno",
    "etyma.notes",
    "num_notes",
    "num_comparanda",
    "etyma.status",
    "etyma.public",
    "users.username",
]
_ETYMA16_SELECT = """SELECT e.tag,
  (SELECT COUNT(DISTINCT rn) FROM lx_et_hash WHERE tag=e.tag) AS num_recs,
  ch.chaptertitle, e.chapter, e.sequence, e.protoform, e.protogloss, e.grpid, g.plg, g.grpno, e.notes,
  (SELECT COUNT(*) FROM notes WHERE tag=e.tag) AS num_notes,
  (SELECT COUNT(*) FROM notes WHERE tag=e.tag AND notetype='F') AS num_comparanda,
  e.status, e.public, ''
  FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid LEFT JOIN chapters ch ON ch.semkey=e.chapter"""


def _etyma_table(c, where, params, order):
    rows = c.execute(f"{_ETYMA16_SELECT} WHERE {where} ORDER BY {order}", params).fetchall()
    if not rows:
        return "", 0
    ths = "".join(f'<th id="{f}">{esc(f.split(".")[-1])}</th>' for f in ETYMA16)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(f"<td>{esc(v)}</td>" for v in r) + "</tr>\n"
    html = (
        f'<table id="etyma_resulttable" class="resizable hangindent" width="100%" '
        f'style="table-layout:fixed;">\n<thead><tr>{ths}</tr></thead>\n<tbody>\n{body}</tbody></table>'
    )
    return html, len(rows)


# ------------------------------------------------------------------------------------ source pages
def _period(s):
    s = s or ""
    return s + ("" if s.endswith((".", "?")) else ".")


def legacy_source(srcabbr):
    c = render.con()
    sb = c.execute("SELECT author, year, title, imprint FROM srcbib WHERE srcabbr=?", (srcabbr,)).fetchone()
    if not sb:
        c.close()
        raise ValueError(f"no source {srcabbr}")
    author, year, title, imprint = sb["author"] or "", sb["year"] or "", sb["title"] or "", sb["imprint"] or ""
    lgs = c.execute(
        """SELECT ln.silcode, ln.language, g.grpid, g.grpno, g.grp,
                         COUNT(l.rn) AS nrec, ln.lgid, ln.pi_page, ln.lgabbr
                       FROM languagenames ln LEFT JOIN languagegroups g ON g.grpid=ln.grpid
                         LEFT JOIN lexicon l ON l.lgid=ln.lgid
                       WHERE ln.srcabbr=? AND coalesce(ln.lgcode,0)!=0
                         AND coalesce(l.status,'') NOT IN ('HIDE','DELETED')
                       GROUP BY ln.lgid HAVING nrec>0 ORDER BY ln.lgcode, ln.language COLLATE unaccent""",
        (srcabbr,),
    ).fetchall()
    notes = c.execute(
        """SELECT xmlnote FROM notes WHERE spec='S' AND id=? AND notetype!='I'
                         AND xmlnote IS NOT NULL ORDER BY ord, noteid""",
        (srcabbr,),
    ).fetchall()
    c.close()

    cite = (
        f'<p align="center" style="width:50%">{esc(_period(author))} {esc(_period(year))} '
        f'<cite>{esc(title)}</cite>{"" if title.endswith((".", "?")) else "."}'
        f'{(" " + esc(_period(imprint))) if imprint else ""}\nAccessed via STEDT database '
        # an access-date blank, like the main site's citebox: the date belongs to the reader, and a
        # clock-baked date made 300 source pages nondeterministic under the snapshot harness
        f"<tt>&lt;https://larc-iu.github.io/stedt/&gt;</tt> on [date accessed].</p>"
    )
    notes_html = "".join(f'<p>{_lnote(n["xmlnote"])}</p>' for n in notes)
    # guest-available raw-data export (rootcanal's /sources/ddata); a static TSV written by build_legacy
    dl = (
        ""
        if srcabbr == "SIL-Nuosu"
        else f'<p><a href="{BASE}/sources/ddata/{esc(srcabbr)}.tsv">Download data for {esc(srcabbr)}</a></p>'
    )

    rows = ""
    for r in lgs:
        iso = (
            (
                f'<a href="http://www.ethnologue.com/show_language.asp?code={esc(r["silcode"])}" '
                f'target="stedt_ethnologue">{esc(r["silcode"])}</a>'
            )
            if r["silcode"]
            else "n/a"
        )
        pi = (
            (
                f'<a href="{BASE}/phon_inv.html?page={(r["pi_page"] or 0) + 26}" target="stedt_pi" '
                f'title="Namkung, ed. 1996">p.{r["pi_page"]}</a>'
            )
            if r["pi_page"]
            else ""
        )
        rows += (
            f"<tr>\n<td>{iso}</td>\n"
            f'<td><a href="{BASE}/group/{r["grpid"]}/{r["lgid"]}" target="stedt_grps">{esc(r["language"])}</a></td>\n'
            f'<td>{esc(r["lgabbr"])}</td>\n'
            f'<td>{esc(r["grpno"])} - <a href="{BASE}/group/{r["grpid"]}" target="stedt_grps">{esc(r["grp"])}</a></td>\n'
            f'<td><a href="{BASE}/gnis?lexicon.lgid={r["lgid"]}" target="stedt_sss">{r["nrec"]}</a></td>\n'
            f"<td>{pi}</td>\n</tr>\n"
        )

    body = f"""<p>Cite as follows:</p>
{cite}
{notes_html}
{dl}
<p>Languages in this source:</p>
<table class="hangindent">
<tr><th>ISO 639-3</th><th>Language Name</th><th title="Language name from source OR abbreviated name" style="cursor:help;">Short Lg Name</th><th>Group</th><th>num. of records</th><th title="from Namkung, ed. 1996 (STEDT Monograph #3)" style="cursor:help;">Phon. Inventory</th></tr>
{rows}</table>"""
    return chrome(f"STEDT Source: {author} {year}", body)


def legacy_all_sources():
    c = render.con()
    rows = c.execute("""SELECT sb.srcabbr, COUNT(DISTINCT ln.lgid) AS num_lgs, COUNT(l.rn) AS num_recs,
                          sb.citation, sb.author, sb.year, sb.title, sb.imprint
                        FROM srcbib sb LEFT JOIN languagenames ln ON ln.srcabbr=sb.srcabbr
                          LEFT JOIN lexicon l ON l.lgid=ln.lgid
                        WHERE coalesce(l.status,'') NOT IN ('HIDE','DELETED')
                        GROUP BY sb.srcabbr HAVING num_recs>0 ORDER BY sb.citation COLLATE unaccent""").fetchall()
    c.close()
    trs = ""
    for r in rows:
        ref = (
            f'{esc(_period(r["author"]))} {esc(_period(r["year"]))} <cite>{esc(r["title"])}</cite>'
            f'{"" if (r["title"] or "").endswith((".", "?")) else "."}'
            f'{(" " + esc(_period(r["imprint"]))) if r["imprint"] else ""}'
        )
        trs += (
            f'<tr>\n<td><a href="{BASE}/source/{esc(r["srcabbr"])}" target="stedt_src">{esc(r["citation"])}</a></td>\n'
            f'<td>{r["num_lgs"]}</td>\n<td>{r["num_recs"]}</td>\n<td>{ref}</td>\n</tr>\n'
        )
    body = f"""<p>Sources for the data in the STEDT database ({len(rows)} total):</p>
<table class="hangindent sortable">
<tr><th>citation</th><th>languages</th><th>records</th><th>Reference</th></tr>
{trs}</table>"""
    return chrome("Source Bibliography - STEDT Database", body)


# ------------------------------------------------------------------------------------- group pages
_LG_TH = (
    '<th title="Language name from source OR abbreviated name" style="cursor:help;">Short Lg Name</th>'
    '<th>num. of records</th><th title="from Namkung, ed. 1996 (STEDT Monograph #3)" '
    'style="cursor:help;">Phon. Inventory</th>'
)


def legacy_group(grpid, lgid=None):
    """groups.tt: group tree + the languages-in-group table. With an lgid (the URL /group/<id>/<lgid>
    a reflex language link points at), show the selected language's detail + "other sources which
    include this language" (same lgcode) + "other languages in group" (the rest)."""
    c = render.con()
    grp = c.execute("SELECT grpno, grp FROM languagegroups WHERE grpid=?", (grpid,)).fetchone()
    if not grp:
        c.close()
        raise ValueError(f"no group {grpid}")
    grps = c.execute("SELECT grpid, grpno, grp FROM languagegroups ORDER BY grp0,grp1,grp2,grp3,grp4").fetchall()
    lgs = [
        dict(r)
        for r in c.execute(
            """SELECT ln.silcode, ln.language, ln.lgcode, ln.srcabbr, sb.citation, ln.lgid,
             COUNT(l.rn) AS nrec, ln.pi_page, ln.lgabbr
           FROM languagenames ln LEFT JOIN lexicon l ON l.lgid=ln.lgid
             LEFT JOIN srcbib sb ON sb.srcabbr=ln.srcabbr
           WHERE ln.grpid=? AND coalesce(ln.lgcode,0)!=0
             AND coalesce(l.status,'') NOT IN ('HIDE','DELETED')
           GROUP BY ln.lgid HAVING nrec>0 ORDER BY ln.lgcode, ln.language COLLATE unaccent""",
            (grpid,),
        )
    ]
    c.close()
    grpname = f'{esc(grp["grpno"])} {esc(grp["grp"])}'

    def iso(r):
        return (
            (
                f'<a href="http://www.ethnologue.com/show_language.asp?code={esc(r["silcode"])}" '
                f'target="stedt_ethnologue">{esc(r["silcode"])}</a>'
            )
            if r["silcode"]
            else "n/a"
        )

    def pi(r):
        return (
            (
                f'<a href="{BASE}/phon_inv.html?page={(r["pi_page"] or 0) + 26}" target="stedt_pi" '
                f'title="Namkung, ed. 1996">p.{r["pi_page"]}</a>'
            )
            if r["pi_page"]
            else ""
        )

    def recs(r):
        return f'<a href="{BASE}/gnis?lexicon.lgid={r["lgid"]}" target="stedt_sss">{r["nrec"]}</a>'

    def src(r):
        return f'<a href="{BASE}/source/{esc(r["srcabbr"])}" target="stedt_src">{esc(r["citation"])}</a>'

    tree = "".join(
        (
            f'<tr bgcolor="#FFFF99" id="showme"><td>{esc(g["grpno"])}</td>'
            if g["grpid"] == grpid
            else f'<tr><td>{esc(g["grpno"])}</td>'
        )
        + f'<td><a href="{BASE}/group/{g["grpid"]}">{esc(g["grp"])}</a></td></tr>\n'
        for g in grps
    )

    sel = next((i for i, r in enumerate(lgs) if r["lgid"] == lgid), None) if lgid is not None else None

    lginfo = ""
    if sel is not None:
        s = lgs[sel]
        lg_code = s["lgcode"]
        lginfo += (
            f'<p>Language information for <b>{esc(s["language"])}</b> from source {src(s)}:</p>\n'
            f"<table>\n"
            f'<tr><th title="Language name from source OR abbreviated name" style="cursor:help;">Short Lg Name</th><td>{esc(s["lgabbr"])}</td></tr>\n'
            f"<tr><th>ISO 639-3</th><td>{iso(s)}</td></tr>\n"
            f"<tr><th>num. of records</th><td>{recs(s)}</td></tr>\n"
            + (
                f'<tr><th title="from Namkung, ed. 1996 (STEDT Monograph #3)" style="cursor:help;">Phon. Inventory</th><td>{pi(s)}</td></tr>\n'
                if s["pi_page"]
                else ""
            )
            + "</table>\n"
        )
        others = [r for j, r in enumerate(lgs) if j != sel and r["lgcode"] == lg_code]
        if others:
            orows = "".join(
                f'<tr>\n<td>{esc(r["language"])}</td>\n<td>{src(r)}</td>\n'
                f'<td>{esc(r["lgabbr"])}</td>\n<td>{recs(r)}</td>\n<td>{pi(r)}</td>\n</tr>\n'
                for r in others
            )
            lginfo += (
                '<p>Other sources which include this language:</p>\n<table class="hangindent">\n'
                f"<tr><th>Language Name</th><th>Source</th>{_LG_TH}</tr>\n{orows}</table>\n"
            )
        else:
            lginfo += "(No other sources with this language.)\n"
        lginfo += f"<p>Other languages in <b>{grpname}</b>:</p>\n"
        main = [r for j, r in enumerate(lgs) if j != sel and r["lgcode"] != lg_code]
    else:
        lginfo += f"<p>Languages in <b>{grpname}</b></p>\n"
        main = lgs

    lrows = "".join(
        f'<tr id="lg{r["lgid"]}">\n<td>{iso(r)}</td>\n'
        f'<td><a href="{BASE}/group/{grpid}/{r["lgid"]}" target="_self">{esc(r["language"])}</a></td>\n'
        f'<td>{src(r)}</td>\n<td>{esc(r["lgabbr"])}</td>\n<td>{recs(r)}</td>\n<td>{pi(r)}</td>\n</tr>\n'
        for r in main
    )

    body = f"""<table id="lgtreehead"><tr><th style="width:4em">Group #</th><th>Group Name</th></tr></table>
<div id="lgtree"><table>
{tree}</table></div>
<div id="lginfo">
{lginfo}<table>
<tr><th>ISO 639-3</th><th>Language Name</th><th>Source</th>{_LG_TH}</tr>
{lrows}</table>
</div>
<script>
if ($('showme')) $('lgtree').scrollTop = Math.max(0, $('showme').offsetTop - document.viewport.getHeight()/3);
</script>"""
    return chrome("Language Groups - STEDT Database", body)


# ------------------------------------------------------------------------------------ chapter pages
def legacy_chapter(semkey):
    c = render.con()
    row = c.execute("SELECT chaptertitle FROM chapters WHERE semkey=?", (semkey,)).fetchone()
    title = (row["chaptertitle"] if row else None) or "[chapter does not exist in chapters table!]"
    notes = c.execute(
        """SELECT notetype, noteid, xmlnote FROM notes WHERE spec='C' AND id=? AND notetype!='I'
                         AND xmlnote IS NOT NULL ORDER BY ord, noteid""",
        (semkey,),
    ).fetchall()
    table, n = _etyma_table(
        c,
        "e.chapter=? AND coalesce(upper(e.status),'')!='DELETE'",
        (semkey,),
        "CASE WHEN CAST(e.sequence AS REAL)=0 THEN 1 ELSE 0 END, CAST(e.sequence AS REAL), e.public DESC",
    )
    c.close()

    notes_html = ""
    for nt in notes:
        if nt["notetype"] == "G":
            notes_html += (
                f'<div><a href="{BASE}/pdf/{nt["noteid"]}.pdf">' f'<img src="{BASE}/png/{nt["noteid"]}.png"></a></div>'
            )
        else:
            notes_html += f'<p>{_lnote(nt["xmlnote"])}</p>'

    etyma_section = f"<h2>Etyma in this chapter</h2>\n{table}" if table else ""
    body = f"""<p>[Back to the <a href="{BASE}/chapters">Chapter Browser</a>]</p>
<h1>{esc(semkey)} {esc(title)}</h1>
{notes_html}
{etyma_section}
<br>"""
    scripts = ""
    if table:
        scripts = f"""<script src="{BASE}/js/tbl/etyma.js"></script>
<script>
var footnote_counter = 0;
$w('u_recs o_recs etyma.exemplary etyma.chapter etyma.notes etyma.xrefs etyma.possallo etyma.allofams users.username etyma.semkey etyma.status etyma.prefix etyma.initial etyma.rhyme etyma.tone').each(function (col) {{ if (setup['etyma'][col]) setup['etyma'][col].hide = true; }});
setup['etyma']['etyma.protoform'].transform = function (v, key, rec, n) {{
  if (rec[$('etyma.public').cellIndex] === '1') return v;
  return v + ' <span style="color:red;">[provisional]</span>';
}};
setup['etyma']['etyma.public'] = {{ noedit: true, hide: true, size: 15 }};
TableKit.Raw.init('etyma_resulttable', 'etyma', setup['etyma']);
TableKit.Rows.stripe('etyma_resulttable');
</script>
<script src="{BASE}/js/notes.js"></script>"""
    return chrome(f"STEDT Chapter {semkey}", body, extra_scripts=scripts)


def _semkey_tuple(sk):
    # numeric parts sort naturally; non-numeric (e.g. the 'x.x' admin chapter) sort to the very end,
    # matching rootcanal's v/f/c ordering which keeps special chapters at the bottom.
    return tuple(int(p) if str(p).isdigit() else 10**9 for p in str(sk).split("."))


def legacy_chapter_browser():
    c = render.con()
    chs = c.execute("""SELECT ch.semkey, ch.chaptertitle,
                         (SELECT COUNT(*) FROM etyma WHERE chapter=ch.semkey AND coalesce(upper(status),'')!='DELETE') AS netyma,
                         (SELECT COUNT(DISTINCT noteid) FROM notes WHERE id=ch.semkey) AS nnotes,
                         (SELECT MAX(notetype='G') FROM notes WHERE id=ch.semkey) AS flow
                       FROM chapters ch WHERE coalesce(ch.semkey,'')!=''""").fetchall()
    c.close()
    chs = sorted((dict(r) for r in chs), key=lambda r: _semkey_tuple(r["semkey"]))

    vols = [
        r for r in chs if str(r["semkey"]).replace(".0", "").count(".") == 0 and _semkey_tuple(r["semkey"])[0] <= 10
    ]
    vol_html = "".join(f'<li><a href="#{esc(v["semkey"])}">{esc(v["chaptertitle"])}</a></li>' for v in vols)

    trs = ""
    for r in chs:
        sk = str(r["semkey"])
        indent = sk.replace(".0", "").count(".")
        pad = "&nbsp;" * (5 * indent)
        depth = sk.count(".")
        ti = esc(r["chaptertitle"])
        if indent == 0:
            ti = f"<b>{ti}</b>"
        elif indent == 1:
            ti = f"<i>{ti}</i>"
        # every row is a deep-link target, like the original's /chapters#1.1.1 (829 anchors)
        anchor = f'<a name="{esc(sk)}"></a>'
        trs += (
            f'<tr>\n<td>{anchor}{pad}<a target="notes" href="{BASE}/chap/{esc(sk)}">{esc(sk)}</a></td>\n'
            f'<td>{pad}{ti}</td>\n<td>{r["netyma"] or ""}</td>\n<td>{r["nnotes"] or ""}</td>\n'
            f'<td>{"✓" if r["flow"] else ""}</td>\n</tr>\n'
        )

    body = f"""<h1>Chapters</h1>
Volumes:
<ol>{vol_html}</ol>
<p>{len(chs)} nodes</p>
<table id="ch" class="sortable resizable hangindent" width="100%" style="table-layout:fixed">
<thead><tr><th>semkey</th><th>title</th><th>num. etyma</th><th>notes</th><th>flowchart?</th></tr></thead>
<tbody>
{trs}</tbody></table>"""
    return chrome("STEDT Chapter Browser", body)


if __name__ == "__main__":
    for name, fn in (("splash", legacy_splash), ("gnis", legacy_gnis), ("etymon1764", lambda: legacy_etymon(1764))):
        open(f"/tmp/legacy_{name}.html", "w").write(fn())
        print(f"wrote /tmp/legacy_{name}.html")
