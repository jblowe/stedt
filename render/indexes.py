"""Index/browse pages: home, about, reconstructions, languages, sources, search, thesaurus."""
import re
import json

from .config import CITE_BASE, PREVIEW
from .db import con, reflex_semkey_counts
from .text import esc, alt, natkey, rcount_txt
from .notes import render_note
from .shell import page, breadcrumb, reflex_counts, canon_lgid

# ---------------------------------------------------------------- views
def home():
    banner = ('<div class="preview-banner" style="background:var(--accent);color:var(--paper);'
              'padding:14px 20px;border-radius:3px;margin:0 0 22px;font-size:15px;line-height:1.55">'
              '<b>Preview.</b> Data and features are incomplete and may change.</div>'
              ) if PREVIEW else ""
    body = banner + """
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
    const B=window.STEDT_BASE||'';
    const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
    const altstar=s=>String(s).replace(/^\\s*\\*\\s*/,'').replace(/⪤\\s*\\*?/g,'⪤ *');
    const bs=document.getElementById('bs'),d=document.getElementById('drop');let t;
    const note=m=>{d.innerHTML='<div class="cap" style="padding:10px 12px">'+m+'</div>';d.style.display='block';};
    bs.addEventListener('input',()=>{clearTimeout(t);const q=bs.value.trim();
      if(q.length<2){d.style.display='none';return;}
      t=setTimeout(async()=>{
        if(!window.stedtSearch){return;}
        if(!window.stedtDbLoaded)note('Loading search…');
        let j;try{j=await window.stedtSearch(q,8);}catch(e){note('Search is unavailable.');return;}
        let h='';
        (j.languages||[]).forEach(x=>h+=`<a href="${B}/language/${x.lgid}"><span class="k">lang</span><span>${esc(x.language)}</span></a>`);
        j.etyma.forEach(e=>h+=`<a href="${B}/etymon/${e.tag}"><span class="k">recon</span><span><span class="recon">${altstar(esc(e.protoform))}</span> · <span class="gl">${esc(e.protogloss)}</span></span></a>`);
        j.reflexes.forEach(x=>h+=`<a href="${x.tag?B+'/etymon/'+x.tag:B+'/language/'+x.lgid+'#rn'+x.rn}"><span class="k">${esc(x.language)}</span><span><span class="lat">${esc(x.form)}</span> <span class="gl">${esc(x.gloss)}</span>${x.gfn?` <span class="pos">${esc(x.gfn)}</span>`:''}</span></a>`);
        d.innerHTML=h;d.style.display=h?'block':'none';},180);});
    bs.addEventListener('keydown',e=>{if(e.key==='Enter')location=B+'/search?q='+encodeURIComponent(bs.value);});
    document.addEventListener('click',e=>{if(!e.target.closest('.bigsearch'))d.style.display='none';});
    </script>"""
    return page("Home", body)

def about():
    c = con()
    n = lambda s: c.execute(s).fetchone()[0]
    ety = n("SELECT count(*) FROM etyma e WHERE coalesce(upper(e.status),'')!='DELETE'")
    rfx = n("SELECT count(*) FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid WHERE ln.language NOT LIKE '*%'")
    # count a "language" as a lect = (name, subgroup), matching the Languages index header and the
    # canonicalization (a name spanning two subgroups, e.g. Lahu (Red), is two lects) — not bare name.
    lgs = n("""SELECT count(*) FROM (SELECT 1 FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid
        WHERE ln.language!='' AND ln.language NOT LIKE '*%' GROUP BY ln.language, ln.grpid)""")
    src = n("""SELECT count(*) FROM srcbib sb WHERE EXISTS(
        SELECT 1 FROM languagenames ln JOIN lexicon l ON l.lgid=ln.lgid WHERE ln.srcabbr=sb.srcabbr)""")
    c.close()
    stat = lambda v, l: f'<div><div class="n">{v:,}</div><div class="l">{l}</div></div>'
    abbr = [("ST", "Sino-Tibetan"), ("TB", "Tibeto-Burman"), ("PTB", "Proto-Tibeto-Burman"),
            ("HPTB", "Matisoff (2003), <i>Handbook of Proto-Tibeto-Burman</i>"),
            ("STC", "Benedict (1972), <i>Sino-Tibetan: A Conspectus</i>"),
            ("PLB", "Proto-Lolo-Burmese"), ("PKC", "Proto-Kuki-Chin"), ("PTani", "Proto-Tani")]
    abbrhtml = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in abbr)
    body = f"""
    <div class="ety-head">
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
      <p>Each entry has a stable address of the form <code>{esc(CITE_BASE)}/etymon/&lt;number&gt;</code>,
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

# Shared windowed-list engine for the big client-rendered lists (reconstructions index, search
# results, thesaurus attestations). Rows still render in CHUNK-sized batches to keep the DOM light,
# but a trailing spacer reserves the whole list's (over)estimated height up front — so the
# scrollbar reflects the FULL dataset from first paint instead of growing as you scroll. Scrolling
# toward the end renders the rows that belong there in one batch, so dragging the bar to the bottom
# lands on the last rows at once. The height estimate is biased high on purpose (MARGIN): real
# content then only ever settles UP toward a bar you've dragged down, never grows past it. Plain
# constant (literal { }); embedded inline on each page so it runs before its page script, with no
# extra request and no module load-order dependency.
_WINDOWED_JS = """
function windowedList(list, opts){
  opts=opts||{};
  var CHUNK=opts.chunk||200, row=opts.row, MARGIN=opts.margin||1.15, BUFFER=600;
  var data=[], shown=0, rowH=0;
  var spacer=document.createElement('div');
  spacer.className='wl-spacer'; spacer.setAttribute('aria-hidden','true');
  list.parentNode.insertBefore(spacer, list.nextSibling);
  function resize(){                         // reserve (over)estimated height for the unrendered tail
    var rem=data.length-shown;
    spacer.style.height=(rem>0&&rowH>0)?Math.ceil(rem*rowH*MARGIN)+'px':'';
  }
  function renderTo(target){                 // render rows [shown,target) in a single batch
    if(target>data.length) target=data.length;
    if(target>shown){
      var h='';
      for(var i=shown;i<target;i++) h+=row(data[i]);
      list.insertAdjacentHTML('beforeend',h);
      shown=target;
      if(list.offsetHeight>0) rowH=list.offsetHeight/shown;   // running average; adapts to wrap/zoom
    }
    resize();
    if(opts.onRender) opts.onRender(shown,data.length);
  }
  function fill(){                           // render until rendered rows cover the viewport (+buffer)
    var vh=window.innerHeight||document.documentElement.clientHeight, guard=0;
    while(shown<data.length && guard++<4000){
      var top=spacer.getBoundingClientRect().top;   // boundary between real rows and the reserve
      if(top>=vh+BUFFER) break;
      var step=CHUNK;
      if(rowH>0){var need=Math.ceil((vh+BUFFER-top)/rowH); if(need>step) step=need;}
      renderTo(shown+step);
    }
  }
  function reset(newData){                    // (re)bind data, e.g. after an in-page filter change
    data=newData||[]; shown=0; list.innerHTML='';
    renderTo(CHUNK); fill();
  }
  var queued=false;
  function onScroll(){
    if(queued) return; queued=true;
    requestAnimationFrame(function(){queued=false; fill();});
  }
  window.addEventListener('scroll', onScroll, {passive:true});
  window.addEventListener('resize', onScroll, {passive:true});
  return {reset:reset, fill:fill};
}
"""

def reconstructions():
    # The whole list (~4k etyma) is shipped once as compact JSON and rendered
    # client-side in windows of CHUNK rows, with an instant in-page filter. This
    # keeps the initial DOM small (~200 nodes vs ~31k) on slow devices while the
    # gloss-ordered full set stays a single, filterable, statically-hosted page.
    c = con()
    OK = "coalesce(upper(e.status),'')!='DELETE'"
    rows = c.execute(f"""SELECT e.tag, e.protoform, e.protogloss, g.plg AS plg
        FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
        WHERE {OK} ORDER BY e.protogloss, e.tag""").fetchall()
    counts = reflex_counts(c)
    c.close()
    total = len(rows)
    data = [[r["tag"], alt(r["protoform"] or ""), r["protogloss"] or "", r["plg"] or "",
             counts.get(r["tag"], 0)] for r in rows]
    # < keeps the payload from breaking out of the <script> tag and stays valid JSON.
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("<", "\\u003c")
    body = f"""
    <div class="ety-head">
      <div class="pagetitle">Reconstructions</div>
      <div class="metabar"><span><b>{total:,}</b> etyma</span><span>ordered by gloss</span></div>
    </div>
    <div class="rbar">
      <input id="rfilter" type="search" placeholder="Filter by form, gloss, group, or tag…" autocomplete="off" autofocus>
      <span class="rcount" id="rcount"></span>
    </div>
    <div id="recon-list"></div>
    <p class="rnone">No reconstructions match your filter.</p>
    <noscript><p class="cap">Enable JavaScript to browse and filter all reconstructions, or use
      <a href="/search">search</a>. Each etymon also has its own page, linked from the
      <a href="/thesaurus">thesaurus</a> and <a href="/languages">language</a> indexes.</p></noscript>
    <script id="recon-data" type="application/json">{payload}</script>
    <script>""" + _WINDOWED_JS + """
    (function(){
      var B=window.STEDT_BASE||'';
      var esc=function(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
        return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});};
      var norm=function(s){return String(s==null?'':s).toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'');};
      var DATA=JSON.parse(document.getElementById('recon-data').textContent);
      for(var i=0;i<DATA.length;i++){var r=DATA[i];r[5]=norm(r[1]+' '+r[2]+' '+r[3]+' #'+r[0]);}
      var view=DATA;
      var list=document.getElementById('recon-list'),
          none=document.querySelector('.rnone'),
          count=document.getElementById('rcount'),
          input=document.getElementById('rfilter');
      function row(r){var rc=r[4]?(' · '+r[4]+(r[4]==1?' reflex':' reflexes')):'';
        return '<a class="ety-hit" href="'+B+'/etymon/'+r[0]+'">'+
        '<span class="pf2 lat">'+esc(r[1])+'</span>'+
        '<span class="pg2">'+esc(r[2])+'</span>'+
        '<span class="tagn">'+esc(r[3])+' #'+esc(r[0])+rc+'</span></a>';}
      function updateCount(shown){
        var t=DATA.length, m=view.length;
        var s=(m===t)?t.toLocaleString()+' etyma':m.toLocaleString()+(m===1?' match':' matches');
        if(shown<m) s+=' · '+shown.toLocaleString()+' shown';
        count.textContent=s;
      }
      var win=windowedList(list,{row:row,onRender:function(shown){
        updateCount(shown); none.style.display=view.length?'none':'block';}});
      function apply(){
        var q=norm(input.value.trim());
        view=q?DATA.filter(function(r){return r[5].indexOf(q)>=0;}):DATA;
        win.reset(view);
      }
      var tmr; input.addEventListener('input',function(){clearTimeout(tmr);tmr=setTimeout(apply,90);});
      win.reset(DATA);
    })();
    </script>"""
    return page("Reconstructions", body, nav="reconstructions")

def languages_index():
    c = con()
    # every genetic-classification node, so headline subgroups (Lolo-Burmese, Bodo-Garo, Tani, …)
    # and the two "previously published reconstructions" groups appear as headings even when no
    # member language is directly attested under them.
    allgroups = c.execute(
        "SELECT grpid, grpno, grp, plg FROM languagegroups WHERE grpid IS NOT NULL").fetchall()
    rows = c.execute("""SELECT ln.grpid AS grpid, ln.language AS language, ln.lgid AS lgid, count(*) AS n
        FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid
        WHERE ln.language NOT LIKE '*%'
        GROUP BY ln.lgid""").fetchall()
    c.close()
    members, ntot = {}, 0   # grpid -> {language name: (lgid, max reflex count)}
    for r in rows:
        nm = r['language'] or ''
        if not nm: continue
        d = members.setdefault(r['grpid'], {})
        cur = d.get(nm)
        if cur is None or r['n'] > cur[1]:
            d[nm] = (r['lgid'], r['n'])
    for d in members.values(): ntot += len(d)

    def block(grpno, grp, plg, grpid, langs):
        depth = str(grpno).count('.') if grpno else 0
        code = f'<span class="grpno">{esc(grpno)}</span>' if grpno else ''
        head = code + esc(grp or '—') + (f' <span class="plg2">({esc(plg)})</span>' if plg else '')
        gid = f' id="g{grpid}"' if grpid is not None else ''
        headhtml = (f'<a href="/group/{grpid}">{head}</a>' if grpid is not None else head)
        items = ''.join(f'<li><a href="/language/{canon_lgid(lid)}">{esc(nm)}</a></li>'
                        for nm, (lid, _) in sorted(langs.items(), key=lambda kv: kv[0].lower()))
        idx = f'<ul class="idx">{items}</ul>' if items else ''
        return (f'<div class="grpblock" style="margin-left:{depth*18}px">'
                f'<h4 class="grp"{gid}>{headhtml}</h4>{idx}</div>')

    out = ['<div class="ety-head"><div class="pagetitle">Languages</div>',
           f'<div class="metabar"><span><b>{ntot:,}</b> languages</span><span>by genetic subgroup</span></div></div>']
    for g in sorted(allgroups, key=lambda g: natkey(g['grpno'])):
        out.append(block(g['grpno'], g['grp'], g['plg'], g['grpid'], members.get(g['grpid'], {})))
    # any attested language whose grpid isn't a known classification node (incl. NULL) stays reachable
    known = {g['grpid'] for g in allgroups}
    leftover = {}
    for gid, d in members.items():
        if gid not in known:
            leftover.update(d)
    if leftover:
        out.append(block(None, 'Unclassified', '', None, leftover))
    return page("Languages", ''.join(out), nav="languages")

def sources_index():
    c = con()
    rows = c.execute("""SELECT sb.srcabbr AS srcabbr, sb.citation AS citation, sb.author AS author,
            sb.year AS year, sb.title AS title, sb.imprint AS imprint,
            count(DISTINCT CASE WHEN l.rn IS NOT NULL AND ln.language NOT LIKE '*%' AND ln.language!='' THEN ln.lgid END) AS nlang,
            count(CASE WHEN ln.language NOT LIKE '*%' AND ln.language!='' THEN l.rn END) AS nforms
        FROM srcbib sb
        LEFT JOIN languagenames ln ON ln.srcabbr=sb.srcabbr
        LEFT JOIN lexicon l ON l.lgid=ln.lgid
        WHERE coalesce(sb.srcabbr,'')!=''
        GROUP BY sb.srcabbr
        ORDER BY lower(coalesce(nullif(sb.author,''),nullif(sb.citation,''),sb.srcabbr)), sb.year""").fetchall()
    c.close()
    def refstr(s):
        # full reference incl. the publication imprint (journal/issue/pages or publisher),
        # so the venue is visible at a glance instead of only on the detail page.
        au = (s['author'] or '').rstrip()
        if au and not au.endswith('.'): au += '.'
        base = ' '.join(x for x in (au, f"{s['year']}." if s['year'] else '', s['title']) if x)
        if s['imprint']:
            sep = '' if base.rstrip().endswith('.') else '.'   # avoid "Title.. Imprint"
            base = (base.rstrip() + sep + ' ' + s['imprint']) if base else s['imprint']
        return base
    data = [s for s in rows if s['nforms']]
    refonly = [s for s in rows if not s['nforms']]

    def li(s):
        cit = esc(s['citation'] or s['srcabbr'])
        ref = esc(refstr(s))
        refhtml = f'<span class="srcref">{ref}</span>' if ref and ref != cit else ''
        au = esc((s['author'] or s['citation'] or s['srcabbr'] or '').lower())
        return (f'<li data-author="{au}" data-forms="{s["nforms"]}" data-langs="{s["nlang"]}">'
                f'<a href="/source/{esc(s["srcabbr"])}">{cit}</a>{refhtml}'
                f'<span class="srccnt">{s["nforms"]:,} forms · {s["nlang"]} languages</span></li>')
    main = ''.join(li(s) for s in data)
    refitems = ''.join(
        f'<li><a href="/source/{esc(s["srcabbr"])}">{esc(s["citation"] or s["srcabbr"])}</a> '
        f'<span class="srcref">{esc(refstr(s))}</span></li>' for s in refonly)
    refblock = (f'<details class="seg" style="margin-top:24px"><summary>Reference-only sources'
                f'<span class="c">{len(refonly)}</span></summary>'
                f'<p class="cap">Cited in the literature but with no attested forms held in STEDT.</p>'
                f'<ul class="idx">{refitems}</ul></details>') if refonly else ''
    total_forms = sum(s['nforms'] for s in data)
    sortctl = ('<div class="srcsort">Sort <select id="srcsort" aria-label="Sort sources">'
               '<option value="author">by author</option>'
               '<option value="forms">most forms</option>'
               '<option value="langs">most languages</option></select></div>')
    sort_js = """
    <script>
    (function(){
      var sel=document.getElementById('srcsort'),ul=document.getElementById('srclist');
      if(!sel||!ul)return;
      var items=[].slice.call(ul.children);
      sel.addEventListener('change',function(){
        var k=sel.value;
        items.sort(function(a,b){
          if(k==='author'){var x=a.getAttribute('data-author'),y=b.getAttribute('data-author');
            return x<y?-1:x>y?1:0;}
          return (+b.getAttribute('data-'+k)||0)-(+a.getAttribute('data-'+k)||0);
        });
        var f=document.createDocumentFragment();
        items.forEach(function(li){f.appendChild(li);});
        ul.appendChild(f);
      });
    })();
    </script>"""
    body = (f'<div class="ety-head"><div class="pagetitle">Sources</div>'
            f'<div class="metabar"><span><b>{len(data):,}</b> sources with data</span>'
            f'<span><b>{total_forms:,}</b> forms</span></div></div>'
            f'{sortctl}<ul class="srcidx" id="srclist">{main}</ul>{refblock}{sort_js}')
    return page("Sources", body, nav="sources")

def search_page(q=""):
    """Static results shell — reads ?q= and renders matches client-side via window.stedtSearch,
    federated across entity types (languages / reconstructions / attested forms), each with its
    true total count and windowed infinite-scroll, so results are never silently capped."""
    body = """
    <div class="sr">
      <div class="bigsearch" style="margin:0 0 22px"><input id="bs" placeholder="Search a meaning, form, or language…" autocomplete="off"></div>
      <h2 id="srh">Search</h2>
      <div id="srsub" class="sub"></div>
      <div id="results"></div>
    </div>
    <script>""" + _WINDOWED_JS + """
    const B=window.STEDT_BASE||'';
    const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
    const altstar=s=>String(s).replace(/^\\s*\\*\\s*/,'').replace(/⪤\\s*\\*?/g,'⪤ *');
    const fmt=n=>Number(n).toLocaleString();
    const CHUNK=200;
    const bs=document.getElementById('bs');
    bs.addEventListener('keydown',e=>{if(e.key==='Enter')location=B+'/search?q='+encodeURIComponent(bs.value);});
    const etyRow=e=>`<a class="ety-hit" href="${B}/etymon/${e.tag}"><span class="pf2 lat">${altstar(esc(e.protoform))}</span><span class="pg2">${esc(e.protogloss)}</span><span class="tagn">${esc(e.plg)} #${e.tag}${e.nreflex?` · ${fmt(e.nreflex)} reflex${e.nreflex==1?'':'es'}`:''}</span></a>`;
    // --- per-syllable etymon links (faithful port of the original SylStation.syllabify) ---
    // Syllabify a form the way the data was tagged so lx_et_hash.ind (syllable position -> etymon)
    // aligns; tagged syllables then link to their etymon. Char classes [(] [)] [|] stand in for the
    // escaped \\( \\) \\| to keep this readable inside the page string.
    const _TONE="⁰¹²³⁴⁵⁶⁷⁸0-9ˊˋ˥-˩";
    const _DELIM="-=≡≣+.,;/~◦⪤()↮ ";
    const _HIDE=new RegExp('[(]([^'+_DELIM+_TONE+']+)[)]','g');
    const _START=new RegExp('^(['+_DELIM+']+)');
    const _REPOST="([^"+_DELIM+_TONE+"]+["+_TONE+"]+(?:[|]$)?)(["+_DELIM+"]*)";
    const _REPRE="(["+_TONE+"]{1,2}[^"+_DELIM+_TONE+"]+)(["+_DELIM+"]*)";
    const _REDEL="([^"+_DELIM+"]+)(["+_DELIM+"]*)";
    function _syl1(s,reSrc){
      s=s.replace(_HIDE,'（$1）'); let prefix='';
      if(_START.test(s)){const pm=_START.exec(s);prefix=pm[1];s=s.substring(prefix.length);}
      const syls=[],dl=[]; const re=new RegExp("^"+reSrc); let m;
      while((m=re.exec(s))&&m[0].length){
        s=s.substring(m[0].length);
        if(m[1].indexOf('|')!==-1&&syls.length){
          syls[syls.length-1]+=dl.pop();
          syls[syls.length-1]+=m[1].replace(/（/g,'(').replace(/）/g,')').replace('|','');
        }else{syls.push(m[1].replace(/（/g,'(').replace(/）/g,')'));}
        dl.push(m[2]);
      }
      if(!syls[0])syls[0]='';
      if(s)syls[syls.length-1]+=s;
      return {syls,dl,prefix,ok:!s.length};
    }
    function syllabify(s){
      let r=_syl1(s,_REPOST);
      if(!r.ok){r=_syl1(s,_REPRE);if(!r.ok)r=_syl1(s,_REDEL);}
      return r;
    }
    const sylLink=r=>{                     // syllable-linked form HTML, or null to fall back
      if(!r.syn)return null;
      const sy=syllabify(String(r.form||'')),syls=sy.syls,dl=sy.dl;
      for(const k in r.syn){if(+k>=syls.length)return null;}   // tags must land on real syllables
      let out=esc(sy.prefix||'');
      for(let i=0;i<syls.length;i++){
        out+=(r.syn[i]!=null
          ? `<a class="syl" href="${B}/etymon/${r.syn[i]}">${esc(syls[i])}</a>`
          : esc(syls[i]))
          + esc(dl[i]||'').replace(/◦/g,'<span class="br">◦</span>');
      }
      return out;
    };
    const rfxRow=r=>{
      const home=`${B}/language/${r.lgid}#rn${r.rn}`;
      const src=r.srcabbr?`<a href="${B}/source/${esc(r.srcabbr)}">${esc(r.citation||r.srcabbr)}</a>`:'';
      const pos=r.gfn?` <span class="pos">${esc(r.gfn)}</span>`:'';
      // the gloss is styled (italic·soft) so it reads distinct without quotes; a note dotted-
      // underlines it and reveals on hover/focus (rather than an always-on line)
      const gl=r.note
        ? `<span class="g noted" tabindex="0">${esc(r.gloss)}<span class="notepop" role="note">${esc(r.note)}</span></span>`
        : `<span class="g">${esc(r.gloss)}</span>`;
      const lf=sylLink(r); let mid, lang;
      if(lf){                              // syllables carry the etymon links; the name carries #rn
        lang=`<a class="lang" href="${home}">${esc(r.language)}</a>`;
        mid=`<span class="lat">${lf}</span> ${gl}${pos}`;
      }else{                               // form links to its attestation (#rn); trailing via chips
        lang=`<span class="lang">${esc(r.language)}</span>`;
        const links=(r.etyma&&r.etyma.length)?` <span class="vias">${r.etyma.map(x=>`<a class="via" href="${B}/etymon/${x.tag}">› *${altstar(esc(x.pf))}</a>`).join(' ')}</span>`:'';
        mid=`<a href="${home}"><span class="lat">${esc(r.form)}</span></a> ${gl}${pos}${links}`;
      }
      return `<div class="rx-hit">${lang}<span class="rx-mid">${mid}</span><span class="rx-src">${src}</span></div>`;
    };
    // attested-form rows are pre-sorted by subgroup; emit a Stammbaum-subgroup header when it changes
    let _rxsub=null;
    const rfxGrouped=r=>{
      const key=(r.grpno||'')+'|'+(r.subgroup||'');
      let head='';
      if(key!==_rxsub){_rxsub=key;const code=r.grpno?`<span class="grpno">${esc(r.grpno)}</span>`:'';
        head=`<div class="rx-sub">${code}${esc(r.subgroup||'(unclassified)')}</div>`;}
      return head+rfxRow(r);
    };
    const langRow=x=>`<a class="ety-hit" href="${B}/language/${x.lgid}"><span class="rf">${esc(x.language)}</span><span class="gl2">${fmt(x.n)} attested form${x.n==1?'':'s'}</span><span class="tagn">language</span></a>`;
    function sectionLabel(title,total,fetched){
      let h='<div class="sec-label">'+esc(title)+'<span class="sec-n">'+fmt(total);
      if(fetched<total) h+=' · first '+fmt(fetched)+' shown';
      return h+'</span></div>';
    }
    function windowed(host,data,rowFn){
      const list=document.createElement('div'); host.appendChild(list);
      windowedList(list,{chunk:CHUNK,row:rowFn}).reset(data);
    }
    function block(title,total,data,rowFn){
      const res=document.getElementById('results');
      res.insertAdjacentHTML('beforeend',sectionLabel(title,total,data.length));
      const host=document.createElement('div'); res.appendChild(host);
      windowed(host,data,rowFn);
    }
    async function run(){
      const q=(new URLSearchParams(location.search).get('q')||'').trim();
      bs.value=q;
      const srh=document.getElementById('srh'),sub=document.getElementById('srsub'),res=document.getElementById('results');
      if(!q){srh.textContent='Search';return;}
      srh.textContent='Results for '+(q==='*'?'all reconstructions':'“'+q+'”');
      if(!window.stedtSearch)return;
      if(!window.stedtDbLoaded)res.innerHTML='<p class="cap">Loading search…</p>';
      let r;
      try{r=await window.stedtSearch(q,null);}
      catch(err){res.innerHTML='<p class="cap">Search is unavailable.</p>';return;}
      const parts=[];
      if(r.languageTotal) parts.push(fmt(r.languageTotal)+' language'+(r.languageTotal==1?'':'s'));
      parts.push(fmt(r.etymaTotal)+' reconstruction'+(r.etymaTotal==1?'':'s'));
      parts.push(fmt(r.reflexTotal)+' attested form'+(r.reflexTotal==1?'':'s'));
      sub.textContent=parts.join(' · ');
      res.innerHTML='';
      if(r.languageTotal) block('Languages',r.languageTotal,r.languages,langRow);
      if(r.etymaTotal) block('Reconstructions',r.etymaTotal,r.etyma,etyRow);
      if(r.reflexTotal){_rxsub=null;block('Attested forms',r.reflexTotal,r.reflexes,rfxGrouped);}
      if(!r.languageTotal&&!r.etymaTotal&&!r.reflexTotal) res.innerHTML='<p class="cap">No matches.</p>';
    }
    window.addEventListener('DOMContentLoaded',run);
    </script>"""
    return page("Search", body, q)

# Legacy files an etymon under its (more specific) `chapter`; `semkey` is only a fallback for
# the lone live etymon whose chapter doesn't resolve. Used for thesaurus placement + counts.
ECAT = "coalesce(nullif(e.chapter,''),e.semkey)"

# Windowed list for a thesaurus page's "Attestations". On page load it queries the search WASM
# DB (window.stedtFormsByCategory, set by /assets/stedt-search.js) for every reflex filed at
# this node's semkey(s), then renders in 200-row windows with an in-memory filter and
# infinite-scroll — so a 13k-form category stays a light DOM. No Python interpolation here
# (keys ride in via data-semkeys), so it's a plain constant: literal { } need no escaping.
_CATFORMS_JS = """
<script>
""" + _WINDOWED_JS + """
(function(){
  var wrap=document.querySelector('.catwrap'); if(!wrap) return;
  var B=window.STEDT_BASE||'';
  var esc=function(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});};
  var norm=function(s){return String(s==null?'':s).toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'');};
  var altstar=function(s){return String(s).replace(/^\\s*\\*\\s*/,'').replace(/⪤\\s*\\*?/g,'⪤ *');};
  var list=wrap.querySelector('.catlist'),
      count=wrap.querySelector('.catcount'),
      input=wrap.querySelector('.catfilter');
  var DATA=null, view=[], loaded=false, loading=false;
  function row(r){
    var home=B+'/language/'+r.lgid+'#rn'+r.rn;
    var gl=r.note?'<span class="g noted" tabindex="0">'+esc(r.gloss)+'<span class="notepop" role="note">'+esc(r.note)+'</span></span>':'<span class="g">'+esc(r.gloss)+'</span>';
    var pos=r.gfn?' <span class="pos">'+esc(r.gfn)+'</span>':'';
    var via=(r.etyma&&r.etyma.length)?' <span class="vias">'+r.etyma.map(function(x){
      return '<a class="via" href="'+B+'/etymon/'+x.tag+'">› *'+altstar(esc(x.pf))+'</a>';}).join(' ')+'</span>':'';
    var src=r.srcabbr?'<a href="'+B+'/source/'+esc(r.srcabbr)+'">'+esc(r.citation||r.srcabbr)+'</a>':'';
    return '<div class="rx-hit"><a class="lang" href="'+home+'">'+esc(r.language)+'</a>'+
      '<span class="rx-mid"><a class="lat" href="'+home+'">'+esc(r.reflex)+'</a> '+gl+pos+via+'</span>'+
      '<span class="rx-src">'+src+'</span></div>';
  }
  function updateCount(shown){
    if(!DATA){count.textContent='';return;}
    var t=DATA.length,m=view.length;
    var s=(m===t)?t.toLocaleString()+(t===1?' form':' forms')
                 :m.toLocaleString()+(m===1?' match':' matches')+' of '+t.toLocaleString();
    if(shown<m) s+=' · '+shown.toLocaleString()+' shown';
    count.textContent=s;
  }
  var win=windowedList(list,{row:row,onRender:function(shown){updateCount(shown);}});
  function apply(){
    var q=norm(input.value.trim());
    view=q?DATA.filter(function(r){return r._k.indexOf(q)>=0;}):DATA;
    win.reset(view);
  }
  function load(){
    if(loaded||loading) return; loading=true; count.textContent='Loading forms…';
    var keys; try{keys=JSON.parse(wrap.getAttribute('data-semkeys'));}catch(e){keys=[];}
    var go=function(){
      window.stedtFormsByCategory(keys).then(function(rows){
        DATA=rows||[];
        for(var i=0;i<DATA.length;i++){var r=DATA[i];r._k=norm(r.reflex+' '+r.gloss+' '+r.language);}
        view=DATA; loaded=true; loading=false; apply();
      }).catch(function(){count.textContent='Could not load forms.'; loading=false;});
    };
    var wait=function(n){
      if(window.stedtFormsByCategory) return go();
      if(n<=0){count.textContent='Search is unavailable.'; loading=false; return;}
      setTimeout(function(){wait(n-1);},150);
    };
    wait(40);
  }
  var tmr; input.addEventListener('input',function(){if(!loaded)return;clearTimeout(tmr);tmr=setTimeout(apply,90);});
  load();   // attestations are shown by default (no expand) — fetch on page load
})();
</script>"""

def thesaurus(semkey=None):
    c = con()
    body = ['<div class="thes">']
    if semkey:
        # The integer node N and the chapter N.0 are the same category-overview node;
        # treat /thesaurus/N.0 as an alias of /thesaurus/N so it doesn't render an empty,
        # self-referential ("The Body › The Body") page. An integer node also owns its N.0
        # chapter's notes and any etyma filed directly on N.0 (e.g. 10.0 has 10).
        if re.fullmatch(r'\d+\.0', semkey):
            semkey = semkey.split('.')[0]
        own = [semkey, semkey + '.0'] if '.' not in semkey else [semkey]
        ownph = ','.join('?' * len(own))
        title = c.execute("SELECT chaptertitle FROM chapters WHERE semkey=?", (semkey,)).fetchone()
        if not title and '.' not in semkey:
            title = c.execute("SELECT chaptertitle FROM chapters WHERE semkey=?", (semkey + '.0',)).fetchone()
        title = title[0] if title else semkey
        cnotes = c.execute(f"""SELECT xmlnote FROM notes WHERE id IN ({ownph}) AND spec='C'
                             AND xmlnote IS NOT NULL ORDER BY ord, noteid""", own).fetchall()
        body.append(f'<div class="crumbs"><a href="/thesaurus">Thesaurus</a> &nbsp;›&nbsp; {breadcrumb(c, semkey)}</div>')
        body.append(f'<h2 style="font-family:Fraunces;font-weight:600;font-size:30px;margin:10px 0 18px">{esc(title)}</h2>')
        if cnotes:
            body.append('<section class="notes">'
                        + ''.join(f'<div class="note-block">{render_note(r["xmlnote"])}</div>' for r in cnotes)
                        + '</section>')
        depth = len(semkey.split('.'))
        # Children at the next depth, minus the N.0 overview (it IS this integer node).
        kids = c.execute("""SELECT semkey,chaptertitle FROM chapters
            WHERE semkey LIKE ? AND (length(semkey)-length(replace(semkey,'.','')))=?
              AND semkey NOT LIKE '%.0'
            """, (semkey + '.%', depth)).fetchall()
    else:
        body.append('<h2 style="font-family:Fraunces;font-weight:600;font-size:30px;margin:0 0 6px">Semantic Thesaurus</h2>')
        # The whole tree on one page (Ctrl-F-able). N.0 overviews collapse to their integer chapter
        # root; the deleted/apocryphal buckets (999, 950.1, x.x) are omitted as everywhere else.
        nodes = c.execute("SELECT semkey, chaptertitle FROM chapters WHERE coalesce(semkey,'')!=''").fetchall()
        SPECIAL = {'999', '950.1', 'x.x'}
        scounts = reflex_semkey_counts()   # exact per-semkey reflex counts (proto-excluded)
        tree = []
        for n in nodes:
            sk = n['semkey']
            if sk in SPECIAL: continue
            if sk.endswith('.0') and sk.count('.') == 1:
                disp, depth = sk.split('.')[0], 0
            else:
                disp, depth = sk, sk.count('.')
            # both counts are exact (this node only, NOT the subtree): an integer root N also
            # owns its N.0 overview key. Reconstructions and reflexes are mostly filed at leaves,
            # so upper nodes read small/zero — that's intended (each item counted once, at home).
            own_n = [disp, disp + '.0'] if '.' not in disp else [disp]
            ph = ','.join('?' * len(own_n))
            cnt = c.execute(f"SELECT count(*) FROM etyma e WHERE coalesce(upper(e.status),'')!='DELETE' "
                            f"AND {ECAT} IN ({ph})", own_n).fetchone()[0]
            lcnt = sum(scounts.get(k, 0) for k in own_n)
            tree.append((disp, depth, n['chaptertitle'], cnt, lcnt))
        tree.sort(key=lambda r: natkey(r[0]))
        body.append('<p class="cap">Each count is <b>reconstructions / attestations</b> filed at that node.</p>')
        body.append('<ul class="tree">')
        for disp, depth, title, cnt, lcnt in tree:
            ti = (f'<span class="ti" style="font-weight:600">{esc(title)}</span>' if depth == 0
                  else f'<span class="ti">{esc(title)}</span>')
            ct = (f'<span class="ct" title="reconstructions / attestations">{cnt:,} / {lcnt:,}</span>'
                  if (cnt or lcnt) else '')
            body.append(f'<li style="margin-left:{depth * 18}px"><a class="row" href="/thesaurus/{disp}">'
                        f'<span class="sk">{esc(disp)}</span>{ti}{ct}</a></li>')
        body.append('</ul>')
        c.close()
        body.append('</div>')
        return page("Thesaurus", ''.join(body), nav="thesaurus")
    kids = sorted(kids, key=lambda r: natkey(r['semkey']))
    if kids:
        body.append('<ul>')
        for k in kids:
            sk = k['semkey']
            kown = [sk, sk + '.0'] if '.' not in sk else [sk]   # node-only, matching the index (not subtree)
            kph = ','.join('?' * len(kown))
            cnt = c.execute(f"SELECT count(*) FROM etyma e WHERE coalesce(upper(e.status),'')!='DELETE' "
                            f"AND {ECAT} IN ({kph})", kown).fetchone()[0]
            body.append(f'<li><a class="row" href="/thesaurus/{k["semkey"]}">'
                        f'<span class="sk">{esc(k["semkey"])}</span><span class="ti">{esc(k["chaptertitle"])}</span>'
                        f'<span class="ct">{cnt} etyma</span></a></li>')
        body.append('</ul>')
    if semkey:
        direct = c.execute(f"""SELECT e.tag, e.protoform, e.protogloss, g.plg AS plg
            FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
            WHERE {ECAT} IN ({ownph})
              AND coalesce(upper(e.status),'')!='DELETE'
            ORDER BY e.sequence, e.protogloss""", own).fetchall()
        if direct:
            dcounts = reflex_counts(c, [e['tag'] for e in direct])
            body.append(f'<div class="ety-list"><h3 style="margin-top:30px">Reconstructions <span class="ct">{len(direct):,}</span></h3>')
            for e in direct:
                body.append(f'<div class="ety-hit"><a href="/etymon/{e["tag"]}" class="pf2 lat">{esc(alt(e["protoform"]))}</a>'
                            f'<span class="pg2">{esc(e["protogloss"])}</span>'
                            f'<span class="tagn">{esc(e["plg"])} #{e["tag"]}{rcount_txt(dcounts.get(e["tag"], 0))}</span></div>')
            body.append('</div>')
        # Attested forms (reflexes) filed directly under this meaning — a separate, gloss-level
        # axis from the etyma above. Most reflexes are tagged to no etymon, so they're reachable
        # ONLY here or by language browse. Loaded lazily on expand (reuses the search WASM DB);
        # the count is static so the section is informative before anything downloads.
        scounts = reflex_semkey_counts()
        nforms = sum(scounts.get(k, 0) for k in own)
        if nforms:
            keys_json = esc(json.dumps(own, separators=(',', ':')))
            body.append(
                f'<div class="ety-list catwrap" data-semkeys="{keys_json}">'
                f'<h3 style="margin-top:30px">Attestations <span class="ct">{nforms:,}</span></h3>'
                '<div class="rbar"><input class="catfilter" type="search" '
                'placeholder="Filter by form, gloss, or language…" autocomplete="off">'
                '<span class="rcount catcount"></span></div>'
                '<div class="catlist"></div>'
                '</div>'
                + _CATFORMS_JS)
    c.close()
    body.append('</div>')
    return page("Thesaurus" + (f": {semkey}" if semkey else ""), ''.join(body), nav="thesaurus")
