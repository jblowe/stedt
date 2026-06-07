#!/usr/bin/env python3
"""STEDT — prototype 'new face'. Server-rendered, reads stedt.sqlite, zero deps.

Run:  python3 serve.py   ->   http://localhost:8000
Routes: /  /search?q=  /etymon/<tag>  /thesaurus[/<semkey>]  /reconstructions
        /languages  /language/<lgid>  /sources  /source/<srcabbr>  /about  /api/search?q=
This mirrors a static build: every page is real HTML at a stable URL and could be
pre-rendered to files; live search is the only dynamic bit.
"""
import http.server, socketserver, sqlite3, urllib.parse, re, html, json, os, yaml, difflib

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# The canonical public origin used in citations. Placeholder until the read site is
# deployed — set this to the real domain at deploy time so citations resolve.
SITE_ORIGIN = "https://stedt.org"

# YAML dumper matching export_files.py, so an edited etymon re-serializes with a clean one-field diff
class _YD(yaml.SafeDumper): pass
_NEL = ('\x85', ' ', ' ')
def _ystr(d, s):
    if any(ch in s for ch in _NEL):
        return d.represent_scalar('tag:yaml.org,2002:str', s, style='"')
    return d.represent_scalar('tag:yaml.org,2002:str', s, style='|' if '\n' in s else None)
_YD.add_representer(str, _ystr)
def ydump(o): return yaml.dump(o, Dumper=_YD, allow_unicode=True, sort_keys=False, width=100)

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stedt.sqlite")
PORT = 8000

def con():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c

# ---------------------------------------------------------------- note XML -> HTML
_ENT = {'&quot;': '"', '&apos;': '’', '&amp;': '&', '&lt;': '<', '&gt;': '>'}
_PAIR = {
    'par': ('<p class="np">', '</p>'), 'reconstruction': ('<span class="recon">', '</span>'),
    'latinform': ('<span class="lat">', '</span>'), 'plainlatinform': ('<span class="lat">', '</span>'),
    'hanform': ('<span class="han">', '</span>'), 'gloss': ('<span class="gl">', '</span>'),
    'emph': ('<em>', '</em>'), 'strong': ('<strong>', '</strong>'),
    'footnote': ('<span class="fn">', '</span>'), 'unicode': ('<span>', '</span>'),
    'sup': ('<sup>', '</sup>'), 'sub': ('<sub>', '</sub>'),
}
def render_note(x):
    if not x: return ""
    s = x
    s = re.sub(r'<xref[^>]*\bref="(\d+)"[^>]*>(.*?)</xref>',
               r'<a class="xref" href="/etymon/\1">\2</a>', s, flags=re.S)
    s = re.sub(r'</?xref[^>]*>', '', s)
    s = re.sub(r'<a\s+href="([^"]*)"[^>]*>(.*?)</a>',
               r'<a href="\1" rel="noopener" target="_blank">\2</a>', s, flags=re.S)
    for t, (o, c) in _PAIR.items():
        s = s.replace(f'<{t}>', o).replace(f'</{t}>', c)
    s = re.sub(r'<br\s*/?>', '<br>', s)
    for e, ch in _ENT.items():
        s = s.replace(e, ch)
    if '<p' not in s:
        s = f'<p class="np">{s}</p>'
    return s

def natkey(s):
    out = []
    for p in (s or '').split('.'):
        out.append((0, int(p), '') if p.isdigit() else (1, 0, p))
    return out

def esc(s): return html.escape(str(s)) if s is not None else ""

def suggest_edit_url(e):
    """Prefilled 'Suggest an edit' Issue Form link — the contribution front door.
    Opens a GitHub issue (login handled by GitHub, no service) that the suggest-edit
    Action turns into a validated PR. Note SQLite cols: gloss=protogloss, references=notes."""
    q = urllib.parse.urlencode({
        "template": "suggest-edit.yml",
        "title": f"Suggested edit to etymon #{e['tag']}",
        "tag": e['tag'],
        "protoform": e['protoform'] or "",
        "gloss": e['protogloss'] or "",
        "semkey": e['semkey'] or "",
        "references": e['notes'] or "",
    })
    return f"https://github.com/larc-iu/stedt/issues/new?{q}"

# ---------------------------------------------------------------- page shell
CSS = r"""
:root{
  --paper:#f4efe2; --paper2:#efe8d6; --ink:#211c15; --soft:#5d5443;
  --mut:#94886e; --rule:#ddd1b6; --hair:#e7dcc4; --accent:#9c2b25; --accent-d:#7e201b;
  --accent2:#3a5a6b; --gold:#b08a3c;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:"Charis SIL","Gentium Plus",Georgia,serif; font-size:18px; line-height:1.55;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.025'/%3E%3C/svg%3E");
}
.han{font-family:"Noto Serif SC","Songti SC",serif;}
.lat{font-style:italic;}
.recon{font-style:italic;} .recon::before{content:"*"; color:var(--accent);}
.gl,.gloss{font-variant:small-caps; letter-spacing:.02em;}

/* links: quiet neutral underline at rest; vermilion only on hover */
a{color:var(--ink); text-decoration:none; border-bottom:1px solid var(--rule);}
a:hover{color:var(--accent); border-bottom-color:var(--accent);}
.brand .wm a,nav.main a{border-bottom:none;}
a.xref{color:var(--accent); border-bottom:1px dotted var(--accent);}

/* masthead */
.top{height:3px;background:var(--accent);}
header.mast{max-width:1080px;margin:0 auto;padding:22px 28px 14px;display:flex;align-items:flex-end;
  gap:26px;border-bottom:1px solid var(--rule);flex-wrap:wrap;}
.brand{display:flex;flex-direction:column;line-height:1;}
.brand .wm{font-family:"Fraunces",serif;font-weight:600;font-size:30px;letter-spacing:.01em;
  font-optical-sizing:auto;}
.brand .sub{font-variant:small-caps;letter-spacing:.08em;font-size:11.5px;color:var(--mut);margin-top:7px;}
nav.main{margin-left:auto;display:flex;gap:20px;font-variant:small-caps;letter-spacing:.07em;font-size:15px;}
nav.main a{color:var(--soft);} nav.main a:hover{color:var(--accent);}
nav.main a.active{color:var(--ink);border-bottom:2px solid var(--accent);padding-bottom:2px;}
.hsearch input{font-family:inherit;font-size:15px;padding:7px 11px;width:200px;border:1px solid var(--rule);
  background:var(--paper2);color:var(--ink);border-radius:2px;}
.hsearch input:focus{outline:none;border-color:var(--accent);}

main{max-width:1080px;margin:0 auto;padding:34px 28px 90px;}
.prose{max-width:38em;}
.cap{color:var(--mut);font-size:14px;margin:0 0 14px;}
footer{max-width:1080px;margin:0 auto;padding:24px 28px 60px;border-top:1px solid var(--rule);
  color:var(--mut);font-size:13.5px;}

/* home */
.home{max-width:600px;margin:7vh auto 0;text-align:center;}
.bigsearch{position:relative;text-align:left;}
.bigsearch input{width:100%;font-family:inherit;font-size:21px;padding:14px 18px;border:1.5px solid var(--ink);
  background:var(--paper2);border-radius:3px;}
.bigsearch input:focus{outline:none;border-color:var(--accent);}
.drop{position:absolute;left:0;right:0;top:104%;background:var(--paper);border:1px solid var(--rule);
  border-radius:3px;box-shadow:0 10px 30px rgba(33,28,21,.10);z-index:9;overflow:hidden;display:none;}
.drop a{display:flex;gap:10px;align-items:baseline;padding:9px 15px;border-bottom:1px solid var(--rule);}
.drop a:last-child{border-bottom:none}
.drop a:hover{background:var(--paper2);color:inherit;border-color:var(--rule);}
.drop .k{font-variant:small-caps;font-size:11px;color:var(--mut);width:46px;flex:none;letter-spacing:.08em;}
.entry{display:flex;flex-wrap:wrap;gap:10px 22px;justify-content:center;margin-top:28px;font-size:15px;}
.entry a{color:var(--soft);}
.entry a:hover{color:var(--accent);}

/* about */
.about{max-width:40em;}
.about p{margin:0 0 14px;}
.stats{display:flex;gap:34px;flex-wrap:wrap;margin:6px 0 18px;}
.stats .n{font-family:"Fraunces",serif;font-size:28px;color:var(--ink);line-height:1.1;font-variant-numeric:tabular-nums;}
.stats .l{font-variant:small-caps;letter-spacing:.08em;font-size:12px;color:var(--mut);}
.abbr{display:grid;grid-template-columns:max-content 1fr;gap:6px 16px;font-size:15px;margin:4px 0;}
.abbr dt{font-weight:700;} .abbr dd{margin:0;color:var(--soft);}

/* etymon page */
.ety-head{border-bottom:2px solid var(--ink);padding-bottom:16px;margin-bottom:8px;}
.ety-head .plg{font-variant:small-caps;letter-spacing:.08em;font-size:13px;color:var(--accent);}
.ety-head .etno{float:right;font-family:"Fraunces",serif;font-size:14px;color:var(--mut);
  font-variant-numeric:tabular-nums;letter-spacing:.02em;}
.badge{font-variant:small-caps;letter-spacing:.08em;font-size:11px;padding:1px 8px;margin-left:8px;
  border-radius:2px;border:1px solid;vertical-align:middle;}
.badge.del{color:var(--accent);border-color:var(--accent);}
.ety-head .pf{font-family:"Charis SIL",serif;font-size:44px;line-height:1.1;margin:6px 0 4px;}
.ety-head .pf::before{content:"*";color:var(--accent);}
.ety-head .pg{font-variant:small-caps;letter-spacing:.03em;font-size:20px;color:var(--soft);}
.crumbs{font-size:13px;color:var(--mut);margin:14px 0 0;}
.crumbs a{color:var(--soft);border-bottom:1px dotted var(--rule);}
.metabar{display:flex;gap:24px;margin:16px 0 4px;font-size:14px;color:var(--mut);flex-wrap:wrap;}
.metabar b{font-family:"Fraunces",serif;color:var(--ink);font-size:16px;margin-right:5px;font-variant-numeric:tabular-nums;}

/* section headers — the one small-caps + accent "label" tier */
.notes h3,.reflexes h3,.thes h3,.conn h3,.meso h3,.apparatus h3{font-variant:small-caps;letter-spacing:.10em;
  font-size:14px;color:var(--accent);border-bottom:1px solid var(--rule);padding-bottom:5px;margin:0 0 12px;}
.notes{margin:26px 0 8px;}
.np{margin:0 0 12px;max-width:38em;} .fn{font-size:.86em;color:var(--soft);}
.note-block{margin-bottom:6px;}

.jump{font-size:12.5px;color:var(--mut);margin:0 0 18px;line-height:2;}
.jump a{border-bottom:1px dotted var(--rule);margin-right:4px;}
.sg{margin:0 0 22px;}
.sg h4{display:flex;align-items:baseline;gap:10px;font-variant:small-caps;letter-spacing:.06em;font-size:16px;
  margin:0 0 6px;border-bottom:1px solid var(--rule);padding-bottom:3px;}
.sg h4 .c{font-family:"Fraunces",serif;font-size:12px;color:var(--mut);letter-spacing:0;margin-left:auto;
  font-variant-numeric:tabular-nums;}
.rfx{display:grid;grid-template-columns:190px minmax(0,1fr) 190px;gap:2px 18px;padding:4px 0;
  border-bottom:1px solid var(--hair);align-items:baseline;line-height:1.35;}
.rfx:hover{background:var(--paper2);}
.rfx:last-child{border-bottom:none}
.rfx .lang{color:var(--soft);font-size:14.5px;}
.rfx .form{font-size:17px;}
.rfx .form .br{color:var(--mut);}
.rfx .src{font-size:13px;color:var(--mut);}
.rfx .g{color:var(--soft);font-size:13.5px;font-style:italic;}
.rfx a{border-bottom:none;}
.rfx a.lang{color:var(--soft);}
.rfx a:hover{color:var(--accent);border-bottom:1px solid var(--accent);}

/* end apparatus: citation + references, de-banner'd */
.apparatus{margin-top:42px;}
.citebox{border:1px solid var(--rule);padding:12px 15px;border-radius:2px;font-size:14.5px;color:var(--soft);
  max-width:48em;}
.citebox > div{margin:0 0 4px;} .citebox > div:last-child{margin-bottom:0;}
.citebox code{font-family:"Charis SIL",serif;color:var(--ink);}
.cite-actions{display:flex;gap:18px;margin:12px 0 0;font-size:14px;flex-wrap:wrap;}
.cite-actions a,.copybtn{color:var(--soft);border:none;border-bottom:1px solid var(--rule);background:none;
  font-family:inherit;font-size:14px;padding:0;cursor:pointer;}
.cite-actions a:hover,.copybtn:hover{color:var(--accent);border-color:var(--accent);}

/* search */
.sr h2{font-family:"Fraunces",serif;font-weight:600;font-size:24px;margin:0 0 4px;}
.sr .sub{color:var(--mut);font-size:14px;margin-bottom:24px;}
.sec-label{font-variant:small-caps;letter-spacing:.10em;font-size:13px;color:var(--accent);
  border-bottom:1px solid var(--rule);padding-bottom:5px;margin:28px 0 10px;}
.ety-hit{display:grid;grid-template-columns:auto 1fr auto;gap:14px;align-items:baseline;padding:8px 0;
  border-bottom:1px solid var(--hair);}
a.ety-hit{border-bottom:1px solid var(--hair);}
a.ety-hit:hover{color:inherit;background:var(--paper2);border-color:var(--hair);}
.ety-hit .pf2{font-size:19px;} .ety-hit .pf2::before{content:"*";color:var(--accent);}
.ety-hit .pg2{font-variant:small-caps;color:var(--soft);}
.ety-hit .tagn{font-family:"Fraunces",serif;font-size:12px;color:var(--mut);font-variant-numeric:tabular-nums;}
.rx-hit{display:grid;grid-template-columns:180px 1fr 1fr;gap:14px;align-items:baseline;padding:6px 0;
  border-bottom:1px solid var(--hair);font-size:15px;}
.rx-hit .lang{color:var(--soft);font-size:13.5px;}
.rx-hit .via{font-size:12.5px;color:var(--mut);text-align:right;}

/* thesaurus */
.thes ul{list-style:none;padding:0;margin:0;}
.thes li{border-bottom:1px solid var(--rule);}
.thes li a.row{display:flex;align-items:baseline;gap:12px;padding:11px 6px;border-bottom:none;}
.thes li a.row:hover{background:var(--paper2);color:inherit;}
.thes .sk{font-family:"Fraunces",serif;font-size:13px;color:var(--mut);width:64px;flex:none;
  font-variant-numeric:tabular-nums;}
.thes .ti{font-size:18px;}
.thes .ct{margin-left:auto;font-size:13px;color:var(--mut);font-variant-numeric:tabular-nums;}
.thes .ety-list{margin-top:18px}

/* connections / mesoroots / language+source + index pages */
.pagetitle{font-family:"Fraunces",serif;font-weight:600;font-size:36px;line-height:1.08;margin:6px 0 4px;}
.conn,.meso{margin:24px 0 8px;}
.conn-row{display:flex;align-items:baseline;gap:12px;padding:6px 0;border-bottom:1px solid var(--hair);}
.conn-row:last-child{border-bottom:none}
.rl{font-variant:small-caps;letter-spacing:.08em;font-size:12px;color:var(--accent);width:92px;flex:none;}
.conn-row .reltgt{flex:1;}
.exm{color:var(--gold);font-variant:small-caps;letter-spacing:.06em;font-size:.9em;}
.metabar a{border-bottom:1px dotted var(--rule);}
.metabar a:hover{color:var(--accent);}
.idx{list-style:none;padding:0;margin:6px 0 0;columns:2;column-gap:44px;font-size:15px;}
.idx li{break-inside:avoid;padding:2px 0;}
.grp{font-variant:small-caps;letter-spacing:.05em;font-size:15px;color:var(--ink);margin:18px 0 2px;}
.grp .plg2{color:var(--mut);font-variant:normal;font-size:.82em;letter-spacing:0;}
.pager{display:flex;align-items:baseline;gap:22px;margin:26px 0 0;font-size:14px;color:var(--mut);}
.srclangs{margin:12px 0 4px;font-size:13.5px;color:var(--soft);line-height:1.9;}
.subg{color:var(--soft);font-size:14px;}
.rfx .via{color:var(--mut);}
details.seg{border-bottom:1px solid var(--rule);}
details.seg:last-of-type{border-bottom:none;}
details.seg > summary{cursor:pointer;list-style:none;display:flex;align-items:baseline;gap:10px;
  font-variant:small-caps;letter-spacing:.06em;font-size:15px;color:var(--ink);padding:9px 2px;}
details.seg > summary::-webkit-details-marker{display:none;}
details.seg > summary::before{content:"▸";color:var(--mut);font-size:11px;}
details.seg[open] > summary::before{content:"▾";}
details.seg > summary:hover{color:var(--accent);}
details.seg > summary .c{margin-left:auto;font-family:"Fraunces",serif;font-size:12px;color:var(--mut);
  letter-spacing:0;font-variant-numeric:tabular-nums;}
details.seg .rfx{padding-left:20px;}
details.seg[open]{padding-bottom:8px;}

/* contribution form + diff */
.editform{max-width:620px;margin:8px 0;}
.editform label{display:block;margin:0 0 14px;font-variant:small-caps;letter-spacing:.06em;font-size:13px;color:var(--soft);}
.editform input,.editform textarea{display:block;width:100%;margin-top:4px;font-family:"Charis SIL",serif;
  font-size:16px;font-variant:normal;letter-spacing:0;color:var(--ink);padding:8px 11px;
  border:1px solid var(--rule);background:var(--paper2);border-radius:2px;}
.editform input:focus,.editform textarea:focus{outline:none;border-color:var(--accent);}
.editform .hint{font-variant:normal;letter-spacing:0;color:var(--mut);text-transform:none;}
.editform hr,.editform .who{border:none;border-top:1px solid var(--rule);margin:18px 0;padding-top:14px;}
.editform .actions{display:flex;align-items:center;gap:16px;margin-top:6px;}
.editform button{font-family:inherit;font-size:16px;font-variant:small-caps;letter-spacing:.05em;
  padding:9px 22px;background:var(--accent);color:var(--paper);border:none;border-radius:2px;cursor:pointer;}
.editform button:hover{background:var(--accent-d);}
.editform .cancel{background:none;color:var(--mut);}
.gate{padding:10px 16px;border-radius:2px;margin:16px 0;font-size:15px;}
.gate.ok{background:#e8f0e3;border-left:3px solid #4a7c3a;color:#2f4f25;}
.gate.bad{background:#f6e3e0;border-left:3px solid var(--accent);color:var(--accent-d);}
.gate ul{margin:6px 0 0 18px;}
pre.diff{background:#faf7ef;border:1px solid var(--rule);border-radius:3px;padding:14px 16px;overflow:auto;
  font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:13px;line-height:1.5;}
pre.diff span{display:block;white-space:pre-wrap;}
pre.diff .add{background:#e3f0db;color:#2f4f25;}
pre.diff .del{background:#f6dfdb;color:var(--accent-d);}
pre.diff .hdr{color:var(--mut);}
"""

_NAV = [("thesaurus", "/thesaurus", "Thesaurus"),
        ("reconstructions", "/reconstructions", "Reconstructions"),
        ("languages", "/languages", "Languages"),
        ("sources", "/sources", "Sources"),
        ("about", "/about", "About")]

def page(title, body, q="", nav=""):
    nav_parts = []
    for key, href, label in _NAV:
        cls = ' class="active"' if nav == key else ''
        nav_parts.append(f'<a href="{href}"{cls}>{label}</a>')
    navhtml = "".join(nav_parts)
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · STEDT</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;1,9..144,400&family=Charis+SIL:ital,wght@0,400;0,700;1,400;1,700&family=Noto+Serif+SC:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body>
<div class="top"></div>
<header class="mast">
  <div class="brand">
    <span class="wm"><a href="/">STEDT</a></span>
    <span class="sub">Sino-Tibetan Etymological Dictionary &amp; Thesaurus</span>
  </div>
  <nav class="main">{navhtml}</nav>
  <form class="hsearch" action="/search" method="get">
    <input name="q" placeholder="search…" value="{esc(q)}" autocomplete="off">
  </form>
</header>
<main>{body}</main>
<footer></footer>
</body></html>"""

# ---------------------------------------------------------------- views
def home():
    body = """
    <div class="home">
      <div class="bigsearch">
        <input id="bs" placeholder="Search a meaning, form, or language — e.g. “ladder”, “gam”, “Lahu”" autocomplete="off">
        <div class="drop" id="drop"></div>
      </div>
      <div class="entry">
        <a href="/thesaurus">Browse by meaning</a>
        <a href="/reconstructions">All reconstructions</a>
        <a href="/languages">Languages</a>
        <a href="/sources">Sources</a>
        <a href="/etymon/260">A sample entry: *m-gam ‘ladder’</a>
      </div>
    </div>
    <script>
    const bs=document.getElementById('bs'),d=document.getElementById('drop');let t;
    bs.addEventListener('input',()=>{{clearTimeout(t);const q=bs.value.trim();
      if(q.length<2){{d.style.display='none';return;}}
      t=setTimeout(async()=>{{const r=await fetch('/api/search?limit=8&q='+encodeURIComponent(q));
        const j=await r.json();let h='';
        j.etyma.forEach(e=>h+=`<a href="/etymon/${{e.tag}}"><span class="k">recon</span><span><span class="recon">${{e.protoform}}</span> · <span class="gl">${{e.protogloss}}</span></span></a>`);
        j.reflexes.forEach(x=>h+=`<a href="${{x.tag?'/etymon/'+x.tag:'#'}}"><span class="k">${{x.language}}</span><span><span class="lat">${{x.form}}</span> ‘${{x.gloss}}’</span></a>`);
        d.innerHTML=h;d.style.display=h?'block':'none';}},180);}});
    bs.addEventListener('keydown',e=>{{if(e.key==='Enter')location='/search?q='+encodeURIComponent(bs.value);}});
    document.addEventListener('click',e=>{{if(!e.target.closest('.bigsearch'))d.style.display='none';}});
    </script>"""
    return page("Home", body)

def about():
    c = con()
    n = lambda s: c.execute(s).fetchone()[0]
    ety = n("SELECT count(*) FROM etyma e WHERE coalesce(upper(e.status),'')!='DELETE'")
    rfx = n("SELECT count(*) FROM lexicon")
    lgs = n("SELECT count(DISTINCT ln.language) FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid WHERE ln.language!='' AND ln.language NOT LIKE '*%'")
    src = n("SELECT count(*) FROM srcbib")
    c.close()
    stat = lambda v, l: f'<div><div class="n">{v:,}</div><div class="l">{l}</div></div>'
    abbr = [("ST", "Sino-Tibetan"), ("TB", "Tibeto-Burman"), ("PTB", "Proto-Tibeto-Burman"),
            ("HPTB", "Matisoff (2003), <i>Handbook of Proto-Tibeto-Burman</i>"),
            ("STC", "Benedict (1972), <i>Sino-Tibetan: A Conspectus</i>"),
            ("PLB", "Proto-Lolo-Burmese"), ("PKC", "Proto-Kuki-Chin"), ("PTani", "Proto-Tani")]
    abbrhtml = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in abbr)
    body = f"""
    <div class="ety-head">
      <div class="plg">About</div>
      <div class="pagetitle">About STEDT</div>
    </div>
    <div class="about">
      <p>The Sino-Tibetan Etymological Dictionary and Thesaurus is a record of the
      reconstructed vocabulary of the Sino-Tibetan language family: proto-forms, the
      attested words that descend from them, and the semantic categories that organize them.</p>
      <div class="stats">
        {stat(ety, "reconstructions")}{stat(rfx, "attested forms")}
        {stat(lgs, "languages")}{stat(src, "sources")}
      </div>
      <h3 class="sec-label">Provenance</h3>
      <p>STEDT was compiled at the University of California, Berkeley, under the direction of
      James A. Matisoff. This site is built faithfully from the STEDT v1.0 public release (2017):
      etymon numbers and the underlying records are preserved, and no new reconstructions have
      been added. It is a read-only republication intended to keep the resource available and
      citable independently of any single institution.</p>
      <h3 class="sec-label">Citing</h3>
      <p>Each entry has a stable address of the form <code>{esc(SITE_ORIGIN)}/etymon/&lt;number&gt;</code>,
      and the etymon number is the citable identity. A ready-made citation appears at the foot of
      every entry. When citing a particular attested form, cite its original source as well.</p>
      <h3 class="sec-label">License</h3>
      <p>STEDT v1.0 was released for public use; the licensing terms for this republication are
      being finalized.</p>
      <h3 class="sec-label">Contributing</h3>
      <p>Corrections and additions are welcome. Every entry links to a way to suggest an edit;
      proposed changes are reviewed before they go live.</p>
      <h3 class="sec-label">Abbreviations</h3>
      <dl class="abbr">{abbrhtml}</dl>
    </div>"""
    return page("About", body, nav="about")

def breadcrumb(c, semkey):
    parts = (semkey or "").split('.')
    out = []
    for i in range(1, len(parts) + 1):
        sk = '.'.join(parts[:i])
        r = c.execute("SELECT chaptertitle FROM chapters WHERE semkey=?", (sk,)).fetchone()
        if not r and '.' not in sk:  # integer chapter level: borrow the N.0 overview title
            r = c.execute("SELECT chaptertitle FROM chapters WHERE semkey=?", (sk + '.0',)).fetchone()
        if r: out.append(f'<a href="/thesaurus/{sk}">{esc(r[0])}</a>')
    return ' &nbsp;›&nbsp; '.join(out)

def etymon(tag):
    c = con()
    e = c.execute("""SELECT e.*, g.plg AS plg FROM etyma e
        LEFT JOIN languagegroups g ON g.grpid=e.grpid WHERE e.tag=?""", (tag,)).fetchone()
    if not e:
        c.close(); return page("Not found", "<p>No such etymon.</p>"), 404
    notes = c.execute("""SELECT xmlnote FROM notes WHERE tag=? AND spec='E' AND notetype!='I'
                         AND xmlnote IS NOT NULL ORDER BY ord, noteid""", (tag,)).fetchall()
    rows = c.execute("""SELECT l.rn AS rn, ln.language AS language, l.lgid AS lgid, l.reflex AS form, l.gloss,
            g.grp AS subgroup, g.grpno AS groupnode, g.plg AS grpplg,
            sb.citation AS citation, ln.srcabbr AS srcabbr
        FROM lx_et_hash h JOIN lexicon l ON l.rn=h.rn
        JOIN languagenames ln ON ln.lgid=l.lgid
        LEFT JOIN languagegroups g ON g.grpid=ln.grpid
        LEFT JOIN srcbib sb ON sb.srcabbr=ln.srcabbr
        WHERE h.tag=? GROUP BY l.rn""", (tag,)).fetchall()
    hptb = c.execute("""SELECT h.plg, h.protoform, h.protogloss, h.pages
        FROM et_hptb_hash x JOIN hptb h ON h.hptbid=x.hptbid WHERE x.tag=? ORDER BY x.ord""", (tag,)).fetchall()
    meso = c.execute("""SELECT g.grp AS subgroup, g.grpno AS groupnode, m.form, m.gloss, m.variant, m.old_note
        FROM mesoroots m LEFT JOIN languagegroups g ON g.grpid=m.grpid
        WHERE m.tag=? ORDER BY g.grpno, m.id""", (tag,)).fetchall()
    # cross-reference labels: collect every tag mentioned in a pure tag-list field
    digit_tokens = set()
    for fld in (e['allofams'], e['xrefs'], e['possallo']):
        if fld and re.fullmatch(r'[\d,\s]+', fld.strip()):
            digit_tokens.update(int(t) for t in re.split(r'[,\s]+', fld.strip()) if t)
    labels = {}
    if digit_tokens:
        toks = list(digit_tokens); qm = ','.join('?' * len(toks))
        for r in c.execute(f"SELECT tag,protoform,protogloss FROM etyma WHERE tag IN ({qm})", toks):
            labels[r['tag']] = (r['protoform'], r['protogloss'])
    crumb = breadcrumb(c, e['semkey']); c.close()

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
    if nsub > 6:
        jump = '<div class="jump">Jump to subgroup: ' + ''.join(
            f'<a href="#sg{i}">{esc(k[1])}</a>' for i, k in enumerate(gkeys)) + '</div>'

    sgs = []
    for i, k in enumerate(gkeys):
        items = sorted(groups[k], key=lambda r: ((r['language'] or ''), (r['form'] or '')))
        rfx = []
        for r in items:
            form = esc(r['form']).replace('◦', '<span class="br">◦</span>')
            g = f'<span class="g">{esc(r["gloss"])}</span>' if (r['gloss'] and r['gloss'] != e['protogloss']) else ''
            lang = f'<a class="lang" href="/language/{r["lgid"]}">{esc(r["language"])}</a>'
            if r['srcabbr']:
                src = f'<a class="src" href="/source/{esc(r["srcabbr"])}">{esc(r["citation"] or r["srcabbr"])}</a>'
            else:
                src = f'<span class="src">{esc(r["citation"] or "")}</span>'
            rfx.append(f'<div class="rfx" id="r{r["rn"]}">{lang}<span class="form">{form} {g}</span>{src}</div>')
        sgs.append(f'<div class="sg" id="sg{i}"><h4>{esc(k[1])}<span class="c">{len(items)}</span></h4>'
                   + ''.join(rfx) + '</div>')

    noteshtml = ""
    if notes:
        noteshtml = ('<section class="notes"><h3>Notes</h3>'
                     + ''.join(f'<div class="note-block">{render_note(r["xmlnote"])}</div>' for r in notes)
                     + '</section>')

    reflexeshtml = (f'<section class="reflexes"><h3>Reflexes &amp; cognates</h3>{jump}{"".join(sgs)}</section>'
                    if sgs else '')

    mesohtml = ''
    if meso:
        mr = ''
        for m in meso:
            sm = f'<span class="src">{esc(m["old_note"])}</span>' if m['old_note'] else '<span class="src"></span>'
            mr += (f'<div class="rfx"><span class="lang">{esc(m["subgroup"] or "")}</span>'
                   f'<span class="form"><span class="recon">{esc(m["form"])}</span> '
                   f'<span class="g">{esc(m["gloss"])}</span></span>{sm}</div>')
        mesohtml = f'<section class="meso"><h3>Intermediate reconstructions</h3>{mr}</section>'

    # previously published reconstructions (reflex rows whose "language" is a proto-form node)
    reconhtml = ''
    if recon_rows:
        rr = ''
        for r in recon_rows:
            lab = r['grpplg'] or r['subgroup'] or (r['language'] or '').lstrip('*')
            if r['srcabbr']:
                cit = f'<a class="src" href="/source/{esc(r["srcabbr"])}">{esc(r["citation"] or r["srcabbr"])}</a>'
            else:
                cit = f'<span class="src">{esc(r["citation"] or "")}</span>'
            gl = f' ‘{esc(r["gloss"])}’' if r['gloss'] else ''
            rr += (f'<div class="conn-row"><span class="rl">{esc(lab)}</span>'
                   f'<span class="reltgt"><span class="recon">{esc(r["form"])}</span>{gl}</span>{cit}</div>')
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
                txt = f'*{esc(lab[0])} ‘{esc(lab[1])}’' if lab else f'#{esc(t)}'
                parts.append(f'<a class="xref" href="/etymon/{t}">{txt}</a>')
            return ', '.join(parts)
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

    pf = esc(e['protoform'])
    badges = '<span class="badge del">deleted</span>' if (e['status'] or '').upper() == 'DELETE' else ''
    exm = ' · <span class="exm">exemplary</span>' if (e['exemplary'] or '') == 'x' else ''

    cite_text = f"STEDT etymon #{e['tag']}, *{e['protoform']} ‘{e['protogloss']}’. {SITE_ORIGIN}/etymon/{e['tag']}"
    bib = ("@misc{stedt-" + str(e['tag']) + ",\n"
           "  title  = {{*" + (e['protoform'] or '') + " '" + (e['protogloss'] or '') + "'}},\n"
           "  author = {STEDT},\n"
           "  year   = {2017},\n"
           "  note   = {Sino-Tibetan Etymological Dictionary and Thesaurus (STEDT) v1.0, etymon #" + str(e['tag']) + "},\n"
           "  url    = {" + SITE_ORIGIN + "/etymon/" + str(e['tag']) + "}\n"
           "}")
    refs_line = f'<div>References: {esc(e["notes"])}</div>' if e['notes'] else ''
    copy_js = ("<script>document.querySelectorAll('.copybtn').forEach("
               "b=>b.addEventListener('click',()=>{navigator.clipboard.writeText(b.dataset.cite);"
               "b.textContent='Copied';}));</script>")
    apparatus = f"""
    <section class="apparatus"><h3>Cite this entry</h3>
      <div class="citebox">
        <div>STEDT etymon #{e['tag']}, <code>*{pf} ‘{esc(e['protogloss'])}’</code>.</div>
        <div>Stable link: <code>{esc(SITE_ORIGIN)}/etymon/{e['tag']}</code></div>
        <div>Data: STEDT v1.0 (2017). Accessed: ____.</div>
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
      <div class="plg">{esc(e['plg'])}{exm}{badges}</div>
      <div class="pf">{pf}</div>
      <div class="pg">{esc(e['protogloss'])}</div>
      <div class="crumbs">Semantic domain: {crumb or esc(e['semkey'])}</div>
    </div>
    <div class="metabar">
      <span><b>{len(reflex_rows)}</b>reflexes</span>
      <span><b>{nsub}</b>subgroups</span>
    </div>
    {noteshtml}
    {reflexeshtml}
    {mesohtml}
    {reconhtml}
    {connhtml}
    {apparatus}"""
    return page(f"*{e['protoform']} ‘{e['protogloss']}’", body, nav="reconstructions"), 200

def group_lineage(c, grpno):
    """Genetic lineage (ancestors incl. self) by walking grpno prefixes."""
    out = []
    if not grpno: return out
    parts = str(grpno).split('.')
    for i in range(1, len(parts) + 1):
        r = c.execute("SELECT grpid,grp FROM languagegroups WHERE grpno=?", ('.'.join(parts[:i]),)).fetchone()
        if r: out.append(r)
    return out

def proto_labels(c, tags):
    """Map {tag: protoform} for a set of etymon tags."""
    tags = [t for t in tags if t]
    out = {}
    for i in range(0, len(tags), 900):
        chunk = tags[i:i + 900]
        qm = ','.join('?' * len(chunk))
        for r in c.execute(f"SELECT tag,protoform FROM etyma WHERE tag IN ({qm})", chunk):
            out[r['tag']] = r['protoform']
    return out

def language(lgid):
    c = con()
    ln = c.execute("SELECT * FROM languagenames WHERE lgid=?", (lgid,)).fetchone()
    if not ln:
        c.close(); return page("Not found", "<p>No such language.</p>"), 404
    grp = c.execute("SELECT grpid,grpno,grp,plg FROM languagegroups WHERE grpid=?", (ln['grpid'],)).fetchone()
    src = c.execute("SELECT srcabbr,citation FROM srcbib WHERE srcabbr=?", (ln['srcabbr'],)).fetchone()
    rows = c.execute("""SELECT l.reflex, l.gloss, l.semkey,
            (SELECT h.tag FROM lx_et_hash h WHERE h.rn=l.rn AND h.tag>0 LIMIT 1) AS tag
        FROM lexicon l WHERE l.lgid=? ORDER BY l.semkey, l.reflex""", (lgid,)).fetchall()
    total = len(rows)
    chap = {r['semkey']: r['chaptertitle'] for r in c.execute("SELECT semkey,chaptertitle FROM chapters")}
    lin = group_lineage(c, grp['grpno']) if grp else []
    plabels = proto_labels(c, {r['tag'] for r in rows if r['tag']})
    c.close()

    crumb_links = ['<a href="/languages">Languages</a>'] + \
                  [f'<a href="/languages#g{gg["grpid"]}">{esc(gg["grp"])}</a>' for gg in lin]
    meta = []
    if src and src['srcabbr']:
        meta.append(f'<span><b>source</b> <a href="/source/{esc(src["srcabbr"])}">{esc(src["citation"] or src["srcabbr"])}</a></span>')
    if ln['silcode']: meta.append(f'<span><b>ISO 639-3</b> {esc(ln["silcode"])}</span>')
    meta.append(f'<span><b>{total:,}</b> reflexes</span>')

    groups = {}
    for r in rows:
        sk = r['semkey'] or ''
        groups.setdefault(sk.split('.')[0] if sk else '', []).append(r)
    keys = sorted(groups, key=lambda k: (k == '', natkey(k)))
    openall = total <= 80
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
            via = (f'<a class="via" href="/etymon/{r["tag"]}">› *{esc(plabels.get(r["tag"], ""))}</a>'
                   if r['tag'] else '')
            rfx.append(f'<div class="rfx">{catcell}'
                       f'<span class="form">{form} <span class="g">{esc(r["gloss"])}</span></span>'
                       f'<span class="src">{via}</span></div>')
        segs.append(f'<details class="seg"{" open" if openall else ""}><summary>{esc(ttl)}'
                    f'<span class="c">{len(items)}</span></summary>{"".join(rfx)}</details>')

    body = f"""
    <div class="ety-head">
      <div class="plg">Language</div>
      <div class="pagetitle">{esc(ln['language'])}</div>
      <div class="crumbs">{' &nbsp;›&nbsp; '.join(crumb_links)}</div>
      <div class="metabar">{''.join(meta)}</div>
    </div>
    <section class="reflexes"><h3>Attested forms</h3>{''.join(segs)}</section>"""
    return page(ln['language'], body, nav="languages"), 200

def source(srcabbr):
    c = con()
    s = c.execute("SELECT * FROM srcbib WHERE srcabbr=?", (srcabbr,)).fetchone()
    if not s:
        c.close(); return page("Not found", "<p>No such source.</p>"), 404
    langs = c.execute("""SELECT ln.lgid AS lgid, ln.language AS language,
            g.grp AS subgroup, g.grpno AS grpno, count(l.rn) AS n
        FROM languagenames ln LEFT JOIN lexicon l ON l.lgid=ln.lgid
        LEFT JOIN languagegroups g ON g.grpid=ln.grpid
        WHERE ln.srcabbr=? AND ln.language!='' GROUP BY ln.lgid
        HAVING n>0 ORDER BY ln.language""", (srcabbr,)).fetchall()
    c.close()
    total = sum(l['n'] for l in langs)
    cite = ' '.join(x for x in (s['author'], f"({s['year']})" if s['year'] else '', s['title']) if x)
    meta = []
    if s['imprint']: meta.append(f'<span><b>imprint</b> {esc(s["imprint"])}</span>')
    meta.append(f'<span><b>{len(langs)}</b> languages</span>')
    meta.append(f'<span><b>{total:,}</b> forms</span>')
    rows = ''.join(
        f'<div class="rfx"><a class="lang" href="/language/{l["lgid"]}">{esc(l["language"])}</a>'
        f'<span class="subg">{esc(l["subgroup"] or "")}</span>'
        f'<span class="src">{l["n"]:,} forms</span></div>' for l in langs)
    citehtml = f'<div class="pg" style="font-variant:normal;font-size:16px;color:var(--soft);letter-spacing:0">{esc(cite)}</div>' if cite else ''
    body = f"""
    <div class="ety-head">
      <div class="plg">Source · {esc(s['srcabbr'])}</div>
      <div class="pagetitle">{esc(s['citation'] or s['srcabbr'])}</div>
      {citehtml}
      <div class="crumbs"><a href="/sources">Sources</a> &nbsp;›&nbsp; {esc(s['srcabbr'])}</div>
      <div class="metabar">{''.join(meta)}</div>
    </div>
    <section class="reflexes"><h3>Languages in this source</h3>{rows}</section>"""
    return page(s['citation'] or s['srcabbr'], body, nav="sources"), 200

def reconstructions(page_n=1):
    c = con(); PER = 100
    OK = "coalesce(upper(e.status),'')!='DELETE'"
    total = c.execute(f"SELECT count(*) FROM etyma e WHERE {OK}").fetchone()[0]
    pages = max(1, (total + PER - 1) // PER)
    page_n = max(1, min(page_n, pages))
    off = (page_n - 1) * PER
    rows = c.execute(f"""SELECT e.tag, e.protoform, e.protogloss, g.plg AS plg
        FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
        WHERE {OK} ORDER BY e.protogloss, e.tag LIMIT ? OFFSET ?""", (PER, off)).fetchall()
    c.close()
    hits = ''.join(
        f'<a class="ety-hit" href="/etymon/{r["tag"]}">'
        f'<span class="pf2 lat">{esc(r["protoform"])}</span>'
        f'<span class="pg2">{esc(r["protogloss"])}</span>'
        f'<span class="tagn">{esc(r["plg"])} #{r["tag"]}</span></a>' for r in rows)
    prev = f'<a href="/reconstructions?page={page_n-1}">← previous</a>' if page_n > 1 else '<span></span>'
    nxt = f'<a href="/reconstructions?page={page_n+1}">next →</a>' if page_n < pages else '<span></span>'
    pager = f'<div class="pager">{prev}<span>page {page_n} of {pages}</span>{nxt}</div>'
    body = f"""
    <div class="ety-head">
      <div class="plg">Browse</div>
      <div class="pagetitle">Reconstructions</div>
      <div class="metabar"><span><b>{total:,}</b>etyma</span><span>ordered by gloss</span></div>
    </div>
    {hits}
    {pager}"""
    return page("Reconstructions", body, nav="reconstructions")

def languages_index():
    c = con()
    rows = c.execute("""SELECT g.grpno AS grpno, g.grp AS grp, g.plg AS plg, g.grpid AS grpid,
            ln.language AS language, ln.lgid AS lgid, count(*) AS n
        FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid
        LEFT JOIN languagegroups g ON g.grpid=ln.grpid
        WHERE ln.language NOT LIKE '*%'
        GROUP BY ln.lgid""").fetchall()
    c.close()
    groups, ntot = {}, 0
    for r in rows:
        nm = r['language'] or ''
        if not nm: continue
        key = (r['grpno'] or 'zz', r['grp'] or '—', r['plg'] or '', r['grpid'])
        d = groups.setdefault(key, {})
        cur = d.get(nm)
        if cur is None or r['n'] > cur[1]:
            d[nm] = (r['lgid'], r['n'])
    for d in groups.values(): ntot += len(d)
    gkeys = sorted(groups, key=lambda k: natkey(k[0]))
    out = ['<div class="ety-head"><div class="plg">Browse</div><div class="pagetitle">Languages</div>',
           f'<div class="metabar"><span><b>{ntot:,}</b>languages</span><span>by genetic subgroup</span></div></div>']
    for grpno, grp, plg, grpid in gkeys:
        langs = groups[(grpno, grp, plg, grpid)]
        depth = str(grpno).count('.')
        head = esc(grp) + (f' <span class="plg2">({esc(plg)})</span>' if plg else '')
        gid = f' id="g{grpid}"' if grpid is not None else ''
        items = ''.join(f'<li><a href="/language/{lid}">{esc(nm)}</a></li>'
                        for nm, (lid, _) in sorted(langs.items(), key=lambda kv: kv[0].lower()))
        out.append(f'<h4 class="grp"{gid} style="margin-left:{depth*16}px">{head}</h4>'
                   f'<ul class="idx">{items}</ul>')
    return page("Languages", ''.join(out), nav="languages")

def sources_index():
    c = con()
    rows = c.execute("""SELECT srcabbr, citation, author, year, title FROM srcbib
        ORDER BY lower(coalesce(nullif(author,''),nullif(citation,''),srcabbr)), year""").fetchall()
    c.close()
    items = []
    for s in rows:
        label = s['citation'] or ' '.join(
            x for x in (s['author'], f"({s['year']})" if s['year'] else '', s['title']) if x) or s['srcabbr']
        items.append(f'<li><a href="/source/{esc(s["srcabbr"])}">{esc(label)}</a></li>')
    body = (f'<div class="ety-head"><div class="plg">Browse</div><div class="pagetitle">Sources</div>'
            f'<div class="metabar"><span><b>{len(rows):,}</b>sources</span></div></div>'
            f'<ul class="idx">{"".join(items)}</ul>')
    return page("Sources", body, nav="sources")

def _etymon_path(tag):
    return os.path.join(DATA, "etyma", f"{tag}.yaml")

def edit_form(tag):
    p = _etymon_path(tag)
    if not os.path.exists(p):
        return page("Not found", "<p>No such etymon.</p>"), 404
    d = yaml.safe_load(open(p, encoding='utf-8'))
    F = lambda k: esc(d.get(k) if d.get(k) is not None else '')
    body = f"""
    <div class="ety-head">
      <div class="plg">Suggest an edit · #{tag}</div>
      <div class="pagetitle">*{F('protoform')} ‘{F('gloss')}’</div>
      <div class="crumbs">Your proposal is reviewed by a moderator before it goes live — nothing changes immediately.</div>
    </div>
    <form class="editform" method="post" action="/etymon/{tag}/edit">
      <label>Proto-form <input name="protoform" value="{F('protoform')}"></label>
      <label>Gloss <input name="gloss" value="{F('gloss')}"></label>
      <label>Semantic key <input name="semkey" value="{F('semkey')}"></label>
      <label>References <input name="references" value="{F('references')}"></label>
      <label>Add a note <span class="hint">(optional; plain text or STEDT note markup)</span>
        <textarea name="newnote" rows="3"></textarea></label>
      <div class="who">
        <label>Your name <input name="author" placeholder="Jane Linguist" required></label>
        <label>What &amp; why <input name="summary" placeholder="e.g. corrected gloss per Matisoff 2003" required></label>
      </div>
      <div class="actions"><button type="submit">Propose change →</button>
        <a class="cancel" href="/etymon/{tag}">Cancel</a></div>
    </form>"""
    return page(f"Edit #{tag}", body), 200

def validate_proposed(tag, d):
    """Lightweight gate preview (the full validate.py runs in CI on the resulting PR)."""
    c = con(); probs = []
    if d.get('tag') != tag: probs.append("the etymon tag must not change")
    if not (d.get('protoform') or '').strip(): probs.append("proto-form is empty")
    if not (d.get('gloss') or '').strip(): probs.append("gloss is empty")
    sk = d.get('semkey')
    if sk and not c.execute("SELECT 1 FROM chapters WHERE semkey=?", (sk,)).fetchone():
        probs.append(f"semantic key “{sk}” is not a thesaurus node")
    c.close(); return probs

def edit_submit(tag, form):
    p = _etymon_path(tag)
    if not os.path.exists(p):
        return page("Not found", "<p>No such etymon.</p>"), 404
    g1 = lambda k: (form.get(k, [''])[0] or '').strip()
    orig = open(p, encoding='utf-8').read()
    d = yaml.safe_load(orig)
    for k in ('protoform', 'gloss', 'semkey', 'references'):
        v = g1(k)
        if v: d[k] = v
        elif k in d: del d[k]
    if g1('newnote'):
        d.setdefault('notes', []).append({'type': 'T', 'text': g1('newnote')})
    proposed = ydump(d)
    diff = list(difflib.unified_diff(orig.splitlines(True), proposed.splitlines(True),
                                     fromfile=f"a/data/etyma/{tag}.yaml", tofile=f"b/data/etyma/{tag}.yaml"))
    probs = validate_proposed(tag, d)
    author, summary = esc(g1('author')), esc(g1('summary'))

    if not diff:
        return page("No change", '<p>No changes detected — nothing to propose. '
                    f'<a href="/etymon/{tag}/edit">Back</a></p>'), 200
    difflines = []
    for ln in diff:
        cls = 'add' if ln.startswith('+') and not ln.startswith('+++') else \
              'del' if ln.startswith('-') and not ln.startswith('---') else \
              'hdr' if ln.startswith('@@') or ln.startswith('+++') or ln.startswith('---') else ''
        difflines.append(f'<span class="{cls}">{esc(ln.rstrip(chr(10)))}</span>')
    gate = ('<div class="gate ok">✓ Passes the basic checks — ready for a moderator to review.</div>'
            if not probs else
            '<div class="gate bad">This proposal has issues a moderator would flag:<ul>'
            + ''.join(f'<li>{esc(x)}</li>' for x in probs) + '</ul></div>')
    body = f"""
    <div class="ety-head">
      <div class="plg">Proposed change · #{tag}</div>
      <div class="pagetitle">Submitted ✓</div>
      <div class="crumbs">By <b>{author or "anonymous"}</b> — “{summary}”</div>
    </div>
    <p class="prose">This is what a maintainer would review. On the live site it would open a
    pull request against <code>data/etyma/{tag}.yaml</code>; CI runs the full <code>validate.py</code>, and a
    moderator approves or requests changes. <em>(Prototype: nothing was written — this previews the flow.)</em></p>
    {gate}
    <h3 class="sec-label">The change</h3>
    <pre class="diff">{''.join(difflines)}</pre>
    <p><a href="/etymon/{tag}">← Back to the entry</a></p>"""
    return page(f"Proposed: #{tag}", body), 200

def fts_q(q):
    q = q.replace('"', ' ').strip()
    return '"%s"' % q if q else '""'

def search_data(q, limit=40):
    c = con()
    OK = "coalesce(upper(e.status),'')!='DELETE'"
    # a leading "*" is reconstruction notation, not a search operator; "*" alone still means "all"
    qe = q[1:].strip() if (q.startswith('*') and q != '*') else q
    etyma = []
    if q == '*':
        etyma = c.execute(f"""SELECT e.tag, g.plg AS plg, e.protoform, e.protogloss, e.semkey
            FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
            WHERE {OK} ORDER BY e.tag LIMIT ?""", (limit,)).fetchall()
    elif qe:
        like = f"%{qe}%"
        nohy = "%" + re.sub(r'[-|◦\s]', '', qe) + "%"  # morpheme-boundary–insensitive
        etyma = c.execute(f"""SELECT e.tag, g.plg AS plg, e.protoform, e.protogloss, e.semkey
            FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
            WHERE {OK} AND (e.protogloss LIKE ? OR e.protoform LIKE ?
                OR replace(replace(replace(e.protoform,'-',''),'|',''),'◦','') LIKE ?)
            ORDER BY CASE WHEN upper(e.protogloss) LIKE upper(?)||'%' THEN 0 ELSE 1 END, e.protogloss
            LIMIT ?""", (like, like, nohy, qe, limit)).fetchall()
    reflexes = []
    if qe and q != '*':
        reflexes = c.execute("""SELECT l.reflex AS form, l.gloss, ln.language AS language, l.rn,
              e.tag AS tag, e.protoform AS pf, e.protogloss AS pg
            FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid
            LEFT JOIN lx_et_hash h ON h.rn=l.rn AND h.tag>0
            LEFT JOIN etyma e ON e.tag=h.tag
            WHERE l.rn IN (SELECT rn FROM lexicon_fts WHERE lexicon_fts MATCH ? LIMIT ?)
            GROUP BY l.rn LIMIT ?""", (fts_q(qe), limit + 40, limit)).fetchall()
    c.close()
    return etyma, reflexes

def search_page(q):
    etyma, reflexes = search_data(q, 50)
    label = "all reconstructions" if q == '*' else f'“{esc(q)}”'
    out = [f'<div class="sr"><h2>Results for {label}</h2>'
           f'<div class="sub">{len(etyma)} reconstruction(s) · {len(reflexes)} attested form(s) shown</div>']
    if etyma:
        out.append('<div class="sec-label">Reconstructions</div>')
        for e in etyma:
            out.append(f'<a class="ety-hit" href="/etymon/{e["tag"]}">'
                       f'<span class="pf2 lat">{esc(e["protoform"])}</span>'
                       f'<span class="pg2">{esc(e["protogloss"])}</span>'
                       f'<span class="tagn">{esc(e["plg"])} #{e["tag"]}</span></a>')
    if reflexes:
        out.append('<div class="sec-label">Attested forms</div>')
        for r in reflexes:
            via = (f'<a class="via" href="/etymon/{r["tag"]}">› *{esc(r["pf"])}</a>'
                   if r['tag'] else '<span class="via">untagged</span>')
            out.append(f'<div class="rx-hit"><span class="lang">{esc(r["language"])}</span>'
                       f'<span><span class="lat">{esc(r["form"])}</span> ‘{esc(r["gloss"])}’</span>{via}</div>')
    if not etyma and not reflexes:
        out.append('<p class="cap">No matches.</p>')
    out.append('</div>')
    return page(f"Search: {q}", ''.join(out), q)

def thesaurus(semkey=None):
    c = con()
    body = ['<div class="thes">']
    if semkey:
        title = c.execute("SELECT chaptertitle FROM chapters WHERE semkey=?", (semkey,)).fetchone()
        if not title and '.' not in semkey:
            title = c.execute("SELECT chaptertitle FROM chapters WHERE semkey=?", (semkey + '.0',)).fetchone()
        title = title[0] if title else semkey
        body.append(f'<div class="crumbs"><a href="/thesaurus">Thesaurus</a> &nbsp;›&nbsp; {breadcrumb(c, semkey)}</div>')
        body.append(f'<h2 style="font-family:Fraunces;font-weight:600;font-size:30px;margin:10px 0 18px">{esc(title)}</h2>')
        depth = len(semkey.split('.'))
        kids = c.execute("""SELECT semkey,chaptertitle FROM chapters
            WHERE semkey LIKE ? AND (length(semkey)-length(replace(semkey,'.','')))=?
            """, (semkey + '.%', depth)).fetchall()
    else:
        body.append('<h2 style="font-family:Fraunces;font-weight:600;font-size:30px;margin:0 0 6px">Semantic Thesaurus</h2>')
        body.append('<p class="cap">Browse meanings from the most general to the most specific.</p>')
        # top level = the N.0 chapter overviews, presented as integer chapter nodes
        roots = c.execute("""SELECT semkey,chaptertitle FROM chapters
            WHERE semkey LIKE '%.0' AND (length(semkey)-length(replace(semkey,'.','')))=1""").fetchall()
        kids = [{'semkey': r['semkey'].split('.')[0], 'chaptertitle': r['chaptertitle']} for r in roots]
    kids = sorted(kids, key=lambda r: natkey(r['semkey']))
    if kids:
        body.append('<ul>')
        for k in kids:
            cnt = c.execute("""SELECT count(*) FROM etyma e WHERE coalesce(upper(e.status),'')!='DELETE'
                AND (e.semkey=? OR e.semkey LIKE ?)""", (k['semkey'], k['semkey'] + '.%')).fetchone()[0]
            body.append(f'<li><a class="row" href="/thesaurus/{k["semkey"]}">'
                        f'<span class="sk">{esc(k["semkey"])}</span><span class="ti">{esc(k["chaptertitle"])}</span>'
                        f'<span class="ct">{cnt} etyma</span></a></li>')
        body.append('</ul>')
    if semkey:
        direct = c.execute("""SELECT e.tag, e.protoform, e.protogloss, g.plg AS plg
            FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
            WHERE e.semkey=? AND coalesce(upper(e.status),'')!='DELETE' ORDER BY e.protogloss""", (semkey,)).fetchall()
        if direct:
            body.append('<div class="ety-list"><h3 style="margin-top:30px">Reconstructions here</h3>')
            for e in direct:
                body.append(f'<div class="ety-hit"><a href="/etymon/{e["tag"]}" class="pf2 lat">{esc(e["protoform"])}</a>'
                            f'<span class="pg2">{esc(e["protogloss"])}</span>'
                            f'<span class="tagn">{esc(e["plg"])} #{e["tag"]}</span></div>')
            body.append('</div>')
    c.close()
    body.append('</div>')
    return page("Thesaurus" + (f": {semkey}" if semkey else ""), ''.join(body), nav="thesaurus")

# ---------------------------------------------------------------- http
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, body, code=200, ctype="text/html; charset=utf-8"):
        b = body.encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers()
        self.wfile.write(b)
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); path = u.path
        qs = urllib.parse.parse_qs(u.query)
        q = (qs.get("q", [""])[0]).strip()
        try:
            if path == "/":
                self.send(home())
            elif path == "/about":
                self.send(about())
            elif path == "/api/search":
                lim = int(qs.get("limit", ["10"])[0])
                et, rx = search_data(q, lim)
                self.send(json.dumps({
                    "etyma": [dict(r) for r in et],
                    "reflexes": [{"form": r["form"], "gloss": r["gloss"], "language": r["language"], "tag": r["tag"]} for r in rx],
                }), ctype="application/json")
            elif path == "/search":
                self.send(search_page(q))
            elif path == "/reconstructions":
                pg = qs.get("page", ["1"])[0]
                self.send(reconstructions(int(pg) if pg.isdigit() else 1))
            elif path == "/languages":
                self.send(languages_index())
            elif path == "/sources":
                self.send(sources_index())
            elif path.startswith("/etymon/"):
                parts = path.split("/")   # ['', 'etymon', tag, ('edit')?]
                tag = parts[2]
                if not tag.isdigit():
                    self.send(page("Not found", "<p>Bad etymon id.</p>"), 404)
                elif len(parts) > 3 and parts[3] == "edit":
                    html_, code = edit_form(int(tag)); self.send(html_, code)
                else:
                    html_, code = etymon(int(tag)); self.send(html_, code)
            elif path == "/thesaurus":
                self.send(thesaurus())
            elif path.startswith("/thesaurus/"):
                self.send(thesaurus(path.split("/", 2)[2]))
            elif path.startswith("/language/"):
                lid = path.split("/")[2]
                if lid.isdigit():
                    html_, code = language(int(lid)); self.send(html_, code)
                else:
                    self.send(page("Not found", "<p>Bad language id.</p>"), 404)
            elif path.startswith("/source/"):
                html_, code = source(urllib.parse.unquote(path.split("/", 2)[2])); self.send(html_, code)
            elif path == "/favicon.ico":
                self.send("", 204)
            else:
                self.send(page("Not found", "<p>Page not found.</p>"), 404)
        except Exception as ex:
            import traceback; traceback.print_exc()
            self.send(page("Error", f"<pre>{esc(ex)}</pre>"), 500)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            m = re.match(r"^/etymon/(\d+)/edit$", path)
            if m:
                n = int(self.headers.get('Content-Length', 0))
                form = urllib.parse.parse_qs(self.rfile.read(n).decode('utf-8'), keep_blank_values=True)
                html_, code = edit_submit(int(m.group(1)), form); self.send(html_, code)
            else:
                self.send(page("Not found", "<p>Not found.</p>"), 404)
        except Exception as ex:
            import traceback; traceback.print_exc()
            self.send(page("Error", f"<pre>{esc(ex)}</pre>"), 500)

if __name__ == "__main__":
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("", PORT), H) as httpd:
        print(f"STEDT prototype → http://localhost:{PORT}")
        httpd.serve_forever()
