#!/usr/bin/env python3
"""STEDT — prototype 'new face'. Server-rendered, reads stedt.sqlite, zero deps.

Run:  python3 serve.py   ->   http://localhost:8000
Routes: /  /search?q=  /etymon/<tag>  /thesaurus  /thesaurus/<semkey>  /api/search?q=
This mirrors a static build: every page is real HTML at a stable URL and could be
pre-rendered to files; live search is the only dynamic bit.
"""
import http.server, socketserver, sqlite3, urllib.parse, re, html, json, os, yaml, difflib

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

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

# ---------------------------------------------------------------- page shell
CSS = r"""
:root{
  --paper:#f4efe2; --paper2:#efe8d6; --ink:#211c15; --soft:#5d5443;
  --mut:#94886e; --rule:#ddd1b6; --accent:#9c2b25; --accent2:#3a5a6b; --gold:#b08a3c;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:"Charis SIL","Gentium Plus",Georgia,serif; font-size:18px; line-height:1.55;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.025'/%3E%3C/svg%3E");
}
.han{font-family:"Noto Serif SC","Songti SC",serif;}
.lat{font-style:italic;}
.recon{font-style:italic;} .recon::before{content:"*"; color:var(--accent);}
.gl,.gloss{font-variant:small-caps; letter-spacing:.03em;}
a{color:var(--ink); text-decoration:none; background-image:linear-gradient(var(--accent),var(--accent));
  background-size:100% 1px; background-position:0 1.05em; background-repeat:no-repeat;}
a:hover{color:var(--accent); background-position:0 1.12em;}
a.xref{color:var(--accent); background:none; border-bottom:1px dotted var(--accent);}

/* masthead */
.top{height:4px;background:linear-gradient(90deg,var(--accent) 0 38%,var(--gold) 38% 42%,var(--accent) 42%);}
header.mast{max-width:1080px;margin:0 auto;padding:22px 28px 14px;display:flex;align-items:flex-end;
  gap:26px;border-bottom:1px solid var(--rule);flex-wrap:wrap;}
.brand{display:flex;flex-direction:column;line-height:1;}
.brand .wm{font-family:"Fraunces",serif;font-weight:600;font-size:34px;letter-spacing:.01em;
  font-optical-sizing:auto;}
.brand .wm a{background:none;}
.brand .sub{font-variant:small-caps;letter-spacing:.18em;font-size:11.5px;color:var(--mut);margin-top:7px;}
nav.main{margin-left:auto;display:flex;gap:20px;font-variant:small-caps;letter-spacing:.08em;font-size:15px;}
nav.main a{background:none;color:var(--soft);} nav.main a:hover{color:var(--accent);}
.hsearch{position:relative;}
.hsearch input{font-family:inherit;font-size:15px;padding:7px 11px;width:210px;border:1px solid var(--rule);
  background:var(--paper2);color:var(--ink);border-radius:2px;}
.hsearch input:focus{outline:none;border-color:var(--accent);}

main{max-width:1080px;margin:0 auto;padding:34px 28px 90px;animation:rise .5s ease both;}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
footer{max-width:1080px;margin:0 auto;padding:24px 28px 60px;border-top:1px solid var(--rule);
  color:var(--mut);font-size:13.5px;}

/* home */
.hero{text-align:center;padding:34px 0 10px;}
.hero h1{font-family:"Fraunces",serif;font-weight:600;font-size:52px;line-height:1.05;margin:0 0 10px;}
.hero p.lede{font-size:19px;color:var(--soft);max-width:620px;margin:0 auto 26px;}
.bigsearch{max-width:560px;margin:0 auto;position:relative;}
.bigsearch input{width:100%;font-family:inherit;font-size:21px;padding:14px 18px;border:1.5px solid var(--ink);
  background:var(--paper2);border-radius:3px;}
.bigsearch input:focus{outline:none;border-color:var(--accent);box-shadow:0 4px 22px rgba(156,43,37,.12);}
.drop{position:absolute;left:0;right:0;top:104%;background:var(--paper);border:1px solid var(--rule);
  border-radius:3px;box-shadow:0 14px 40px rgba(33,28,21,.14);z-index:9;overflow:hidden;display:none;}
.drop a{display:flex;gap:10px;align-items:baseline;padding:9px 15px;background:none;border-bottom:1px solid var(--rule);}
.drop a:last-child{border-bottom:none}
.drop a:hover{background:var(--paper2);color:inherit;}
.drop .k{font-variant:small-caps;font-size:11px;color:var(--mut);width:46px;flex:none;letter-spacing:.08em;}
.colophon{display:flex;justify-content:center;gap:38px;margin:40px 0 4px;flex-wrap:wrap;}
.colophon div{text-align:center;}
.colophon .n{font-family:"Fraunces",serif;font-size:30px;color:var(--accent);}
.colophon .l{font-variant:small-caps;letter-spacing:.12em;font-size:12px;color:var(--mut);}
.entry{display:flex;gap:18px;justify-content:center;margin-top:34px;}
.entry a{border:1px solid var(--rule);padding:11px 20px;background:var(--paper2);font-variant:small-caps;
  letter-spacing:.06em;}
.entry a:hover{border-color:var(--accent);color:var(--accent);}

/* etymon page */
.ety-head{border-bottom:2px solid var(--ink);padding-bottom:18px;margin-bottom:8px;}
.ety-head .plg{font-variant:small-caps;letter-spacing:.14em;font-size:13px;color:var(--accent);}
.badge{font-variant:small-caps;letter-spacing:.08em;font-size:11px;padding:1px 8px;margin-left:8px;
  border-radius:2px;border:1px solid;vertical-align:middle;}
.badge.del{color:#9c2b25;border-color:#9c2b25;background:#f6e3e0;}
.badge.draft{color:#7a6a33;border-color:#c2a64a;background:#f3ecd6;}
.ety-head .pf{font-family:"Charis SIL",serif;font-size:46px;line-height:1.1;margin:6px 0 4px;}
.ety-head .pf::before{content:"*";color:var(--accent);font-family:"Fraunces",serif;}
.ety-head .pg{font-variant:small-caps;letter-spacing:.04em;font-size:23px;color:var(--soft);}
.crumbs{font-size:13px;color:var(--mut);margin:14px 0 0;}
.crumbs a{background:none;color:var(--soft);border-bottom:1px dotted var(--rule);}
.metabar{display:flex;gap:26px;margin:16px 0 4px;font-size:13px;color:var(--mut);font-variant:small-caps;letter-spacing:.06em;}
.metabar b{font-family:"Fraunces",serif;font-variant:normal;color:var(--ink);font-size:16px;margin-right:5px;}
.cite{background:var(--paper2);border-left:3px solid var(--gold);padding:10px 16px;margin:20px 0;
  font-size:14px;color:var(--soft);}
.cite code{font-family:"Charis SIL",serif;color:var(--ink);}

.notes{margin:26px 0 8px;}
.notes h3,.reflexes h3,.thes h3{font-variant:small-caps;letter-spacing:.12em;font-size:14px;color:var(--accent);
  border-bottom:1px solid var(--rule);padding-bottom:5px;margin:0 0 12px;}
.np{margin:0 0 12px;} .fn{font-size:.86em;color:var(--soft);}
.note-block{margin-bottom:6px;}

.jump{font-size:12.5px;color:var(--mut);margin:0 0 18px;line-height:2;}
.jump a{background:none;border-bottom:1px dotted var(--rule);margin-right:4px;}
.sg{margin:0 0 20px;}
.sg h4{display:flex;align-items:baseline;gap:10px;font-variant:small-caps;letter-spacing:.07em;font-size:16px;
  margin:0 0 6px;border-bottom:1px solid var(--rule);padding-bottom:3px;}
.sg h4 .c{font-family:"Fraunces",serif;font-size:12px;color:var(--mut);letter-spacing:0;margin-left:auto;}
.rfx{display:grid;grid-template-columns:200px 1fr auto;gap:4px 18px;padding:3px 0;
  border-bottom:1px dotted #e7dcc4;align-items:baseline;}
.rfx:last-child{border-bottom:none}
.rfx .lang{color:var(--soft);font-size:14.5px;}
.rfx .form{font-size:17px;}
.rfx .form .br{color:var(--mut);}
.rfx .src{font-size:12px;color:var(--mut);text-align:right;font-variant:small-caps;letter-spacing:.04em;}
.rfx .g{color:var(--soft);font-size:13.5px;font-style:italic;}

/* search */
.sr h2{font-family:"Fraunces",serif;font-weight:600;font-size:24px;margin:0 0 4px;}
.sr .sub{color:var(--mut);font-size:14px;margin-bottom:24px;}
.sec-label{font-variant:small-caps;letter-spacing:.12em;font-size:13px;color:var(--accent);
  border-bottom:1px solid var(--rule);padding-bottom:5px;margin:28px 0 10px;}
.ety-hit{display:grid;grid-template-columns:auto 1fr auto;gap:14px;align-items:baseline;padding:8px 0;border-bottom:1px dotted #e7dcc4;}
.ety-hit .pf2{font-size:19px;} .ety-hit .pf2::before{content:"*";color:var(--accent);}
.ety-hit .pg2{font-variant:small-caps;color:var(--soft);}
.ety-hit .tagn{font-family:"Fraunces",serif;font-size:12px;color:var(--mut);}
.rx-hit{display:grid;grid-template-columns:180px 1fr 1fr;gap:14px;align-items:baseline;padding:6px 0;border-bottom:1px dotted #e7dcc4;font-size:15px;}
.rx-hit .lang{color:var(--soft);font-size:13.5px;}
.rx-hit .via{font-size:12.5px;color:var(--mut);text-align:right;}

/* thesaurus */
.thes ul{list-style:none;padding:0;margin:0;}
.thes li{border-bottom:1px solid var(--rule);}
.thes li a.row{display:flex;align-items:baseline;gap:12px;padding:11px 6px;background:none;}
.thes li a.row:hover{background:var(--paper2);}
.thes .sk{font-family:"Fraunces",serif;font-size:13px;color:var(--mut);width:64px;flex:none;}
.thes .ti{font-size:18px;}
.thes .ct{margin-left:auto;font-size:12px;color:var(--mut);font-variant:small-caps;letter-spacing:.05em;}
.thes .ety-list{margin-top:18px}

/* etymon connections / mesoroots / language+source pages */
.pagetitle{font-family:"Fraunces",serif;font-weight:600;font-size:38px;line-height:1.08;margin:6px 0 4px;}
.conn,.meso{margin:24px 0 8px;}
.conn-row{display:flex;align-items:baseline;gap:12px;padding:6px 0;border-bottom:1px dotted #e7dcc4;}
.conn-row:last-child{border-bottom:none}
.rl{font-variant:small-caps;letter-spacing:.09em;font-size:12px;color:var(--accent);width:80px;flex:none;}
.rfx a.lang,.rfx a.src{background:none;border-bottom:1px dotted var(--rule);}
.rfx a.lang{color:var(--soft);}
.rfx a.lang:hover,.rfx a.src:hover{color:var(--accent);border-color:var(--accent);}
.metabar a{background:none;border-bottom:1px dotted var(--rule);}
.metabar a:hover{color:var(--accent);}

/* contribution form + diff */
.editlink{background:var(--accent);color:var(--paper);padding:2px 10px;border-radius:2px;margin-left:10px;
  font-variant:small-caps;letter-spacing:.05em;font-size:13px;}
.editlink:hover{color:var(--paper);background:#7e201b;}
.editlink.gh{background:var(--ink);} .editlink.gh:hover{background:#000;}
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
.editform button:hover{background:#7e201b;}
.editform .cancel{background:none;color:var(--mut);}
.gate{padding:10px 16px;border-radius:2px;margin:16px 0;font-size:15px;}
.gate.ok{background:#e8f0e3;border-left:3px solid #4a7c3a;color:#2f4f25;}
.gate.bad{background:#f6e3e0;border-left:3px solid var(--accent);color:#7e201b;}
.gate ul{margin:6px 0 0 18px;}
pre.diff{background:#faf7ef;border:1px solid var(--rule);border-radius:3px;padding:14px 16px;overflow:auto;
  font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:13px;line-height:1.5;}
pre.diff span{display:block;white-space:pre-wrap;}
pre.diff .add{background:#e3f0db;color:#2f4f25;}
pre.diff .del{background:#f6dfdb;color:#7e201b;}
pre.diff .hdr{color:var(--mut);}
"""

def page(title, body, q=""):
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
  <nav class="main">
    <a href="/thesaurus">Thesaurus</a>
    <a href="/search?q=*">Reconstructions</a>
  </nav>
  <form class="hsearch" action="/search" method="get">
    <input name="q" placeholder="search…" value="{esc(q)}" autocomplete="off">
  </form>
</header>
<main>{body}</main>
<footer>
  Rebuilt from the STEDT v1.0 public release (2017). A prototype reimagining of the
  Sino-Tibetan Etymological Dictionary &amp; Thesaurus, originally compiled at UC Berkeley
  under James A. Matisoff. Etymon numbers are preserved for citation.
</footer>
</body></html>"""

# ---------------------------------------------------------------- views
def home():
    c = con()
    n = lambda s: c.execute(s).fetchone()[0]
    ety = n("SELECT count(*) FROM etyma e WHERE coalesce(upper(e.status),'')!='DELETE'")
    rfx = n("SELECT count(*) FROM lexicon")
    lgs = n("SELECT count(DISTINCT ln.language) FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid WHERE ln.language!=''")
    src = n("SELECT count(*) FROM srcbib")
    c.close()
    stat = lambda v,l: f'<div><div class="n">{v:,}</div><div class="l">{l}</div></div>'
    body = f"""
    <section class="hero">
      <h1>The roots of<br>Sino-Tibetan</h1>
      <p class="lede">An open, community-stewarded etymological dictionary and semantic
        thesaurus — {ety:,} reconstructions tying together {rfx:,} words across {lgs:,} languages.</p>
      <div class="bigsearch">
        <input id="bs" placeholder="Search a meaning, form, or language — e.g. “dog”, “lak”, “Lahu”" autocomplete="off">
        <div class="drop" id="drop"></div>
      </div>
      <div class="colophon">
        {stat(ety,"reconstructions")}{stat(rfx,"attested forms")}
        {stat(lgs,"languages")}{stat(src,"sources")}
      </div>
      <div class="entry">
        <a href="/thesaurus">Browse by meaning</a>
        <a href="/etymon/1764">A sample entry: ‘dog’</a>
      </div>
    </section>
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
    rows = c.execute("""SELECT ln.language AS language, l.lgid AS lgid, l.reflex AS form, l.gloss, l.gfn,
            g.grp AS subgroup, g.grpno AS groupnode, sb.citation AS citation, ln.srcabbr AS srcabbr, l.srcid
        FROM lx_et_hash h JOIN lexicon l ON l.rn=h.rn
        JOIN languagenames ln ON ln.lgid=l.lgid
        LEFT JOIN languagegroups g ON g.grpid=ln.grpid
        LEFT JOIN srcbib sb ON sb.srcabbr=ln.srcabbr
        WHERE h.tag=? GROUP BY l.rn""", (tag,)).fetchall()
    hptb = c.execute("""SELECT h.plg, h.protoform, h.protogloss, h.pages
        FROM et_hptb_hash x JOIN hptb h ON h.hptbid=x.hptbid WHERE x.tag=? ORDER BY x.ord""", (tag,)).fetchall()
    meso = c.execute("""SELECT g.grp AS subgroup, g.grpno AS groupnode, m.form, m.gloss, m.variant
        FROM mesoroots m LEFT JOIN languagegroups g ON g.grpid=m.grpid
        WHERE m.tag=? ORDER BY g.grpno, m.id""", (tag,)).fetchall()
    rel_tags = [int(v.strip()) for v in (e['allofams'], e['xrefs']) if v and v.strip().isdigit()]
    labels = {}
    if rel_tags:
        qm = ','.join('?' * len(rel_tags))
        for r in c.execute(f"SELECT tag,protoform,protogloss FROM etyma WHERE tag IN ({qm})", rel_tags):
            labels[r['tag']] = (r['protoform'], r['protogloss'])
    crumb = breadcrumb(c, e['semkey']); c.close()

    # group reflexes by subgroup, order by stammbaum (groupnode)
    groups = {}
    for r in rows:
        key = (r['groupnode'] or 'zz', r['subgroup'] or '—')
        groups.setdefault(key, []).append(r)
    gkeys = sorted(groups, key=lambda k: (natkey(k[0]), k[1]))
    nsub = len(gkeys)

    jump = ""
    if nsub > 6:
        jump = '<div class="jump">' + ''.join(
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
            rfx.append(f'<div class="rfx">{lang}<span class="form">{form} {g}</span>{src}</div>')
        sgs.append(f'<div class="sg" id="sg{i}"><h4>{esc(k[1])}<span class="c">{len(items)}</span></h4>'
                   + ''.join(rfx) + '</div>')

    noteshtml = ""
    if notes:
        noteshtml = ('<section class="notes"><h3>Notes</h3>'
                     + ''.join(f'<div class="note-block">{render_note(r["xmlnote"])}</div>' for r in notes)
                     + '</section>')

    # connections: HPTB reconstruction(s) + allofam / cross-references
    conn = []
    for h in hptb:
        conn.append(f'<div class="conn-row"><span class="rl">HPTB</span>'
                    f'<span><span class="lat">{esc(h["protoform"])}</span> ‘{esc(h["protogloss"])}’</span>'
                    f'<span class="src">pp. {esc(h["pages"])}</span></div>')
    def rel_link(v):
        v = (v or '').strip()
        if v.isdigit():
            lab = labels.get(int(v))
            txt = f'*{esc(lab[0])} ‘{esc(lab[1])}’' if lab else f'#{esc(v)}'
            return f'<a class="xref" href="/etymon/{v}">{txt}</a>'
        return f'<span>{esc(v)}</span>' if v else ''
    if e['allofams']: conn.append(f'<div class="conn-row"><span class="rl">Allofam</span>{rel_link(e["allofams"])}</div>')
    if e['xrefs']:    conn.append(f'<div class="conn-row"><span class="rl">See also</span>{rel_link(e["xrefs"])}</div>')
    connhtml = f'<section class="conn"><h3>Connections</h3>{"".join(conn)}</section>' if conn else ''

    mesohtml = ''
    if meso:
        mr = ''.join(f'<div class="rfx"><span class="lang">{esc(m["subgroup"] or "")}</span>'
                     f'<span class="form"><span class="recon">{esc(m["form"])}</span> '
                     f'<span class="g">{esc(m["gloss"])}</span></span><span class="src"></span></div>' for m in meso)
        mesohtml = f'<section class="meso"><h3>Intermediate reconstructions</h3>{mr}</section>'

    refs = f'<div class="cite">References: {esc(e["notes"])}</div>' if e['notes'] else ''
    pf = esc(e['protoform'])
    badges = ''
    if (e['status'] or '').upper() == 'DELETE': badges += '<span class="badge del">deleted</span>'
    if not e['public']: badges += '<span class="badge draft">unpublished</span>'
    body = f"""
    <div class="ety-head">
      <div class="plg">{esc(e['plg'])} · reconstruction #{e['tag']}{badges}</div>
      <div class="pf">{pf}</div>
      <div class="pg">{esc(e['protogloss'])}</div>
      <div class="crumbs">{crumb or esc(e['semkey'])}</div>
    </div>
    <div class="metabar">
      <span><b>{len(rows)}</b>reflexes</span>
      <span><b>{nsub}</b>subgroups</span>
    </div>
    <div class="cite">Cite as: <code>STEDT etymon #{e['tag']}, *{pf} ‘{esc(e['protogloss'])}’</code>.
      Stable link: <code>/etymon/{e['tag']}</code>
      <a class="editlink" href="/etymon/{e['tag']}/edit">✎ Suggest an edit</a>
      <a class="editlink gh" href="https://github.com/larc-iu/stedt/edit/main/data/etyma/{e['tag']}.yaml"
         target="_blank" rel="noopener">Edit on GitHub →</a></div>
    {refs}
    {connhtml}
    {noteshtml}
    {mesohtml}
    <section class="reflexes"><h3>Reflexes &amp; cognates</h3>
      {jump}
      {''.join(sgs)}
    </section>"""
    return page(f"*{e['protoform']} ‘{e['protogloss']}’", body), 200

def language(lgid):
    c = con()
    ln = c.execute("SELECT * FROM languagenames WHERE lgid=?", (lgid,)).fetchone()
    if not ln:
        c.close(); return page("Not found", "<p>No such language.</p>"), 404
    grp = c.execute("SELECT grp,plg FROM languagegroups WHERE grpid=?", (ln['grpid'],)).fetchone()
    src = c.execute("SELECT srcabbr,citation FROM srcbib WHERE srcabbr=?", (ln['srcabbr'],)).fetchone()
    total = c.execute("SELECT count(*) FROM lexicon WHERE lgid=?", (lgid,)).fetchone()[0]
    CAP = 500
    rows = c.execute("""SELECT l.reflex, l.gloss, l.gfn, l.semkey,
            (SELECT h.tag FROM lx_et_hash h WHERE h.rn=l.rn AND h.tag>0 LIMIT 1) AS tag
        FROM lexicon l WHERE l.lgid=? ORDER BY l.semkey, l.reflex LIMIT ?""", (lgid, CAP)).fetchall()
    c.close()
    meta = []
    if grp: meta.append(f'<span><b>subgroup</b> {esc(grp["grp"])}{ " (" + esc(grp["plg"]) + ")" if grp["plg"] else "" }</span>')
    if src and src['srcabbr']:
        meta.append(f'<span><b>source</b> <a href="/source/{esc(src["srcabbr"])}">{esc(src["citation"] or src["srcabbr"])}</a></span>')
    if ln['silcode']: meta.append(f'<span><b>ISO 639-3</b> {esc(ln["silcode"])}</span>')
    meta.append(f'<span><b>{total:,}</b> reflexes</span>')
    rfx = []
    for r in rows:
        link = f' <a class="via" href="/etymon/{r["tag"]}">› cognate</a>' if r['tag'] else ''
        form = esc(r['reflex']).replace('◦', '<span class="br">◦</span>')
        rfx.append(f'<div class="rfx"><span class="lang">{esc(r["semkey"])}</span>'
                   f'<span class="form">{form} <span class="g">{esc(r["gloss"])}</span></span>'
                   f'<span class="src">{esc(r["gfn"] or "")}{link}</span></div>')
    cap = f'<p style="color:var(--mut)">Showing the first {CAP:,} of {total:,}.</p>' if total > CAP else ''
    body = f"""
    <div class="ety-head">
      <div class="plg">Language</div>
      <div class="pagetitle">{esc(ln['language'])}</div>
      <div class="metabar">{''.join(meta)}</div>
    </div>
    {cap}
    <section class="reflexes"><h3>Attested forms</h3>{''.join(rfx)}</section>"""
    return page(ln['language'], body), 200

def source(srcabbr):
    c = con()
    s = c.execute("SELECT * FROM srcbib WHERE srcabbr=?", (srcabbr,)).fetchone()
    if not s:
        c.close(); return page("Not found", "<p>No such source.</p>"), 404
    langs = c.execute("SELECT lgid,language FROM languagenames WHERE srcabbr=? AND language!='' ORDER BY language",
                      (srcabbr,)).fetchall()
    total = c.execute("""SELECT count(*) FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid
        WHERE ln.srcabbr=?""", (srcabbr,)).fetchone()[0]
    CAP = 500
    rows = c.execute("""SELECT l.reflex, l.gloss, ln.language, l.lgid, l.semkey,
            (SELECT h.tag FROM lx_et_hash h WHERE h.rn=l.rn AND h.tag>0 LIMIT 1) AS tag
        FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid
        WHERE ln.srcabbr=? ORDER BY ln.language, l.semkey LIMIT ?""", (srcabbr, CAP)).fetchall()
    c.close()
    cite = ' '.join(x for x in (s['author'], f"({s['year']})" if s['year'] else '', s['title']) if x)
    meta = []
    if s['imprint']: meta.append(f'<span><b>imprint</b> {esc(s["imprint"])}</span>')
    meta.append(f'<span><b>{len(langs)}</b> languages</span>')
    meta.append(f'<span><b>{total:,}</b> forms</span>')
    langlinks = ' · '.join(f'<a href="/language/{l["lgid"]}">{esc(l["language"])}</a>' for l in langs)
    rfx = []
    for r in rows:
        link = f' <a class="via" href="/etymon/{r["tag"]}">› cognate</a>' if r['tag'] else ''
        form = esc(r['reflex']).replace('◦', '<span class="br">◦</span>')
        rfx.append(f'<div class="rfx"><a class="lang" href="/language/{r["lgid"]}">{esc(r["language"])}</a>'
                   f'<span class="form">{form} <span class="g">{esc(r["gloss"])}</span></span>'
                   f'<span class="src">{esc(r["semkey"])}{link}</span></div>')
    cap = f'<p style="color:var(--mut)">Showing the first {CAP:,} of {total:,}.</p>' if total > CAP else ''
    body = f"""
    <div class="ety-head">
      <div class="plg">Source · {esc(s['srcabbr'])}</div>
      <div class="pagetitle">{esc(s['citation'] or s['srcabbr'])}</div>
      <div class="pg" style="font-variant:normal;font-size:16px;color:var(--soft);letter-spacing:0">{esc(cite)}</div>
      <div class="metabar">{''.join(meta)}</div>
    </div>
    <div style="margin:12px 0 4px;font-size:13.5px;color:var(--soft);line-height:1.9">{langlinks}</div>
    {cap}
    <section class="reflexes"><h3>Attested forms</h3>{''.join(rfx)}</section>"""
    return page(s['citation'] or s['srcabbr'], body), 200

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
    <p style="color:var(--soft)">This is what a maintainer would review. On the live site it would open a
    pull request against <code>data/etyma/{tag}.yaml</code>; CI runs the full <code>validate.py</code>, and a
    moderator approves or requests changes. <em>(Prototype: nothing was written — this previews the flow.)</em></p>
    {gate}
    <h3 style="font-variant:small-caps;letter-spacing:.1em;color:var(--accent);font-size:14px;border-bottom:1px solid var(--rule);padding-bottom:5px">The change</h3>
    <pre class="diff">{''.join(difflines)}</pre>
    <p><a href="/etymon/{tag}">← Back to the entry</a></p>"""
    return page(f"Proposed: #{tag}", body), 200

def fts_q(q):
    q = q.replace('"', ' ').strip()
    return '"%s"' % q if q else '""'

def search_data(q, limit=40):
    c = con()
    OK = "coalesce(upper(e.status),'')!='DELETE'"
    etyma = []
    if q == '*':
        etyma = c.execute(f"""SELECT e.tag, g.plg AS plg, e.protoform, e.protogloss, e.semkey
            FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
            WHERE {OK} ORDER BY e.tag LIMIT ?""", (limit,)).fetchall()
    elif q:
        like = f"%{q}%"
        etyma = c.execute(f"""SELECT e.tag, g.plg AS plg, e.protoform, e.protogloss, e.semkey
            FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
            WHERE {OK} AND (e.protogloss LIKE ? OR e.protoform LIKE ?)
            ORDER BY CASE WHEN upper(e.protogloss) LIKE upper(?)||'%' THEN 0 ELSE 1 END, e.protogloss
            LIMIT ?""", (like, like, q, limit)).fetchall()
    reflexes = []
    if q and q != '*':
        reflexes = c.execute("""SELECT l.reflex AS form, l.gloss, ln.language AS language, l.rn,
              e.tag AS tag, e.protoform AS pf, e.protogloss AS pg
            FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid
            LEFT JOIN lx_et_hash h ON h.rn=l.rn AND h.tag>0
            LEFT JOIN etyma e ON e.tag=h.tag
            WHERE l.rn IN (SELECT rn FROM lexicon_fts WHERE lexicon_fts MATCH ? LIMIT ?)
            GROUP BY l.rn LIMIT ?""", (fts_q(q), limit + 40, limit)).fetchall()
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
            out.append(f'<a class="ety-hit" href="/etymon/{e["tag"]}" style="background:none">'
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
        out.append('<p style="color:var(--mut)">No matches.</p>')
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
        body.append('<p style="color:var(--mut);margin:0 0 22px">Browse meanings from the most general to the most specific.</p>')
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
                body.append(f'<div class="ety-hit"><a href="/etymon/{e["tag"]}" class="pf2 lat" style="background:none">{esc(e["protoform"])}</a>'
                            f'<span class="pg2">{esc(e["protogloss"])}</span>'
                            f'<span class="tagn">{esc(e["plg"])} #{e["tag"]}</span></div>')
            body.append('</div>')
    c.close()
    body.append('</div>')
    return page("Thesaurus" + (f": {semkey}" if semkey else ""), ''.join(body))

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
            elif path == "/api/search":
                lim = int(qs.get("limit", ["10"])[0])
                et, rx = search_data(q, lim)
                self.send(json.dumps({
                    "etyma": [dict(r) for r in et],
                    "reflexes": [{"form": r["form"], "gloss": r["gloss"], "language": r["language"], "tag": r["tag"]} for r in rx],
                }), ctype="application/json")
            elif path == "/search":
                self.send(search_page(q))
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
