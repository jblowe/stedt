// Search results page: reads ?q= and renders matches client-side via window.stedtSearch (the data
// layer in search.js, loaded on every page), windowing each result section with windowedList.
import { windowedList } from './windowed.js';

const B = window.STEDT_BASE || '';
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const altstar = s => String(s).replace(/^\s*\*\s*/, '').replace(/⪤\s*\*?/g, '⪤ *');
const fmt = n => Number(n).toLocaleString();
const CHUNK = 200;
const bs = document.getElementById('bs');
bs.addEventListener('keydown', e => { if (e.key === 'Enter') location = B + '/search?q=' + encodeURIComponent(bs.value); });
const etyRow = e => `<a class="ety-hit" href="${B}/etymon/${e.tag}"><span class="pf2 lat">${altstar(esc(e.protoform))}</span><span class="pg2">${esc(e.protogloss)}</span><span class="tagn">${esc(e.plg)} #${e.tag}${e.nreflex ? ` · ${fmt(e.nreflex)} reflex${e.nreflex == 1 ? '' : 'es'}` : ''}</span></a>`;
// --- per-syllable etymon links (faithful port of the original SylStation.syllabify) ---
// Syllabify a form the way the data was tagged so lx_et_hash.ind (syllable position -> etymon)
// aligns; tagged syllables then link to their etymon. Char classes [(] [)] [|] stand in for the
// escaped \( \) \| to keep this readable.
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
  let out = esc(sy.prefix || '');
  for (let i = 0; i < syls.length; i++) {
    out += (r.syn[i] != null
      ? `<a class="syl" href="${B}/etymon/${r.syn[i]}">${esc(syls[i])}</a>`
      : esc(syls[i]))
      + esc(dl[i] || '').replace(/◦/g, '<span class="br">◦</span>');
  }
  return out;
};
const rfxRow = r => {
  const home = `${B}/language/${r.lgid}#rn${r.rn}`;
  const src = r.srcabbr ? `<a href="${B}/source/${esc(r.srcabbr)}">${esc(r.citation || r.srcabbr)}</a>` : '';
  const pos = r.gfn ? ` <span class="pos">${esc(r.gfn)}</span>` : '';
  // the gloss is styled (italic·soft) so it reads distinct without quotes; a note marks it with a
  // circled-i and reveals on hover/focus
  const gl = r.note
    ? `<span class="g noted" tabindex="0">${esc(r.gloss)}<span class="notepop" role="note">${esc(r.note)}</span></span>`
    : `<span class="g">${esc(r.gloss)}</span>`;
  const lf = sylLink(r); let mid;
  if (lf) {                              // syllables carry their own etymon links
    mid = `<span class="lat">${lf}</span> ${gl}${pos}`;
  } else {                               // plain form; trailing "via" chips keep their etymon links
    const links = (r.etyma && r.etyma.length) ? ` <span class="vias">${r.etyma.map(x => `<a class="via" href="${B}/etymon/${x.tag}">› *${altstar(esc(x.pf))}</a>`).join(' ')}</span>` : '';
    mid = `<span class="lat">${esc(r.form)}</span> ${gl}${pos}${links}`;
  }
  // the whole row navigates to the form's attestation (#rn) via a stretched overlay link; the inner
  // etymon / source links sit above it (see .rx-go in site.css) so they keep their own targets
  const go = `<a class="rx-go" href="${home}" aria-label="${esc(r.language)}: go to this entry"></a>`;
  return `<div class="rx-hit">${go}<span class="lang">${esc(r.language)}</span><span class="rx-mid">${mid}</span><span class="rx-src">${src}</span></div>`;
};
// attested-form rows are pre-sorted by subgroup; emit a Stammbaum-subgroup header when it changes
let _rxsub = null;
const rfxGrouped = r => {
  const key = (r.grpno || '') + '|' + (r.subgroup || '');
  let head = '';
  if (key !== _rxsub) {
    _rxsub = key; const code = r.grpno ? `<span class="grpno">${esc(r.grpno)}</span>` : '';
    head = `<div class="rx-sub">${code}${esc(r.subgroup || '(unclassified)')}</div>`;
  }
  return head + rfxRow(r);
};
const langRow = x => `<a class="ety-hit" href="${B}/language/${x.lgid}"><span class="rf">${esc(x.language)}</span><span class="gl2">${fmt(x.n)} attested form${x.n == 1 ? '' : 's'}</span><span class="tagn">language</span></a>`;
function sectionLabel(title, total, fetched) {
  let h = '<div class="sec-label">' + esc(title) + '<span class="sec-n">' + fmt(total);
  if (fetched < total) h += ' · first ' + fmt(fetched) + ' shown';
  return h + '</span></div>';
}
function windowed(host, data, rowFn) {
  const list = document.createElement('div'); host.appendChild(list);
  windowedList(list, { chunk: CHUNK, row: rowFn }).reset(data);
}
function block(title, total, data, rowFn) {
  const res = document.getElementById('results');
  res.insertAdjacentHTML('beforeend', sectionLabel(title, total, data.length));
  const host = document.createElement('div'); res.appendChild(host);
  windowed(host, data, rowFn);
}
async function run() {
  const q = (new URLSearchParams(location.search).get('q') || '').trim();
  bs.value = q;
  const srh = document.getElementById('srh'), sub = document.getElementById('srsub'), res = document.getElementById('results');
  if (!q) { srh.textContent = 'Search'; return; }
  srh.textContent = 'Results for ' + (q === '*' ? 'all reconstructions' : '“' + q + '”');
  if (!window.stedtSearch) return;
  if (!window.stedtDbLoaded) res.innerHTML = '<p class="cap">Loading search…</p>';
  let r;
  try { r = await window.stedtSearch(q, null); }
  catch (err) { res.innerHTML = '<p class="cap">Search is unavailable.</p>'; return; }
  const parts = [];
  if (r.languageTotal) parts.push(fmt(r.languageTotal) + ' language' + (r.languageTotal == 1 ? '' : 's'));
  parts.push(fmt(r.etymaTotal) + ' reconstruction' + (r.etymaTotal == 1 ? '' : 's'));
  parts.push(fmt(r.reflexTotal) + ' attested form' + (r.reflexTotal == 1 ? '' : 's'));
  sub.textContent = parts.join(' · ');
  res.innerHTML = '';
  if (r.languageTotal) block('Languages', r.languageTotal, r.languages, langRow);
  if (r.etymaTotal) block('Reconstructions', r.etymaTotal, r.etyma, etyRow);
  if (r.reflexTotal) { _rxsub = null; block('Attested forms', r.reflexTotal, r.reflexes, rfxGrouped); }
  if (!r.languageTotal && !r.etymaTotal && !r.reflexTotal) res.innerHTML = '<p class="cap">No matches.</p>';
}
window.addEventListener('DOMContentLoaded', run);
