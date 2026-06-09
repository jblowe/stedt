// Search results page: reads ?q= and renders matches client-side via window.stedtSearch (the data
// layer in search.js, loaded on every page), windowing each result section with windowedList. The
// row markup + URLs live in rows.js (shared with the thesaurus + reconstructions views).
import { windowedList } from './windowed.js';
import { B, esc, fmt, reflexRow, etymonRow, languageRow } from './rows.js';

const CHUNK = 200;
const bs = document.getElementById('bs');
bs.addEventListener('keydown', e => { if (e.key === 'Enter') location = B + '/search?q=' + encodeURIComponent(bs.value); });
// attested-form rows are pre-sorted by subgroup; emit a Stammbaum-subgroup header when it changes
let _rxsub = null;
const rfxGrouped = r => {
  const key = (r.grpno || '') + '|' + (r.subgroup || '');
  let head = '';
  if (key !== _rxsub) {
    _rxsub = key; const code = r.grpno ? `<span class="grpno">${esc(r.grpno)}</span>` : '';
    head = `<div class="rx-sub">${code}${esc(r.subgroup || '(unclassified)')}</div>`;
  }
  return head + reflexRow(r);
};
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
  parts.push(fmt(r.reflexTotal) + ' reflex' + (r.reflexTotal == 1 ? '' : 'es'));
  sub.textContent = parts.join(' · ');
  res.innerHTML = '';
  if (r.languageTotal) block('Languages', r.languageTotal, r.languages, languageRow);
  if (r.etymaTotal) block('Reconstructions', r.etymaTotal, r.etyma, etymonRow);
  if (r.reflexTotal) { _rxsub = null; block('Reflexes', r.reflexTotal, r.reflexes, rfxGrouped); }
  if (!r.languageTotal && !r.etymaTotal && !r.reflexTotal) res.innerHTML = '<p class="cap">No matches.</p>';
}
window.addEventListener('DOMContentLoaded', run);
