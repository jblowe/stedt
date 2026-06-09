"""Index/browse pages: home, about, reconstructions, languages, sources, search, thesaurus."""

import re
import json

from markupsafe import Markup

from .config import CITE_BASE, PREVIEW
from .db import con, reflex_semkey_counts
from .text import esc, alt, natkey, rcount_txt
from .notes import render_note
from .shell import page, breadcrumb, reflex_counts, canon_lgid
from .templating import env

# ---------------------------------------------------------------- views
_HOME = env.get_template("home.html")
_ABOUT = env.get_template("about.html")
_LANGUAGES = env.get_template("languages_index.html")
_SOURCES = env.get_template("sources_index.html")
_RECONSTRUCTIONS = env.get_template("reconstructions.html")
_SEARCH = env.get_template("search.html")
_THESAURUS = env.get_template("thesaurus.html")


def home():
    return page("Home", _HOME.render(preview=PREVIEW))


def about():
    conn = con()
    one = lambda sql: conn.execute(sql).fetchone()[0]
    ety = one("SELECT count(*) FROM etyma e WHERE coalesce(upper(e.status),'')!='DELETE'")
    rfx = one("SELECT count(*) FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid WHERE ln.language NOT LIKE '*%'")
    # a "language" is a lect = (name, subgroup), matching the Languages index header + canonicalization
    lgs = one("""SELECT count(*) FROM (SELECT 1 FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid
        WHERE ln.language!=\'\' AND ln.language NOT LIKE \'*%\' GROUP BY ln.language, ln.grpid)""")
    src = one("""SELECT count(*) FROM srcbib sb WHERE EXISTS(
        SELECT 1 FROM languagenames ln JOIN lexicon l ON l.lgid=ln.lgid WHERE ln.srcabbr=sb.srcabbr)""")
    conn.close()
    body = _ABOUT.render(ety=f"{ety:,}", rfx=f"{rfx:,}", lgs=f"{lgs:,}", src=f"{src:,}", cite_base=CITE_BASE)
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
    conn = con()
    OK = "coalesce(upper(e.status),'')!='DELETE'"
    rows = conn.execute(f"""SELECT e.tag, e.protoform, e.protogloss, g.plg AS plg
        FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
        WHERE {OK} ORDER BY e.protogloss, e.tag""").fetchall()
    counts = reflex_counts(conn)
    conn.close()
    total = len(rows)
    data = [
        [r["tag"], alt(r["protoform"] or ""), r["protogloss"] or "", r["plg"] or "", counts.get(r["tag"], 0)]
        for r in rows
    ]
    # < keeps the payload from breaking out of the <script> tag and stays valid JSON.
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("<", "\u003c")
    return page(
        "Reconstructions",
        _RECONSTRUCTIONS.render(total=f"{total:,}", payload=Markup(payload), windowed_js=Markup(_WINDOWED_JS)),
        nav="reconstructions",
    )


def languages_index():
    conn = con()
    # every genetic-classification node, so headline subgroups (Lolo-Burmese, Bodo-Garo, Tani, …)
    # and the two "previously published reconstructions" groups appear as headings even when no
    # member language is directly attested under them.
    allgroups = conn.execute("SELECT grpid, grpno, grp, plg FROM languagegroups WHERE grpid IS NOT NULL").fetchall()
    rows = conn.execute("""SELECT ln.grpid AS grpid, ln.language AS language, ln.lgid AS lgid, count(*) AS n
        FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid
        WHERE ln.language NOT LIKE '*%'
        GROUP BY ln.lgid""").fetchall()
    conn.close()
    members, ntot = {}, 0  # grpid -> {language name: (lgid, max reflex count)}
    for r in rows:
        nm = r["language"] or ""
        if not nm:
            continue
        d = members.setdefault(r["grpid"], {})
        cur = d.get(nm)
        if cur is None or r["n"] > cur[1]:
            d[nm] = (r["lgid"], r["n"])
    for d in members.values():
        ntot += len(d)

    def block(grpno, grp, plg, grpid, langs):
        # pre-escape scalars to Markup so the template (autoescape on) emits them verbatim
        return {
            "depth": (str(grpno).count(".") if grpno else 0) * 18,
            "grpno": Markup(esc(grpno)) if grpno else "",
            "grp": Markup(esc(grp or "—")),
            "plg": Markup(esc(plg)) if plg else "",
            "grpid": grpid,
            "langs": [
                (Markup(esc(nm)), canon_lgid(lid))
                for nm, (lid, _) in sorted(langs.items(), key=lambda kv: kv[0].lower())
            ],
        }

    blocks = [
        block(g["grpno"], g["grp"], g["plg"], g["grpid"], members.get(g["grpid"], {}))
        for g in sorted(allgroups, key=lambda g: natkey(g["grpno"]))
    ]
    # any attested language whose grpid isn't a known classification node (incl. NULL) stays reachable
    known = {g["grpid"] for g in allgroups}
    leftover = {}
    for gid, d in members.items():
        if gid not in known:
            leftover.update(d)
    if leftover:
        blocks.append(block(None, "Unclassified", "", None, leftover))
    return page("Languages", _LANGUAGES.render(ntot=f"{ntot:,}", blocks=blocks), nav="languages")


def sources_index():
    conn = con()
    rows = conn.execute("""SELECT sb.srcabbr AS srcabbr, sb.citation AS citation, sb.author AS author,
            sb.year AS year, sb.title AS title, sb.imprint AS imprint,
            count(DISTINCT CASE WHEN l.rn IS NOT NULL AND ln.language NOT LIKE '*%' AND ln.language!='' THEN ln.lgid END) AS nlang,
            count(CASE WHEN ln.language NOT LIKE '*%' AND ln.language!='' THEN l.rn END) AS nforms
        FROM srcbib sb
        LEFT JOIN languagenames ln ON ln.srcabbr=sb.srcabbr
        LEFT JOIN lexicon l ON l.lgid=ln.lgid
        WHERE coalesce(sb.srcabbr,'')!=''
        GROUP BY sb.srcabbr
        ORDER BY lower(coalesce(nullif(sb.author,''),nullif(sb.citation,''),sb.srcabbr)), sb.year""").fetchall()
    conn.close()

    def refstr(s):
        # full reference incl. the publication imprint (journal/issue/pages or publisher),
        # so the venue is visible at a glance instead of only on the detail page.
        au = (s["author"] or "").rstrip()
        if au and not au.endswith("."):
            au += "."
        base = " ".join(x for x in (au, f"{s['year']}." if s["year"] else "", s["title"]) if x)
        if s["imprint"]:
            sep = "" if base.rstrip().endswith(".") else "."  # avoid "Title.. Imprint"
            base = (base.rstrip() + sep + " " + s["imprint"]) if base else s["imprint"]
        return base

    def item(s):
        cit = Markup(esc(s["citation"] or s["srcabbr"]))
        ref = Markup(esc(refstr(s)))
        return {
            "srcabbr": Markup(esc(s["srcabbr"])),
            "cit": cit,
            "ref": ref,
            "show_ref": bool(ref) and ref != cit,  # data list hides ref when it just repeats the citation
            "au": Markup(esc((s["author"] or s["citation"] or s["srcabbr"] or "").lower())),
            "nforms": s["nforms"],
            "nforms_fmt": f"{s['nforms']:,}",
            "nlang": s["nlang"],
        }

    data = [item(s) for s in rows if s["nforms"]]
    refonly = [item(s) for s in rows if not s["nforms"]]
    total_forms = sum(s["nforms"] for s in rows if s["nforms"])
    return page(
        "Sources",
        _SOURCES.render(ndata=f"{len(data):,}", total_forms=f"{total_forms:,}", data=data, refonly=refonly),
        nav="sources",
    )


def search_page(q=""):
    """Static results shell — reads ?q= and renders matches client-side via window.stedtSearch,
    federated across entity types (languages / reconstructions / attested forms), each with its
    true total count and windowed infinite-scroll, so results are never silently capped."""
    return page("Search", _SEARCH.render(windowed_js=Markup(_WINDOWED_JS)), q)


# Legacy files an etymon under its (more specific) `chapter`; `semkey` is only a fallback for
# the lone live etymon whose chapter doesn't resolve. Used for thesaurus placement + counts.
ECAT = "coalesce(nullif(e.chapter,''),e.semkey)"

# Windowed list for a thesaurus page's "Attestations". On page load it queries the search WASM
# DB (window.stedtFormsByCategory, set by /assets/stedt-search.js) for every reflex filed at
# this node's semkey(s), then renders in 200-row windows with an in-memory filter and
# infinite-scroll — so a 13k-form category stays a light DOM. No Python interpolation here
# (keys ride in via data-semkeys), so it's a plain constant: literal { } need no escaping.
_CATFORMS_JS = (
    """
<script>
"""
    + _WINDOWED_JS
    + """
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
)


def thesaurus(semkey=None):
    conn = con()
    if semkey is None:
        nodes = conn.execute("SELECT semkey, chaptertitle FROM chapters WHERE coalesce(semkey,'')!=''").fetchall()
        SPECIAL = {"999", "950.1", "x.x"}
        scounts = reflex_semkey_counts()  # exact per-semkey reflex counts (proto-excluded)
        tree = []
        for n in nodes:
            sk = n["semkey"]
            if sk in SPECIAL:
                continue
            if sk.endswith(".0") and sk.count(".") == 1:
                disp, depth = sk.split(".")[0], 0
            else:
                disp, depth = sk, sk.count(".")
            # both counts are exact (this node only, NOT the subtree): an integer root N also
            # owns its N.0 overview key. Reconstructions and reflexes are mostly filed at leaves,
            # so upper nodes read small/zero - that's intended (each item counted once, at home).
            own_n = [disp, disp + ".0"] if "." not in disp else [disp]
            ph = ",".join("?" * len(own_n))
            cnt = conn.execute(
                f"SELECT count(*) FROM etyma e WHERE coalesce(upper(e.status),'')!='DELETE' " f"AND {ECAT} IN ({ph})",
                own_n,
            ).fetchone()[0]
            lcnt = sum(scounts.get(k, 0) for k in own_n)
            tree.append((disp, depth, n["chaptertitle"], cnt, lcnt))
        tree.sort(key=lambda r: natkey(r[0]))
        conn.close()
        treeinfo = [
            {
                "pad": depth * 18,
                "disp": disp,
                "disp_esc": Markup(esc(disp)),
                "ti": Markup(
                    f'<span class="ti" style="font-weight:600">{esc(title)}</span>'
                    if depth == 0
                    else f'<span class="ti">{esc(title)}</span>'
                ),
                "ct": Markup(
                    f'<span class="ct" title="reconstructions / attestations">{cnt:,} / {lcnt:,}</span>'
                    if (cnt or lcnt)
                    else ""
                ),
            }
            for disp, depth, title, cnt, lcnt in tree
        ]
        return page("Thesaurus", _THESAURUS.render(root=True, tree=treeinfo), nav="thesaurus")

    # The integer node N and the chapter N.0 are the same category-overview node; treat
    # /thesaurus/N.0 as an alias of /thesaurus/N so it doesn't render an empty, self-referential page.
    if re.fullmatch(r"\d+\.0", semkey):
        semkey = semkey.split(".")[0]
    own = [semkey, semkey + ".0"] if "." not in semkey else [semkey]
    ownph = ",".join("?" * len(own))
    title = conn.execute("SELECT chaptertitle FROM chapters WHERE semkey=?", (semkey,)).fetchone()
    if not title and "." not in semkey:
        title = conn.execute("SELECT chaptertitle FROM chapters WHERE semkey=?", (semkey + ".0",)).fetchone()
    title = title[0] if title else semkey
    cnotes = conn.execute(
        f"""SELECT xmlnote FROM notes WHERE id IN ({ownph}) AND spec='C'
                         AND xmlnote IS NOT NULL ORDER BY ord, noteid""",
        own,
    ).fetchall()
    crumb = breadcrumb(conn, semkey)
    depth = len(semkey.split("."))
    # Children at the next depth, minus the N.0 overview (it IS this integer node).
    kids = conn.execute(
        """SELECT semkey,chaptertitle FROM chapters
        WHERE semkey LIKE ? AND (length(semkey)-length(replace(semkey,'.','')))=?
          AND semkey NOT LIKE '%.0'
        """,
        (semkey + ".%", depth),
    ).fetchall()
    kids = sorted(kids, key=lambda r: natkey(r["semkey"]))
    kidinfo = []
    for k in kids:
        sk = k["semkey"]
        kown = [sk, sk + ".0"] if "." not in sk else [sk]  # node-only, matching the index (not subtree)
        kph = ",".join("?" * len(kown))
        cnt = conn.execute(
            f"SELECT count(*) FROM etyma e WHERE coalesce(upper(e.status),'')!='DELETE' " f"AND {ECAT} IN ({kph})", kown
        ).fetchone()[0]
        kidinfo.append(
            {"semkey": sk, "semkey_esc": Markup(esc(sk)), "title": Markup(esc(k["chaptertitle"])), "cnt": cnt}
        )
    direct = conn.execute(
        f"""SELECT e.tag, e.protoform, e.protogloss, g.plg AS plg
        FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
        WHERE {ECAT} IN ({ownph})
          AND coalesce(upper(e.status),'')!='DELETE'
        ORDER BY e.sequence, e.protogloss""",
        own,
    ).fetchall()
    dinfo = []
    if direct:
        dcounts = reflex_counts(conn, [e["tag"] for e in direct])
        dinfo = [
            {
                "tag": e["tag"],
                "pf": Markup(esc(alt(e["protoform"]))),
                "pg": Markup(esc(e["protogloss"])),
                "tagn": Markup(f'{esc(e["plg"])} #{e["tag"]}{rcount_txt(dcounts.get(e["tag"], 0))}'),
            }
            for e in direct
        ]
    # Attested forms (reflexes) filed directly under this meaning - a separate, gloss-level axis from
    # the etyma above. Loaded lazily on expand (reuses the search WASM DB); the count is static.
    scounts = reflex_semkey_counts()
    nforms = sum(scounts.get(k, 0) for k in own)
    attest = None
    if nforms:
        attest = {"keys_json": Markup(esc(json.dumps(own, separators=(",", ":")))), "nforms": f"{nforms:,}"}
    conn.close()
    return page(
        "Thesaurus" + f": {semkey}",
        _THESAURUS.render(
            root=False,
            crumb=Markup(crumb),
            title=Markup(esc(title)),
            cnotes=[Markup(render_note(r["xmlnote"])) for r in cnotes],
            kids=kidinfo,
            direct=dinfo,
            ndirect=f"{len(direct):,}",
            attest=attest,
            catforms_js=Markup(_CATFORMS_JS),
        ),
        nav="thesaurus",
    )
