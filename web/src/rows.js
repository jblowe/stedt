// Shared client-side presentation layer for entity rows (search results, thesaurus reflex list,
// reconstructions index). Goal: ONE row builder and ONE url builder per entity type, so the CLIENT
// views can't drift — a reflex row used to be hand-built in three places and quietly diverged (see
// the project-attestation-links convention). Pure + Node-importable (no DOM at import; B falls back
// to '' off-browser).
//
// SYNC — the static pages (language / etymon / group / thesaurus) are rendered SERVER-side in Python
// and do NOT use this file, so several builders below have a Python twin that must render the SAME
// markup. When you change one, change its twin: both sides are tagged `SYNC(<key>)` — grep the key to
// find every site. Twins: SYNC(reflex-row), SYNC(etymon-row), SYNC(syllabify), SYNC(syllable-links),
// SYNC(protoform-fmt), SYNC(entity-urls).

export const B = (typeof window !== 'undefined' && window.STEDT_BASE) || '';
export const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
// SYNC(protoform-fmt) ↔ stedt/render/text.py alt() — normalise a proto-form (strip the leading *,
// which every emission site re-adds as literal text; star each ⪤-alternant). Keep identical.
export const altstar = s => String(s).replace(/^\s*\*\s*/, '').replace(/(⪤|\bOR\b|~|=)\s*\*?/g, '$1 *');
export const fmt = n => Number(n).toLocaleString();
// SYNC(sortkey) ↔ text.py sortkey + search.js sortkey — the case/accent-insensitive collation key
export const norm = s => String(s == null ? '' : s).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');

// --- canonical URLs: the ONE place each entity's address is built ---
// SYNC(entity-urls) ↔ stedt/render/shell.py {etymon,source,language,reflex}_href + the /thesaurus/{sk}
// category link — the server builds the same addresses; keep the URL shapes + conventions identical.
export const languageHref = lgid => `${B}/language/${lgid}`;            // top of a language page
export const reflexHref = (lgid, rn) => `${B}/language/${lgid}#rn${rn}`; // a specific attestation row
export const etymonHref = tag => `${B}/etymon/${tag}`;
export const sourceHref = abbr => `${B}/source/${esc(abbr)}`;
export const categoryHref = sk => `${B}/thesaurus/${esc(sk)}`;       // a reflex's semantic-category node
// render_note (server) ships root-relative xref links (/etymon/…) in the search DB's note HTML;
// prepend the page base so they resolve under /stedt (or wherever the site is mounted). The note is
// then injected as HTML (it's already escaped/sanitised by render_note), not re-escaped.
export const rebase = html => String(html == null ? '' : html).replace(/href="\//g, `href="${B}/`);

// --- per-syllable etymon links (faithful port of the original SylStation.syllabify): when a
// reflex's syllables are individually tagged, each links to its etymon. Char classes [(] [)] [|]
// stand in for the escaped \( \) \| to keep this readable. ---
// SYNC(syllabify) ↔ stedt/render/syllabify.py — same tokenizer in two runtimes; verified byte-equal
// over 40k tagged forms. Any change must stay identical (re-run that diff).
const _TONE = "⁰¹²³⁴⁵⁶⁷⁸0-9ˊˋ˥-˩";
const _DELIM = "-=≡≣+.,;/~◦⪤()↮ ";
const _HIDE = new RegExp('[(]([^' + _DELIM + _TONE + ']+)[)]', 'g');
const _START = new RegExp('^([' + _DELIM + ']+)');
const _REPOST = "([^" + _DELIM + _TONE + "]+[" + _TONE + "]+(?:[|]$)?)([" + _DELIM + "]*)";
const _REPRE = "([" + _TONE + "]{1,2}[^" + _DELIM + _TONE + "]+)([" + _DELIM + "]*)";
const _REDEL = "([^" + _DELIM + "]+)([" + _DELIM + "]*)";
function _syl1(s, reSrc) {
  s = s.replace(_HIDE, '（$1）'); let prefix = '';
  if (_START.test(s)) { const pm = _START.exec(s); prefix = pm[1]; s = s.substring(prefix.length); }
  const syls = [], dl = []; const re = new RegExp("^" + reSrc); let m;
  while ((m = re.exec(s)) && m[0].length) {
    s = s.substring(m[0].length);
    if (m[1].indexOf('|') !== -1 && syls.length) {
      syls[syls.length - 1] += dl.pop();
      syls[syls.length - 1] += m[1].replace(/（/g, '(').replace(/）/g, ')').replace('|', '');
    } else { syls.push(m[1].replace(/（/g, '(').replace(/）/g, ')')); }
    dl.push(m[2]);
  }
  if (!syls[0]) syls[0] = '';
  if (s) syls[syls.length - 1] += s;
  return { syls, dl, prefix, ok: !s.length };
}
function syllabify(s) {
  let r = _syl1(s, _REPOST);
  if (!r.ok) { r = _syl1(s, _REPRE); if (!r.ok) r = _syl1(s, _REDEL); }
  return r;
}
// SYNC(syllable-links) ↔ stedt/render/rows.py syl_pop(): the linked syllable's etymon-preview
// popover — the original's elink popup, all three parts: linked '#tag PLG *protoform ‘gloss’'
// header, the etymon's mesoroots (each PLG linked to its #ms-{grpno} row on the etymon page),
// and the allofam family (members linked, this etymon bold). The card sits BESIDE the trigger
// link inside .syl-w (nested <a> is invalid), so its links are real. Keep the markup identical.
const sylPop = e => {
  const g = e.pg ? ` ‘${esc(e.pg)}’` : '';
  let out = `<a class="sp-h" href="${etymonHref(e.tag)}">#${e.tag}${e.plg ? ' ' + esc(e.plg) : ''} *${altstar(esc(e.pf))}${g}</a>`;
  const meso = Array.isArray(e.meso) ? e.meso : [], fam = Array.isArray(e.fam) ? e.fam : [];
  if (meso.length) {
    if (fam.length) out += '<span class="sp-sec">Mesoroots</span>';
    out += meso.map(m =>
      `<a class="sp-m" href="${etymonHref(e.tag)}#ms-${esc(String(m.no || ''))}"><span class="sp-plg">${esc(m.plg || '')}</span> *${altstar(esc(m.f))}${m.g ? ` ‘${esc(m.g)}’` : ''}</a>`
    ).join('');
  }
  if (fam.length) {
    out += '<span class="sp-sec">Allofams</span>';
    out += fam.map(a => {
      const lab = `${esc(a.s)} #${a.tag}${a.plg ? ' ' + esc(a.plg) : ''} *${altstar(esc(a.pf))}${a.pg ? ` ‘${esc(a.pg)}’` : ''}`;
      return a.tag === e.tag
        ? `<span class="sp-m"><b>${lab}</b></span>`
        : `<a class="sp-m" href="${etymonHref(a.tag)}">${lab}</a>`;
    }).join('');
  }
  return `<span class="sylpop">${out}</span>`;
};

// SYNC(morph-codes) ↔ stedt/render/text.py morph_code/morph_label — STEDT's per-morpheme analysis
// codes (the original's lexicon.analysis): each non-cognate morpheme slot is tagged 'b' (borrowing,
// optionally with a source, e.g. 'bIndic'), 'p' (prefix), 's' (suffix), or 'm' (an identifiable but
// unreconstructed morpheme). A code is a run of letters/'?' only. Keep the predicate + labels
// identical to the server twin so both runtimes mark the same morphemes the same way.
const MORPH_RE = /^[A-Za-z?]+$/;
export const morphCode = tok => (tok && MORPH_RE.test(tok)) ? tok : null;
const morphLabel = code => {
  if (code === 'p') return 'prefix';
  if (code === 's') return 'suffix';
  if (code === 'm') return 'morpheme';
  if (code[0] === 'b') {                  // borrowing: b / b? / bSOURCE / b?SOURCE / bSOURCE?
    let rest = code.slice(1);
    const uncertain = rest.startsWith('?') || rest.endsWith('?');
    rest = rest.replace(/^\?+|\?+$/g, '');
    const lab = rest ? `${rest} loanword` : 'loanword';
    return uncertain ? `probable ${lab}` : lab;
  }
  return code;
};
// SYNC(morph-codes) ↔ stedt/render/rows.py morph_mark — a coded morpheme: text marked (.morph;
// borrowings add .morph-b) with a popover BESIDE it inside .morph-w (mirrors .syl-w). base escaped.
const morphMark = (code, base) =>
  `<span class="morph-w"><span class="${code[0] === 'b' ? 'morph morph-b' : 'morph'}">${base}</span><span class="mpop">${esc(morphLabel(code))}</span></span>`;
// SYNC(reflex-row) ↔ stedt/render/rows.py morph_chip — fallback trailing summary of the codes,
// used when the form can't be syllabified so the marks can't sit on the morphemes themselves.
const morphChip = codes => {
  if (!codes) return '';
  const labs = Object.keys(codes).map(Number).sort((a, b) => a - b).map(i => esc(morphLabel(codes[i]))).join(' · ');
  return `<span class="anl morphs">${labs}</span>`;
};

// SYNC(syllable-links) ↔ stedt/render/rows.py syl_form() + syl_pop(): the syllable-linked form
// + its etymon-preview popover. Keep the markup (a.syl, .sylpop, header + mesoroot lines) identical.
const sylLink = r => {                     // syllable-linked form HTML, or null to fall back
  if (!r.syn && !r.morph) return null;
  const syn = r.syn || {}, morph = r.morph || {};
  // headword arrives as `form` (search payload) or `reflex` (category payload) — same fallback
  // as the plain path below, or category rows lose their links (and ind-0 rows lost their TEXT:
  // syllabifying '' yields one empty syllable, which happily took the link)
  const head = r.form != null ? r.form : r.reflex;
  const sy = syllabify(String(head || '')), syls = sy.syls, dl = sy.dl;
  for (const k in syn) { if (+k >= syls.length) return null; }     // cognate tags must land on real syllables
  for (const k in morph) { if (+k >= syls.length) return null; }   // and so must codes
  const info = {};                         // tag -> {pf, pg}, for the syllable's etymon-preview popover
  (r.etyma || []).forEach(e => { if (e && e.tag != null) info[e.tag] = e; });
  let out = esc(sy.prefix || '');
  for (let i = 0; i < syls.length; i++) {
    const tag = syn[i];
    if (tag != null) {
      const base = esc(syls[i]), e = info[tag];
      const pop = e && e.pf ? sylPop(e) : '';
      const link = `<a class="syl" href="${etymonHref(tag)}">${base}</a>`;
      out += pop ? `<span class="syl-w">${link}${pop}</span>` : link;
    } else if (morph[i] != null) {
      out += morphMark(morph[i], esc(syls[i]));
    } else {
      out += esc(syls[i]);
    }
    out += esc(dl[i] || '').replace(/◦/g, '<span class="br">◦</span>');
  }
  return out;
};

// SYNC(display-form) ↔ stedt/render/rows.py disp_form — plain (unlinked) display of a stored form:
// strip the internal '|' analysis delimiter via the same syllabify+rejoin the linked path uses,
// escape, and mute the ◦ morpheme separator. Unpiped forms pass straight through.
export const dispForm = s => {
  s = String(s == null ? '' : s);
  if (s.indexOf('|') < 0) return esc(s).replace(/◦/g, '<span class="br">◦</span>');
  const sy = syllabify(s);
  let out = esc(sy.prefix || '');
  for (let i = 0; i < sy.syls.length; i++) {
    out += esc(sy.syls[i]);
    out += esc(sy.dl[i] || '').replace(/◦/g, '<span class="br">◦</span>');
  }
  return out;
};

// --- entity rows ---

// A reflex, shared by the search results and the thesaurus reflex list so they can't drift.
// SYNC(reflex-row) ↔ the server-rendered reflex rows in stedt/render/language.py — language()
// seginfo + stedt/render/etymon.py etymon() rfx builder. Keep the fields, order (POS before gloss), classes,
// roles (listitem — every container holding these rows carries role=list), and link
// targets identical across both runtimes.
// The whole row links to the form's attestation line (#rn) via a stretched overlay; the inner links
// sit above it (see .rx-go in site.css): the language name → the TOP of its language page, syllables
// / via chips → their etyma, source → its page, and a noted gloss stays interactive (shows its note).
// Accepts either `form` (search payload) or `reflex` (category payload) for the headword.
export const reflexRow = r => {
  const loc = r.srcid ? `: ${esc(r.srcid)}` : '';   // per-reflex locus (page/entry), like the entity pages
  const src = r.srcabbr ? `<a href="${sourceHref(r.srcabbr)}">${esc(r.citation || r.srcabbr)}${loc}</a>` : '';
  const pos = r.gfn ? `<span class="pos">${esc(r.gfn)}</span>` : '';   // sits before the gloss (.pos has margin-right)
  const gl = r.note
    ? `<span class="g noted" tabindex="0" aria-describedby="np${r.rn}">${esc(r.gloss)}<span class="notepop" role="note" id="np${r.rn}">${rebase(r.note)}</span></span>`
    : `<span class="g">${esc(r.gloss)}</span>`;
  const lf = sylLink(r); let mid;
  // etyma already linked inline in the syllable form don't repeat as trailing chips
  const inline = (lf && r.syn) ? new Set(Object.values(r.syn)) : new Set();
  const vias = (r.etyma || []).filter(x => x && x.tag != null && !inline.has(x.tag))
    .map(x => `<a class="via" href="${etymonHref(x.tag)}">*${altstar(esc(x.pf))}</a>`);
  const links = vias.length ? ` <span class="vias">${vias.join(' ')}</span>` : '';
  if (lf) {                              // syllables carry their own etymon links / morpheme marks
    mid = `<span class="lat">${lf}</span> ${pos}${gl}${links}`;
  } else {                              // plain form; trailing "via" chips + morpheme codes
    const form = r.form != null ? r.form : r.reflex;
    mid = `<span class="lat">${dispForm(form)}</span> ${pos}${gl}${links}${morphChip(r.morph)}`;
  }
  // the reflex's semantic category (search rows only; the thesaurus-category list omits it as redundant)
  if (r.cat) mid += ` <a class="rx-cat" href="${categoryHref(r.semkey)}">${esc(r.cat)}</a>`;
  const go = `<a class="rx-go" href="${reflexHref(r.lgid, r.rn)}" aria-label="${esc(r.language)}: go to this entry"></a>`;
  return `<div class="rx-hit" role="listitem">${go}<a class="lang" href="${languageHref(r.lgid)}">${esc(r.language)}</a><span class="rx-mid">${mid}</span><span class="rx-src">${src}</span></div>`;
};

// A reconstruction (etymon) result row.
// SYNC(etymon-row) ↔ the server-rendered etymon lists: stedt/render/group.py reconinfo() (group
// page) + stedt/render/indexes.py dinfo (thesaurus). Keep protoform / PLG / #tag / reflex-count /
// exemplary-badge identical.
export const etymonRow = e => `<a class="ety-hit" href="${etymonHref(e.tag)}"><span class="pf2 lat"><span class="star">*</span>${altstar(esc(e.protoform))}</span><span class="pg2">${esc(e.protogloss)}</span><span class="tagn">${esc(e.plg)} #${e.tag}${e.nreflex ? ` · ${fmt(e.nreflex)} reflex${e.nreflex == 1 ? '' : 'es'}` : ''}${e.exemplary ? ' · <span class="exm">exemplary</span>' : ''}${e.public === 0 || e.public === '0' || e.provisional ? ' · <span class="prov">provisional</span>' : ''}</span></a>`;

// A language result row.
export const languageRow = l => `<a class="ety-hit" href="${languageHref(l.lgid)}"><span class="rf">${esc(l.language)}</span><span class="gl2">${fmt(l.n)} reflex${l.n == 1 ? '' : 'es'}</span><span class="tagn">language</span></a>`;
