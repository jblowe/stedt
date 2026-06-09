// Shared client-side presentation layer for entity rows (search results, thesaurus attestations,
// reconstructions index). Goal: ONE row builder and ONE url builder per entity type, so the views
// can't drift — a reflex row used to be hand-built in three places and quietly diverged (see the
// project-attestation-links convention). Pure + Node-importable (no DOM at import; B falls back to
// '' off-browser) so web/test can pin the contract.

export const B = (typeof window !== 'undefined' && window.STEDT_BASE) || '';
export const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
export const altstar = s => String(s).replace(/^\s*\*\s*/, '').replace(/⪤\s*\*?/g, '⪤ *');
export const fmt = n => Number(n).toLocaleString();
export const norm = s => String(s == null ? '' : s).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');

// --- canonical URLs: the ONE place each entity's address is built ---
export const languageHref = lgid => `${B}/language/${lgid}`;            // top of a language page
export const reflexHref = (lgid, rn) => `${B}/language/${lgid}#rn${rn}`; // a specific attestation row
export const etymonHref = tag => `${B}/etymon/${tag}`;
export const sourceHref = abbr => `${B}/source/${esc(abbr)}`;
// render_note (server) ships root-relative xref links (/etymon/…) in the search DB's note HTML;
// prepend the page base so they resolve under /stedt (or wherever the site is mounted). The note is
// then injected as HTML (it's already escaped/sanitised by render_note), not re-escaped.
export const rebase = html => String(html == null ? '' : html).replace(/href="\//g, `href="${B}/`);

// --- per-syllable etymon links (faithful port of the original SylStation.syllabify): when a
// reflex's syllables are individually tagged, each links to its etymon. Char classes [(] [)] [|]
// stand in for the escaped \( \) \| to keep this readable. ---
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
const sylLink = r => {                     // syllable-linked form HTML, or null to fall back
  if (!r.syn) return null;
  const sy = syllabify(String(r.form || '')), syls = sy.syls, dl = sy.dl;
  for (const k in r.syn) { if (+k >= syls.length) return null; }   // tags must land on real syllables
  const pf = {};                           // tag -> protoform, for the ruby annotation above each syllable
  (r.etyma || []).forEach(e => { if (e && e.tag != null) pf[e.tag] = e.pf; });
  let out = esc(sy.prefix || '');
  for (let i = 0; i < syls.length; i++) {
    const tag = r.syn[i];
    if (tag != null) {
      const base = esc(syls[i]), lbl = pf[tag];
      const inner = lbl ? `<ruby>${base}<rt>*${altstar(esc(lbl))}</rt></ruby>` : base;
      out += `<a class="syl" href="${etymonHref(tag)}">${inner}</a>`;
    } else {
      out += esc(syls[i]);
    }
    out += esc(dl[i] || '').replace(/◦/g, '<span class="br">◦</span>');
  }
  return out;
};

// --- entity rows ---

// An attested form, shared by the search results and the thesaurus attestations so they can't drift.
// The whole row links to the form's attestation line (#rn) via a stretched overlay; the inner links
// sit above it (see .rx-go in site.css): the language name → the TOP of its language page, syllables
// / via chips → their etyma, source → its page, and a noted gloss stays interactive (shows its note).
// Accepts either `form` (search payload) or `reflex` (category payload) for the headword.
export const reflexRow = r => {
  const src = r.srcabbr ? `<a href="${sourceHref(r.srcabbr)}">${esc(r.citation || r.srcabbr)}</a>` : '';
  const pos = r.gfn ? `<span class="pos">${esc(r.gfn)}</span>` : '';   // sits before the gloss (.pos has margin-right)
  const gl = r.note
    ? `<span class="g noted" tabindex="0">${esc(r.gloss)}<span class="notepop" role="note">${rebase(r.note)}</span></span>`
    : `<span class="g">${esc(r.gloss)}</span>`;
  const lf = sylLink(r); let mid;
  if (lf) {                              // syllables carry their own etymon links
    mid = `<span class="lat">${lf}</span> ${pos}${gl}`;
  } else {                              // plain form; trailing "via" chips keep their etymon links
    const form = r.form != null ? r.form : r.reflex;
    const links = (r.etyma && r.etyma.length) ? ` <span class="vias">${r.etyma.map(x => `<a class="via" href="${etymonHref(x.tag)}">*${altstar(esc(x.pf))}</a>`).join(' ')}</span>` : '';
    mid = `<span class="lat">${esc(form)}</span> ${pos}${gl}${links}`;
  }
  const go = `<a class="rx-go" href="${reflexHref(r.lgid, r.rn)}" aria-label="${esc(r.language)}: go to this entry"></a>`;
  return `<div class="rx-hit">${go}<a class="lang" href="${languageHref(r.lgid)}">${esc(r.language)}</a><span class="rx-mid">${mid}</span><span class="rx-src">${src}</span></div>`;
};

// A reconstruction (etymon) result row.
export const etymonRow = e => `<a class="ety-hit" href="${etymonHref(e.tag)}"><span class="pf2 lat">${altstar(esc(e.protoform))}</span><span class="pg2">${esc(e.protogloss)}</span><span class="tagn">${esc(e.plg)} #${e.tag}${e.nreflex ? ` · ${fmt(e.nreflex)} reflex${e.nreflex == 1 ? '' : 'es'}` : ''}</span></a>`;

// A language result row.
export const languageRow = l => `<a class="ety-hit" href="${languageHref(l.lgid)}"><span class="rf">${esc(l.language)}</span><span class="gl2">${fmt(l.n)} attested form${l.n == 1 ? '' : 's'}</span><span class="tagn">language</span></a>`;
