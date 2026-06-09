#!/usr/bin/env python3
"""Render library for the /_legacy/ rootcanal clone — pixel-faithful static pages.

Reproduces rootcanal's PUBLIC (logged-out) Template-Toolkit output as HTML from stedt.sqlite, loading
rootcanal's verbatim CSS/JS (copied by build_legacy.py). The dynamic behavior (search, sortable tables,
elink popups, autosuggest) is supplied at runtime by src/legacy-shim.js, which intercepts the original
AJAX endpoints and answers them from legacy.sqlite3 in WASM. Every page is noindex'd.

`chrome()` mirrors web/header.tt's guest branch; per-page functions mirror splash.tt / index.tt /
etymon.tt. self_base/self_url/baseRef are set to the legacy base (BASE), so all asset/link/AJAX URLs
stay inside the subtree. Reuses render.con() for the DB connection.
"""
import os
import html as _html

import render  # reuse con() + helpers; same stedt.sqlite schema

BASE = os.environ.get("STEDT_LEGACY_BASE", "/_legacy").rstrip("/")
VER = os.environ.get("STEDT_LEGACY_VER", "")


def esc(s):
    return _html.escape("" if s is None else str(s))


# ---------------------------------------------------------------------------------- shared chrome
def chrome(title, body, vert_tog=False, cognates=None, extra_scripts=""):
    """web/header.tt, guest branch: external rootcanal CSS/JS + the legacy-shim module (first, so its
    XHR patch is installed before any AJAX), noindex meta, guest header (login/tools forms removed)."""
    cog = ""
    if cognates:
        cog = ("<style type=\"text/css\">"
               + "".join(f".r{n} {{ background-color:yellow; }} " for n in cognates)
               + "".join(f".u{n} {{ background-color:#6FF; }} " for n in cognates)
               + "</style>")
    tog = ""
    if vert_tog:
        tog = (f'<img id="spinner" src="{BASE}/img/spinner.gif" style="display:none;">&nbsp;'
               f'<a href="#" onclick="return vert_tog()"><img title="Rotate View" '
               f'src="{BASE}/img/toggle.png" alt="toggle" id="tog-img" border="0"></a>&nbsp;')
    return f"""﻿<!DOCTYPE html>
<html lang="en">
<head>
\t<meta charset="utf-8">
\t<meta name="robots" content="noindex,nofollow">
\t<title>{esc(title)}</title>
\t<script>window.STEDT_BASE="{BASE}";window.STEDT_LEGACY_DB_VERSION="{VER}";</script>
\t<script type="module" src="{BASE}/assets/legacy-shim.js"></script>
\t<link rel="stylesheet" href="{BASE}/styles/rootcanal.css">
\t<link rel="stylesheet" href="{BASE}/styles/autoSuggest.css">
\t<link rel="stylesheet" href="{BASE}/styles/opentip.css">
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
var stedtuserprivs = 0;
</script>
<a href="https://stedt.berkeley.edu/documentation" target="_blank">help</a>
<script src="{BASE}/js/stedtconfig.js"></script>
</span>
<a href="{BASE}/" title="Search Home"><img src="{BASE}/img/splashy32x32.gif" alt="STEDT Logo" width="32" height="32" class="left" border=0></a>
<b>{esc(title)}</b>
<hr style="clear:both; margin-left:45px">
</div>
{body}
<div class="legacy-footer" style="clear:both;text-align:center;font-size:small;color:#888;margin:3em 0 1em;border-top:1px solid #ddd;padding-top:1em">
Legacy interface · <a href="{BASE}/../">Return to the current STEDT site</a>
</div>
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

ETYMON_FIELDS = ["lexicon.rn", "analysis", "languagenames.lgid", "lexicon.reflex", "lexicon.gloss",
                 "lexicon.gfn", "languagenames.language", "languagegroups.grpid", "languagegroups.grpno",
                 "languagegroups.grp", "languagegroups.genetic", "citation", "languagenames.srcabbr",
                 "lexicon.srcid", "notes.rn"]


def _alt_stars(pf):
    """etymon.tt: asterisk each alternant (after ⪤ / OR / ~ / =) then prefix '*'."""
    import re as _re
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
    e = c.execute("""SELECT e.tag, e.chapter, e.sequence, e.protoform, e.protogloss, e.public, g.plg
                     FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
                     WHERE e.tag=? AND coalesce(upper(e.status),'')!='DELETE'""", (tag,)).fetchone()
    if not e:
        c.close()
        raise ValueError(f"no etymon #{tag}")
    plg, pf, pg = e["plg"] or "", e["protoform"] or "", e["protogloss"] or ""

    # allofams: same chapter & same integer sequence (FLOOR), non-DELETE
    allo = c.execute("""SELECT tag, sequence, protoform, protogloss FROM etyma
                        WHERE chapter=? AND sequence!='0' AND sequence!='0.0'
                          AND CAST(sequence AS INTEGER)=CAST(? AS INTEGER)
                          AND coalesce(upper(status),'')!='DELETE' ORDER BY sequence""",
                     (e["chapter"], e["sequence"])).fetchall()

    # mesoroots
    meso = c.execute("""SELECT m.grpid, g.grpno, g.grp, g.plg, m.form, m.gloss, m.variant, g.genetic
                        FROM mesoroots m LEFT JOIN languagegroups g ON g.grpid=m.grpid
                        WHERE m.tag=? ORDER BY g.grp0,g.grp1,g.grp2,g.grp3,g.grp4, m.variant""",
                     (tag,)).fetchall()
    meso = [dict(m) for m in meso]

    # reflexes (Tags.pm::etymon, guest 15 cols); analysis computed in Python (version-safe)
    recs = c.execute("""SELECT l.rn, ln.lgid, l.reflex, l.gloss, l.gfn, ln.language, g.grpid, g.grpno,
                          g.grp, g.genetic, sb.citation, ln.srcabbr, l.srcid,
                          (SELECT COUNT(*) FROM notes WHERE notes.rn=l.rn) AS num_notes
                        FROM lexicon l JOIN lx_et_hash h ON h.rn=l.rn AND h.tag=?
                          LEFT JOIN languagenames ln ON ln.lgid=l.lgid
                          LEFT JOIN languagegroups g ON g.grpid=ln.grpid
                          LEFT JOIN srcbib sb ON sb.srcabbr=ln.srcabbr
                        WHERE coalesce(l.status,'') NOT IN ('HIDE','DELETED')
                        GROUP BY l.rn
                        ORDER BY g.grp0,g.grp1,g.grp2,g.grp3,g.grp4, ln.lgsort, l.reflex, ln.srcabbr, l.srcid""",
                     (tag,)).fetchall()
    rns = [r["rn"] for r in recs]
    ana = {}
    if rns:
        qm = ",".join("?" * len(rns))
        for rn, ts in c.execute(f"SELECT rn, tag_str FROM lx_et_hash WHERE rn IN ({qm}) AND tag_str IS NOT NULL "
                                f"ORDER BY rn, ind", rns):
            ana.setdefault(rn, []).append(str(ts))

    def cell(v):
        return f"<td>{esc(v)}</td>"

    rows_html = ""
    for r in recs:
        vals = [r["rn"], ",".join(ana.get(r["rn"], [])), r["lgid"], r["reflex"], r["gloss"], r["gfn"],
                r["language"], r["grpid"], r["grpno"], r["grp"], r["genetic"], r["citation"],
                r["srcabbr"], r["srcid"], r["num_notes"]]
        rows_html += "<tr>" + "".join(cell(v) for v in vals) + "</tr>\n"

    # notes (spec=E, not comparanda 'F', not internal 'I') + Chinese comparanda ('F')
    notes = c.execute("""SELECT xmlnote FROM notes WHERE tag=? AND spec='E'
                         AND notetype NOT IN ('F','I') AND xmlnote IS NOT NULL ORDER BY ord, noteid""",
                      (tag,)).fetchall()
    comp = c.execute("""SELECT xmlnote FROM notes WHERE tag=? AND notetype='F'
                        AND xmlnote IS NOT NULL ORDER BY ord, noteid""", (tag,)).fetchall()
    all_grps = {r["grpno"]: {"grpid": r["grpid"], "grpno": r["grpno"], "grp": r["grp"],
                             "genetic": str(r["genetic"]) if r["genetic"] is not None else "0"}
                for r in c.execute("SELECT grpid, grpno, grp, genetic FROM languagegroups")}
    crumbs = _breadcrumbs(c, e["chapter"])
    c.close()

    # ---- assemble markup (etymon.tt guest branch) ----
    allobox = ""
    if len(allo) > 1:
        items = "".join(
            (f'<li><b>{esc(_fmt_seq(a["sequence"]))} #{a["tag"]} *{esc(a["protoform"])} {esc(a["protogloss"])}</b></li>'
             if a["tag"] == tag else
             f'<li><a href="{BASE}/etymon/{a["tag"]}">{esc(_fmt_seq(a["sequence"]))} #{a["tag"]} '
             f'*{esc(a["protoform"])} {esc(a["protogloss"])}</a></li>')
            for a in allo)
        allobox = f'<div class="right" id="allofambox"><b>Allofams:</b><ul>{items}</ul></div>'

    crumbs_html = ""
    for i, (sk, ti) in enumerate(crumbs):
        if i == len(crumbs) - 1:
            crumbs_html += f'<a href="{BASE}/chap/{esc(sk)}">{esc(sk)} <b>{esc(ti)}</b></a>'
        else:
            crumbs_html += f'{esc(sk)} <b>{esc(ti)}</b> &gt; '

    prov = '' if e["public"] else ' <span id="prov_heading" style="color:red; cursor:help; font-size:medium">(provisional)</span>'
    heading = (f'<table><tr><td style="padding: 10px;">'
               f'<h1>#{tag} {esc(plg)} {esc(_alt_stars(pf))} {esc(pg)}{prov}</h1></td></tr></table>')

    meso_html = ""
    if meso:
        lis = "".join(f'<li><a href="#{esc(m["grpno"])}">{esc(m["plg"])} *{esc(m["form"])} {esc(m["gloss"])}</a></li>'
                      for m in meso)
        meso_html = f'Reconstructed mesoroots below:\n<ul class="mesolist">{lis}</ul>'

    notes_html = "".join(f'<div class="notepreview"><p>{render.render_note(n["xmlnote"])}</p></div>' for n in notes)

    table_html = ""
    if recs:
        ths = "".join(f'<th id="{f}">{esc(f.split(".")[-1])}</th>' for f in ETYMON_FIELDS)
        table_html = (f'<table id="lexicon1" tag="{tag}" class="hangindent">\n'
                      f'<thead><tr>{ths}</tr></thead>\n<tbody>\n{rows_html}</tbody></table>')

    comp_html = ""
    if comp:
        label = "Chinese comparand" + ("um" if len(comp) == 1 else "a")
        comp_html = f'<h2>{label}</h2>' + "".join(f'<p>{render.render_note(n["xmlnote"])}</p>' for n in comp)

    body = (f'{allobox}\n<p>{crumbs_html}</p>\n{heading}\n{meso_html}\n{notes_html}\n{table_html}\n{comp_html}\n'
            f'<br>\n')

    scripts = f"""<script>
var footnote_counter = 0;
skipped_roots[{tag}] = true;
num_tables = 2;
var stedt_other_username = '';
var uid2 = '';
var mesoroots = {_json.dumps(meso)};
var subgroupnotes = [];
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
    return str(int(f)) + (chr(ord('a') - 1 + int(frac[0])) if frac and frac[0].isdigit() else "")


if __name__ == "__main__":
    for name, fn in (("splash", legacy_splash), ("gnis", legacy_gnis),
                     ("etymon1764", lambda: legacy_etymon(1764))):
        open(f"/tmp/legacy_{name}.html", "w").write(fn())
        print(f"wrote /tmp/legacy_{name}.html")
