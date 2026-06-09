#!/usr/bin/env python3
"""STEDT page renderer — a build-time library of render functions, imported by
build_static.py to prerender every page to static HTML. There is no server: the deployed
site is static files on GitHub Pages, and search runs client-side (WASM SQLite over
search.sqlite3). Reads the compiled stedt.sqlite.
"""
import sqlite3, urllib.parse, re, html, os, json

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# The canonical public base URL used in citations (includes any path prefix, no trailing
# slash). Defaults to the live GitHub Pages URL so copied citations resolve today; override
# with STEDT_CITE_BASE at build time (e.g. "https://stedt.org") once a project domain is wired up.
CITE_BASE = os.environ.get("STEDT_CITE_BASE", "https://larc-iu.github.io/stedt").rstrip("/")

# Show the "preview" banner (the site is an in-progress rebuild). On by default; set
# STEDT_PREVIEW=0 to turn it off once the site is no longer a preview.
PREVIEW = os.environ.get("STEDT_PREVIEW", "1") != "0"

# Proto-language abbreviations (etyma.grpid -> languagegroups.plg) expanded for the etymon header.
PLG_FULL = {
    'PST': 'Proto-Sino-Tibetan', 'PTB': 'Proto-Tibeto-Burman', 'PLB': 'Proto-Lolo-Burmese',
    'PL': 'Proto-Loloish', 'PKC': 'Proto-Kuki-Chin', 'PCC': 'Proto-Central Chin',
    'PNC': 'Proto-Northern Chin', 'PSPC': 'Proto-Southern Plains Chin', 'PPC': 'Proto-Peripheral Chin',
    'PTani': 'Proto-Tani', 'PTk': 'Proto-Tangkhulic', 'PKar': 'Proto-Karenic',
    'PCN': 'Proto-Central Naga (Ao group)', 'PNN': 'Proto-Northern Naga / Konyakian',
    'TGTM': 'Tamang–Gurung–Thakali–Manang', 'PKir': 'Proto-Kiranti', 'PBod': 'Proto-Bodic',
    'PQ': 'Proto-Qiangic', 'PrGy': 'Proto-rGyalrongic', 'PDeng': 'Proto-Deng',
    'PTQ': 'Proto-Tangut–Qiang', 'PBm': 'Proto-Burmish', 'PNungic': 'Proto-Nungic',
    'PAsak': 'Proto-Asakian', 'NEIA': 'NE Indian Areal Group', 'IA': 'Indo-Aryan',
    'CH': 'Sinitic (Chinese)', 'DRV': 'Dravidian',
}

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stedt.sqlite")

def con():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c

_VALID_TAGS = None
_SEMKEY_COUNTS = None
_XREF_LABELS = None
def valid_etymon_tags():
    """Cached frozenset of etymon tags that have a built page (non-DELETE). Used to gate
    xref links so notes never point at an unbuilt (404) etymon. Loaded once per process."""
    global _VALID_TAGS
    if _VALID_TAGS is None:
        c = con()
        _VALID_TAGS = frozenset(r[0] for r in c.execute(
            "SELECT tag FROM etyma WHERE coalesce(upper(status),'')!='DELETE'"))
        c.close()
    return _VALID_TAGS

def xref_labels():
    """Cached {tag: (plg, protoform, protogloss)} for non-DELETE etyma, so note cross-references
    can be annotated inline (e.g. '#206 PTB *(k/g)um BACK / BODY' instead of a bare '#206').
    Loaded once per process; render_note() takes no connection, so it must self-fetch."""
    global _XREF_LABELS
    if _XREF_LABELS is None:
        c = con()
        _XREF_LABELS = {r[0]: (r[1], r[2], r[3]) for r in c.execute(
            "SELECT e.tag, g.plg, e.protoform, e.protogloss FROM etyma e "
            "LEFT JOIN languagegroups g ON g.grpid=e.grpid "
            "WHERE coalesce(upper(e.status),'')!='DELETE'")}
        c.close()
    return _XREF_LABELS

def reflex_semkey_counts():
    """Cached {lexicon.semkey: reflex count}. Each reflex carries its own gloss-level semkey
    (independent of any etymon); this powers the 'Attested forms here' count on thesaurus
    pages. One GROUP BY pass, loaded once per process."""
    global _SEMKEY_COUNTS
    if _SEMKEY_COUNTS is None:
        c = con()
        # Exclude proto-language stand-ins (language LIKE '*%') — those are reconstructions, not
        # attested forms (they surface as etyma under "Reconstructions here"), and the languages
        # index hides them too. Must match the client query's filter so count == list length.
        _SEMKEY_COUNTS = {r[0]: r[1] for r in c.execute(
            "SELECT l.semkey, count(*) FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid "
            "WHERE coalesce(l.semkey,'')!='' AND ln.language NOT LIKE '*%' GROUP BY l.semkey")}
        c.close()
    return _SEMKEY_COUNTS

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
def _smart_quotes(s):
    """Turn the &quot;/&apos; entities found in note *text* (tag attributes use literal
    quotes, so they stay untouched) into directional quotation marks, by context."""
    def repl(m):
        i = m.start()
        prev = s[i - 1] if i > 0 else ''
        opening = (prev == '' or prev.isspace() or prev in '([{<>“‘—–-/')
        if m.group(0) == '&quot;':
            return '“' if opening else '”'
        return '‘' if opening else '’'
    return re.sub(r'&quot;|&apos;', repl, s)

def render_note(x):
    if not x: return ""
    s = x
    valid = valid_etymon_tags()
    labels = xref_labels()
    def _xref(m):  # only link xrefs to a built (non-DELETE) etymon; else keep the label, drop the link
        ref, txt = m.group(1), m.group(2)
        rid = int(ref)
        if rid in valid:
            lab = labels.get(rid)
            # annotate only a bare "#N" reference; leave an author-written label (the rare xref whose
            # text already spells out a gloss) untouched, so the gloss isn't printed twice.
            if lab and re.fullmatch(r'\s*#?\d+\s*', txt):
                plg, pf, pg = lab
                bits = []
                if plg: bits.append(esc(plg))
                if pf: bits.append(f'<span class="recon">{esc(alt(pf))}</span>')  # CSS .recon::before adds the *
                if pg: bits.append(esc(pg))
                if bits: txt = f'{txt} ' + ' '.join(bits)
            return f'<a class="xref" href="/etymon/{ref}">{txt}</a>'
        return f'<span class="xref">{txt}</span>'
    s = re.sub(r'<xref[^>]*\bref="(\d+)"[^>]*>(.*?)</xref>', _xref, s, flags=re.S)
    s = re.sub(r'</?xref[^>]*>', '', s)
    s = re.sub(r'<a\s+href="([^"]*)"[^>]*>(.*?)</a>',
               r'<a href="\1" rel="noopener" target="_blank">\2</a>', s, flags=re.S)
    for t, (o, c) in _PAIR.items():
        s = s.replace(f'<{t}>', o).replace(f'</{t}>', c)
    s = re.sub(r'<br\s*/?>', '<br>', s)
    s = _smart_quotes(s)
    # Leave &lt;/&gt;/&amp; as entities: in note text they're literal angle brackets/ampersands
    # (linguistic notation like "<WT", "<n>", "&lt;--&gt;"). Un-escaping them to raw < > here
    # produced bogus unclosed tags. Structural markup uses literal <tag> and was handled above.
    if '<p' not in s:
        s = f'<p class="np">{s}</p>'
    return s

def natkey(s):
    out = []
    for p in (s or '').split('.'):
        out.append((0, int(p), '') if p.isdigit() else (1, 0, p))
    return out

def esc(s): return html.escape(str(s)) if s is not None else ""

def alt(s):
    """Star every ⪤-joined alternant of a proto-form. The *leading* asterisk is supplied by CSS
    (.pf/.pf2/.recon ::before) or a literal '*' prefix (cite/title), so strip any leading '*' the
    data itself carries (only etymon 463 does) to avoid a doubled '**', then add the post-⪤ stars."""
    if not s: return s or ""
    s = re.sub(r'^\s*\*\s*', '', s)        # drop a stray leading star baked into the data
    # \*? consumes an asterisk the data already carries on the alternant, so a meaningful
    # double-star (e.g. **d-k-wiy) isn't bumped to *** by adding another.
    return re.sub(r'⪤\s*\*?', '⪤ *', s)

def iso_link(code):
    """An ISO 639-3 code linked to its Glottolog languoid page (the original's Ethnologue
    show_language.asp links are long dead)."""
    code = (code or "").strip()
    if not code: return ""
    return (f'<a href="https://glottolog.org/resource/languoid/iso/{esc(code)}"'
            f' rel="noopener" target="_blank">{esc(code)}</a>')

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
  --morph:#4c211b;   /* interactable morpheme at rest: a quiet, dark accent — clearly a link, barely louder than ink */
  --accent2:#3a5a6b; --gold:#b08a3c;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:"Charis SIL","Gentium Plus",Georgia,serif; font-size:18px; line-height:1.55;
  overflow-wrap:break-word;
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
.ety-head{border-bottom:1px solid var(--rule);padding-bottom:14px;margin-bottom:24px;}
.ety-head .plg{font-variant:small-caps;letter-spacing:.08em;font-size:13px;color:var(--accent);}
.ety-head .pl{font-variant:small-caps;letter-spacing:.06em;font-size:13px;color:var(--accent);margin:10px 0 0;}
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

/* section headers — the primary structural tier in ink (vermilion reserved for asterisk, proto-language, links) */
.notes h3,.reflexes h3,.thes h3,.conn h3,.meso h3,.apparatus h3,.ety-list h3,.phon h3{font-variant:small-caps;letter-spacing:.10em;
  font-size:16px;color:var(--ink);border-bottom:1px solid var(--rule);padding-bottom:5px;margin:0 0 12px;}
.reflexes{max-width:900px;}
.reflexes h3{display:flex;align-items:baseline;}
.reflexes h3 .cnt{margin-left:auto;font-size:.92em;letter-spacing:0;color:var(--mut);font-variant-numeric:tabular-nums;}
.reflexes h3 .toggle-all{margin-left:auto;font-family:"Fraunces",serif;font-size:11.5px;font-variant:small-caps;
  letter-spacing:.06em;color:var(--mut);background:none;border:1px solid var(--rule);border-radius:3px;padding:2px 10px;cursor:pointer;}
.reflexes h3 .toggle-all:hover{color:var(--accent);border-color:var(--accent);}
/* group-page sections (Subgroups / Languages / Reconstructions): one uniform gap above each
   header, plus a right-aligned count — scoped here so other .ety-list headers are untouched */
.grpsec{margin-top:26px;}
.grpsec h3{display:flex;align-items:baseline;}
.grpsec h3 .cnt{margin-left:auto;font-size:.92em;letter-spacing:0;color:var(--mut);font-variant-numeric:tabular-nums;}
.notes{margin:26px 0 8px;}
.np{margin:0 0 12px;max-width:38em;} .fn{font-size:.86em;color:var(--soft);}
.note-block{margin-bottom:6px;}

.jump{font-size:12.5px;color:var(--mut);margin:0 0 18px;line-height:2;}
.jump a{border-bottom:1px dotted var(--rule);margin-right:4px;}
.sg{margin:0 0 22px;}
.sg h4{display:flex;align-items:baseline;gap:10px;font-variant:small-caps;letter-spacing:.06em;font-size:14px;
  color:var(--soft);margin:0 0 6px;}
.sg h4 .c{font-family:"Fraunces",serif;font-size:12px;color:var(--mut);letter-spacing:0;margin-left:auto;
  font-variant-numeric:tabular-nums;}
.rfx{display:grid;grid-template-columns:190px minmax(0,1fr) 190px;gap:2px 18px;padding:4px 0;
  border-bottom:1px solid var(--hair);align-items:baseline;line-height:1.35;}
.rfx:hover{background:var(--paper2);}
.rfx:last-child{border-bottom:none}
.rfx:target,.rfx.rn-target{background:var(--paper2);box-shadow:inset 3px 0 0 var(--accent);padding-left:8px;}
/* etymon page only: subgroup-grouped reflexes + intermediate-recon rows.
   no per-row rule; the source trails the form instead of pinning hard-right;
   full-width section so its header rule lines up with Notes / Prev-reconstructed. */
.reflexes.etymon-rfx{max-width:none;}
.sg .rfx,.meso .rfx{grid-template-columns:190px auto 1fr;border-bottom:none;}
.rfx .lang{color:var(--soft);font-size:14.5px;}
.rfx .form{font-size:17px;}
.rfx .form .br{color:var(--mut);}
.rfx .src{font-size:13px;color:var(--mut);}
.rfx .loc{color:var(--mut);font-variant-numeric:tabular-nums;cursor:help;border-bottom:1px dotted var(--rule);}
.rfx .g{color:var(--soft);font-size:13.5px;font-style:italic;}
.rfx a{border-bottom:none;}
.rfx a.lang{color:var(--soft);}
.rfx a:hover{color:var(--accent);}
.lgab{font-variant:small-caps;letter-spacing:.04em;font-size:12px;color:var(--mut);}
.rfx .pos,.rx-hit .pos,.drop .pos{font-variant:small-caps;letter-spacing:.03em;font-size:11.5px;color:var(--mut);margin-left:6px;}
.rfx .anl{display:block;font-size:12px;color:var(--mut);margin-top:1px;}
.rfx .anl a{border-bottom:none;color:var(--mut);}
.rfx .anl a:hover{color:var(--accent);}
.rfx .rfxnote{grid-column:1/-1;font-size:13px;color:var(--soft);margin:2px 0 2px;padding-left:2px;}
.rfx .rfxnote p{margin:0;max-width:62em;}

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
  border-bottom:1px solid var(--rule);padding-bottom:5px;margin:28px 0 10px;
  display:flex;align-items:baseline;}
.sec-label .sec-n{margin-left:auto;color:var(--mut);font-variant:normal;letter-spacing:0;
  font-size:.9em;font-variant-numeric:tabular-nums;}
.ety-hit{display:grid;grid-template-columns:auto 1fr auto;gap:14px;align-items:baseline;padding:8px 0;
  border-bottom:1px solid var(--hair);}
a.ety-hit{border-bottom:1px solid var(--hair);}
a.ety-hit:hover{color:inherit;background:var(--paper2);border-color:var(--hair);}
.ety-hit .pf2{font-size:19px;} .ety-hit .pf2::before{content:"*";color:var(--accent);}
/* attested reflex form: same column treatment as a protoform but NO reconstruction asterisk */
.ety-hit .rf{font-size:19px;}
.ety-hit .pg2{font-variant:small-caps;color:var(--soft);}
/* attestation gloss: a plain definition — soft, but NOT small-caps (that's for protoglosses) */
.ety-hit .gl2{color:var(--soft);}
.ety-hit .tagn{font-family:"Fraunces",serif;font-size:12px;color:var(--mut);font-variant-numeric:tabular-nums;}
.rx-hit{display:grid;grid-template-columns:160px 1fr auto;gap:4px 14px;align-items:baseline;padding:6px 0;
  border-bottom:1px solid var(--hair);font-size:15px;}
.rx-hit .lang{color:var(--soft);font-size:13.5px;border-bottom:none;}
.rx-hit a.lang:hover{color:var(--accent);}
.rx-hit .rx-mid{min-width:0;}
.rx-hit .g,.drop .gl{color:var(--soft);font-style:italic;}
/* interactable morpheme (per-syllable etymon link): a quiet accent tint atop the dotted underline,
   so it reads as clickable without shouting; brightens to full accent on hover. Not scoped to
   .rx-hit, so the treatment stays consistent anywhere a .syl link appears. */
a.syl{color:var(--morph);border-bottom:1px dotted var(--rule);}
a.syl:hover{color:var(--accent);border-bottom-color:var(--accent);}
.rx-hit .br{color:var(--mut);}
.rx-hit .vias{color:var(--mut);font-size:12.5px;margin-left:.45em;}
.rx-hit .via{font-size:12.5px;color:var(--mut);border-bottom:none;}
.rx-hit .via:hover{color:var(--accent);}
.rx-hit .rx-src{text-align:right;color:var(--mut);font-size:12.5px;white-space:nowrap;}
.rx-hit .rx-src a{color:var(--mut);border-bottom:1px dotted var(--rule);}
.rx-hit .rx-src a:hover{color:var(--accent);}
/* a reflex carrying a lexical note: a small circled-i after the gloss (NOT a dotted underline —
   that signal is reserved for clickable morphemes); the note reveals on hover/focus. The badge is
   drawn in CSS so it's crisp and on-palette, brightening to accent when active. */
.noted{cursor:help;position:relative;}
.noted::after{content:"i";display:inline-grid;place-content:center;box-sizing:border-box;
  width:1.45em;height:1.45em;margin-left:.34em;border:1px solid currentColor;border-radius:50%;
  font:italic 600 .62em/1 "Fraunces",serif;vertical-align:.28em;color:var(--mut);}
.noted:hover::after,.noted:focus::after,.noted:focus-within::after{color:var(--accent);}
/* right:0 anchors the bubble under the circled-i (the right end of .noted), not the gloss's left
   edge — otherwise a long gloss strands the bubble far from its icon. */
.noted>.notepop{display:none;position:absolute;right:0;top:1.55em;z-index:6;width:max-content;max-width:min(340px,calc(100vw - 24px));
  background:var(--paper);border:1px solid var(--rule);border-radius:3px;padding:7px 10px;font-style:normal;
  font-size:12.5px;line-height:1.5;color:var(--soft);white-space:normal;text-align:left;overflow-wrap:anywhere;}
.noted:hover>.notepop,.noted:focus>.notepop,.noted:focus-within>.notepop{display:block;}
.noted>.notepop p,.noted>.notepop .np{margin:0;} .noted>.notepop a{color:var(--soft);}
.noted>.notepop .np{display:block;} .noted>.notepop .np+.np{margin-top:1.35em;}   /* separate notes by an empty line, no divider */
/* Stammbaum-subgroup header between attested-form result groups */
.rx-sub{font-variant:small-caps;letter-spacing:.05em;color:var(--soft);font-size:13px;
  margin:16px 0 3px;padding-bottom:2px;border-bottom:1px solid var(--rule);}

/* reconstructions browse: client-side filter + windowed list */
.rbar{display:flex;gap:14px;align-items:baseline;flex-wrap:wrap;margin:0 0 14px;}
.rbar input{flex:1;min-width:240px;font-family:inherit;font-size:16px;padding:9px 13px;
  border:1px solid var(--rule);background:var(--paper2);color:var(--ink);border-radius:2px;}
.rbar input:focus{outline:none;border-color:var(--accent);}
.rcount{font-size:13px;color:var(--mut);white-space:nowrap;font-variant-numeric:tabular-nums;}
.rnone{display:none;color:var(--mut);font-size:15px;padding:24px 0;}
.wl-spacer{pointer-events:none;}   /* reserves the unrendered tail's height (see _WINDOWED_JS) */

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
.phon{margin:20px 0 8px;}
.phon-grid{display:flex;flex-wrap:wrap;gap:7px 26px;}
.phon .pf-f{font-size:15px;white-space:nowrap;}
.phon .pf-f .rl{display:inline;width:auto;flex:none;margin-right:7px;}
.phon .pf-f .val{font-family:"Charis SIL",serif;color:var(--ink);}
.conn-row{display:flex;align-items:baseline;gap:12px;padding:6px 0;}
.rl{font-variant:small-caps;letter-spacing:.08em;font-size:12px;color:var(--accent);width:92px;flex:none;}
.conn-row .reltgt{flex:1;}
.exm{color:var(--gold);font-variant:small-caps;letter-spacing:.06em;font-size:.9em;}
.metabar a{border-bottom:1px dotted var(--rule);}
.metabar a:hover{color:var(--accent);}
.idx{list-style:none;padding:0;margin:6px 0 0;columns:2;column-gap:44px;font-size:15px;}
.idx li{break-inside:avoid;padding:2px 0;}
.grp{font-variant:small-caps;letter-spacing:.05em;font-size:15px;color:var(--ink);margin:18px 0 2px;}
.grp .plg2{color:var(--mut);font-variant:normal;font-size:.82em;letter-spacing:0;}
/* stammbaum group number (e.g. 6.1.1) shown alongside subgroup names on group/languages/etymon pages */
.grpno{color:var(--mut);font-variant-numeric:tabular-nums;font-size:.82em;letter-spacing:0;margin-right:.35em;}
/* full family tree on group pages: compact, scrollable, one click to any node */
.lgtree{border:1px solid var(--rule);border-radius:2px;max-height:360px;overflow:auto;padding:8px 14px;
  font-size:13.5px;line-height:1.7;}
.lgtree > div{white-space:nowrap;}
.lgtree a{border-bottom:none;color:var(--soft);}
.lgtree a:hover{color:var(--accent);}
.lgtree .here{color:var(--ink);font-weight:700;}
.srclangs{margin:12px 0 4px;font-size:13.5px;color:var(--soft);line-height:1.9;}
.srcidx{list-style:none;padding:0;margin:8px 0 0;}
.srcidx li{padding:8px 2px;border-bottom:1px solid var(--rule);}
.srcidx li a{font-family:"Fraunces",serif;}
.srcidx .srcref{color:var(--soft);font-size:13.5px;margin-left:9px;}
.srcidx .srccnt{color:var(--mut);font-size:12.5px;margin-left:9px;font-variant-numeric:tabular-nums;white-space:nowrap;}
.srcsort{font-size:13px;color:var(--mut);margin:6px 0 14px;}
.srcsort select{font-family:inherit;font-size:13px;color:var(--ink);background:var(--paper2);
  border:1px solid var(--rule);border-radius:2px;padding:3px 7px;}
.srcsort select:focus{outline:none;border-color:var(--accent);}
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

/* ---------------------------------------------------------------- responsive (phones/tablets) */
@media (max-width:720px){
  body{font-size:17px;}

  /* masthead stacks: wordmark / search / nav, each full width; nav wraps instead of overflowing */
  header.mast{flex-direction:column;align-items:stretch;gap:12px;padding:16px 18px 12px;}
  .brand{order:1;}
  .brand .wm{font-size:25px;}
  .hsearch{order:2;}
  .hsearch input{width:100%;}
  nav.main{order:3;margin:0;flex-wrap:wrap;gap:9px 18px;font-size:14px;}

  main{padding:24px 18px 70px;}
  footer{padding:20px 18px 48px;}

  /* big titles down a notch; etymon number drops from a float to its own line */
  .pagetitle{font-size:28px;}
  .ety-head .pf{font-size:32px;}
  .ety-head .pg{font-size:18px;}
  .ety-head .etno{float:none;display:block;margin:0 0 6px;}

  /* record rows collapse to a single stacked column (lang / form·gloss / source) */
  .rfx,.sg .rfx,.meso .rfx{grid-template-columns:1fr;gap:1px 0;padding:8px 0;}
  .rx-hit{grid-template-columns:1fr;gap:1px 0;}
  .rx-hit .rx-src{text-align:left;}
  .ety-hit{grid-template-columns:1fr auto;gap:2px 12px;}
  .ety-hit .pg2,.ety-hit .gl2{grid-column:1;}
  .ety-hit .tagn{grid-column:2;grid-row:1/3;align-self:start;}

  /* language index: one column */
  .idx{columns:1;}

  /* connections: let the relation label sit on its own line above the target */
  .conn-row{flex-wrap:wrap;}
  .conn-row .rl{width:100%;}

  /* thesaurus rows: let the title wrap, keep the count pinned right (don't let title grow) */
  .thes .ti{min-width:0;}

  .stats{gap:20px;}
}
"""

_NAV = [("thesaurus", "/thesaurus", "Thesaurus"),
        ("reconstructions", "/reconstructions", "Reconstructions"),
        ("languages", "/languages", "Languages"),
        ("sources", "/sources", "Sources"),
        ("about", "/about", "About")]

# A note popover's right edge is pinned to its circled-i (see .noted CSS), so on a narrow viewport
# a wide bubble can run off the left edge. CSS can't clamp it to the viewport (the bubble's offset
# parent is a tiny inline span at an unpredictable x), so on first show we measure and nudge it back
# inside an 8px margin. Delegated on document, so it also covers client-rendered notes (search,
# thesaurus). Memoized per node; reset on resize. No Python interpolation here — plain { }.
_NOTEPOP_JS = """<script>
(function(){
  var seen=new WeakSet(), M=8;
  function clamp(n){
    var p=n.querySelector('.notepop'); if(!p) return;
    p.style.transform='';
    var r=p.getBoundingClientRect(), w=document.documentElement.clientWidth, dx=0;
    if(r.left<M) dx=M-r.left; else if(r.right>w-M) dx=w-M-r.right;
    if(dx) p.style.transform='translateX('+Math.round(dx)+'px)';
  }
  function show(e){
    var n=e.target.closest&&e.target.closest('.noted');
    if(n&&!seen.has(n)){seen.add(n);clamp(n);}
  }
  document.addEventListener('pointerover',show,true);
  document.addEventListener('focusin',show,true);
  window.addEventListener('resize',function(){
    seen=new WeakSet();
    var ps=document.querySelectorAll('.notepop');
    for(var i=0;i<ps.length;i++) ps[i].style.transform='';
  },{passive:true});
})();
</script>"""

def page(title, body, q="", nav=""):
    nav_parts = []
    for key, href, label in _NAV:
        cls = ' class="active"' if nav == key else ''
        nav_parts.append(f'<a href="{href}"{cls}>{label}</a>')
    navhtml = "".join(nav_parts)
    search_box = (f'<form class="hsearch" action="/search" method="get">'
                  f'<input name="q" placeholder="search…" value="{esc(q)}" autocomplete="off"></form>')
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · STEDT</title>
<link rel="icon" href="data:,">
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
  {search_box}
</header>
<main>{body}</main>
<footer>Preview interface for STEDT · <a href="https://github.com/larc-iu/stedt">github.com/larc-iu/stedt</a> · <a href="/_legacy/" rel="nofollow">Legacy interface</a></footer>
{_NOTEPOP_JS}
<script type="module" src="/assets/stedt-search.js"></script>
</body></html>"""

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
    const altstar=s=>String(s).replace(/⪤\\s*\\*?/g,'⪤ *');
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
    rfx = n("SELECT count(*) FROM lexicon")
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
        if m and int(m.group(1)) in labels:
            t = m.group(1); lab = labels[int(t)]
            return f'<a class="xref" href="/etymon/{t}">*{esc(alt(lab[0]))} ‘{esc(lab[1])}’</a>'
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

def group_lineage(c, grpno):
    """Genetic lineage (ancestors incl. self) by walking grpno prefixes."""
    out = []
    if not grpno: return out
    parts = str(grpno).split('.')
    for i in range(1, len(parts) + 1):
        r = c.execute("SELECT grpid,grpno,grp FROM languagegroups WHERE grpno=?", ('.'.join(parts[:i]),)).fetchone()
        if r: out.append(r)
    return out

def reflex_counts(c, tags=None):
    """Map {etymon tag: number of attested reflexes}. tags=None counts every etymon in one pass;
    pass a tag set to limit it. Excludes proto-form stand-ins (language '*…') so the count matches
    the etymon page's own, reflex_semkey_counts(), and the search query — those are reconstructions,
    not attested reflexes."""
    JW = ("FROM lx_et_hash h JOIN lexicon l ON l.rn=h.rn JOIN languagenames ln ON ln.lgid=l.lgid "
          "WHERE h.tag>0 AND ln.language NOT LIKE '*%'")
    if tags is None:
        rows = c.execute(f"SELECT h.tag AS tag, count(DISTINCT h.rn) n {JW} GROUP BY h.tag")
        return {r['tag']: r['n'] for r in rows}
    tags = [t for t in tags if t]
    out = {}
    for i in range(0, len(tags), 900):
        chunk = tags[i:i + 900]; qm = ','.join('?' * len(chunk))
        for r in c.execute(f"SELECT h.tag AS tag, count(DISTINCT h.rn) n {JW} "
                           f"AND h.tag IN ({qm}) GROUP BY h.tag", chunk):
            out[r['tag']] = r['n']
    return out

def rcount_txt(n):
    """' · 12 reflexes' / ' · 1 reflex' / '' for an etymon's reflex count."""
    if not n: return ''
    return f' · {n:,} ' + ('reflex' if n == 1 else 'reflexes')

def proto_labels(c, tags):
    """Map {tag: protoform} for a set of etymon tags, restricted to non-DELETE etyma (only
    those have a built page, so callers can gate links on membership)."""
    tags = [t for t in tags if t]
    out = {}
    for i in range(0, len(tags), 900):
        chunk = tags[i:i + 900]
        qm = ','.join('?' * len(chunk))
        for r in c.execute(f"SELECT tag,protoform FROM etyma WHERE tag IN ({qm}) "
                           f"AND coalesce(upper(status),'')!='DELETE'", chunk):
            out[r['tag']] = r['protoform']
    return out

_CANON = None
def canonical_languages():
    """Collapse the source-variant lgids of one (language name, subgroup) to a single canonical
    page — the most-attested lgid — so a 'language' is a lect (not a language×source pair) and its
    words from every source live on one page; the other lgids redirect to it. Variants almost
    always agree on subgroup/ISO, so grouping by (name, grpid) is safe and won't merge homonyms in
    different branches. Returns (canon_of {lgid: canonical_lgid}, members {canonical_lgid: [lgids]})."""
    global _CANON
    if _CANON is None:
        c = con()
        rows = c.execute("""SELECT ln.lgid AS lgid, ln.language AS language, ln.grpid AS grpid,
                count(l.rn) AS n
            FROM languagenames ln LEFT JOIN lexicon l ON l.lgid=ln.lgid
            GROUP BY ln.lgid""").fetchall()
        c.close()
        groups = {}
        for r in rows:
            groups.setdefault((r['language'], r['grpid']), []).append((r['lgid'], r['n'] or 0))
        canon_of, members = {}, {}
        for lst in groups.values():
            canon = max(lst, key=lambda t: (t[1], -t[0]))[0]   # most forms; tie -> lowest lgid
            ids = sorted(t[0] for t in lst)
            members[canon] = ids
            for lid in ids:
                canon_of[lid] = canon
        _CANON = (canon_of, members)
    return _CANON

def canon_lgid(lgid):
    """The canonical lgid for a language×source lgid, so internal links skip the redirect hop."""
    return canonical_languages()[0].get(lgid, lgid)

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
            count(DISTINCT CASE WHEN l.rn IS NOT NULL AND ln.language NOT LIKE '*%' THEN ln.lgid END) AS nlang,
            count(CASE WHEN ln.language NOT LIKE '*%' THEN l.rn END) AS nforms
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
    const altstar=s=>String(s).replace(/⪤\\s*\\*?/g,'⪤ *');
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
  var altstar=function(s){return String(s).replace(/⪤\\s*\\*?/g,'⪤ *');};
  var list=wrap.querySelector('.catlist'),
      count=wrap.querySelector('.catcount'),
      input=wrap.querySelector('.catfilter');
  var DATA=null, view=[], loaded=false, loading=false;
  function row(r){
    var home=B+'/language/'+r.lgid+'#rn'+r.rn;
    var gl=r.note?'<span class="noted" tabindex="0">'+esc(r.gloss)+'<span class="notepop" role="note">'+esc(r.note)+'</span></span>':esc(r.gloss);
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
