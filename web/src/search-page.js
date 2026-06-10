// Search results page: reads ?q= and renders matches client-side via window.stedtSearch (the data
// layer in search.js, loaded on every page), windowing each result section with windowedList. The
// row markup + URLs live in rows.js (shared with the thesaurus + reconstructions views).
import { windowedList } from './windowed.js';
import { B, esc, fmt, norm, reflexRow, etymonRow, languageRow } from './rows.js';

const CHUNK = 200;
const bs = document.getElementById('bs');
// the input sits in a real GET form (the no-JS path); preventDefault so JS users navigate once
bs.closest('form').addEventListener('submit', e => {
  e.preventDefault();
  location = B + '/search?q=' + encodeURIComponent(bs.value);
});
// attested-form rows are pre-sorted by subgroup; emit a Stammbaum-subgroup header when it changes.
// The header is a listitem too: it streams through the same role=list container as the rows
// (bands span render chunks, so a per-band wrapper is impossible), and role=list only admits
// listitem children — the original's table counted band header rows as rows the same way.
let _rxsub = null;
const rfxGrouped = r => {
  const key = (r.grpno || '') + '|' + (r.subgroup || '');
  let head = '';
  if (key !== _rxsub) {
    _rxsub = key; const code = r.grpno ? `<span class="grpno">${esc(r.grpno)}</span>` : '';
    head = `<div class="rx-sub" role="listitem">${code}${esc(r.subgroup || '(unclassified)')}</div>`;
  }
  return head + reflexRow(r);
};
function sectionLabel(title, total, fetched) {
  let h = '<div class="sec-label">' + esc(title) + '<span class="sec-n">' + fmt(total);
  if (fetched < total) h += ' · first ' + fmt(fetched) + ' shown';
  return h + '</span></div>';
}
// label → role=list on the container (reflex sections only: their rows are role=listitem divs;
// the .ety-hit language/reconstruction rows are <a> links, and role=listitem would override
// their link semantics, so those sections stay plain). windowedList's spacer is a SIBLING of
// the container, so only listitems land inside the role=list element.
function windowed(host, data, rowFn, label) {
  const list = document.createElement('div'); host.appendChild(list);
  if (label) { list.setAttribute('role', 'list'); list.setAttribute('aria-label', label); }
  windowedList(list, { chunk: CHUNK, row: rowFn }).reset(data);
}
function block(title, total, data, rowFn) {
  const res = document.getElementById('results');
  res.insertAdjacentHTML('beforeend', sectionLabel(title, total, data.length));
  const host = document.createElement('div'); res.appendChild(host);
  windowed(host, data, rowFn);
}
// the Reflexes section gets a sort control: 'by subgroup' is the default Stammbaum-grouped view;
// any other key re-sorts the fetched rows in memory (case/accent-insensitive) and renders them
// flat — subgroup band headers would be meaningless mid-sort. _lk/_fk come precomputed from
// search.js; gloss/source keys are derived here on demand.
const RX_KEYS = {
  language: r => [r._lk, r._fk],
  form:     r => [r._fk, r._lk],
  gloss:    r => [norm(r.gloss), r._lk, r._fk],
  source:   r => [norm(r.citation || r.srcabbr), r._lk, r._fk],
};
function reflexBlock(total, data) {
  const res = document.getElementById('results');
  res.insertAdjacentHTML('beforeend', sectionLabel('Reflexes', total, data.length));
  const lab = res.lastElementChild;
  const sel = document.createElement('select');
  sel.setAttribute('aria-label', 'Sort reflexes');
  for (const [v, t] of [['subgroup', 'by subgroup'], ['language', 'by language'], ['form', 'by form'],
                        ['gloss', 'by gloss'], ['source', 'by source']]) sel.add(new Option(t, v));
  const wrap = document.createElement('label');
  wrap.className = 'rxsort'; wrap.append('Sort '); wrap.appendChild(sel);
  lab.appendChild(wrap);
  const host = document.createElement('div'); res.appendChild(host);
  const render = () => {
    host.innerHTML = '';
    const keyFn = RX_KEYS[sel.value];
    if (!keyFn) { _rxsub = null; windowed(host, data, rfxGrouped, 'Reflexes'); return; }   // default order, grouped
    const keyed = data.map(r => [keyFn(r), r]);
    keyed.sort((a, b) => {
      for (let i = 0; i < a[0].length; i++) { if (a[0][i] < b[0][i]) return -1; if (a[0][i] > b[0][i]) return 1; }
      return 0;
    });
    windowed(host, keyed.map(p => p[1]), reflexRow, 'Reflexes');
  };
  sel.addEventListener('change', render);
  render();
}
async function run() {
  const q = (new URLSearchParams(location.search).get('q') || '').trim();
  bs.value = q;
  const srh = document.getElementById('srh'), sub = document.getElementById('srsub'), res = document.getElementById('results');
  if (!q) { srh.textContent = 'Search'; return; }
  srh.textContent = 'Results for ' + (q === '*' ? 'all reconstructions' : '“' + q + '”');
  document.title = (q === '*' ? 'All reconstructions' : '“' + q + '”') + ' · Search · STEDT';
  if (!window.stedtSearch) return;
  // #srsub is a role=status live region: transient state lands there so SRs announce it,
  // and the result totals below replace it when they arrive.
  if (!window.stedtDbLoaded) {
    sub.textContent = 'Loading search…';
    // first visit downloads the search index; show how far along it is
    addEventListener('stedt-db-progress', (e) => {
      if (window.stedtDbLoaded) return;
      const mb = (n) => (n / 1048576).toFixed(n < 10485760 ? 1 : 0);
      sub.textContent = 'Loading search index… ' + mb(e.detail.loaded) + ' / ' + mb(e.detail.total) + ' MB';
    });
  }
  let r;
  try { r = await window.stedtSearch(q, null); }
  catch (err) { sub.textContent = 'Search is unavailable.'; res.innerHTML = ''; return; }
  const parts = [];
  if (r.languageTotal) parts.push(fmt(r.languageTotal) + ' language' + (r.languageTotal == 1 ? '' : 's'));
  parts.push(fmt(r.etymaTotal) + ' reconstruction' + (r.etymaTotal == 1 ? '' : 's'));
  parts.push(fmt(r.reflexTotal) + ' reflex' + (r.reflexTotal == 1 ? '' : 'es'));
  sub.textContent = parts.join(' · ');
  res.innerHTML = '';
  if (r.languageTotal) block('Languages', r.languageTotal, r.languages, languageRow);
  if (r.etymaTotal) block('Reconstructions', r.etymaTotal, r.etyma, etymonRow);
  if (r.reflexTotal) reflexBlock(r.reflexTotal, r.reflexes);
  if (!r.languageTotal && !r.etymaTotal && !r.reflexTotal) res.innerHTML = '<p class="cap">No matches.</p>';
}
window.addEventListener('DOMContentLoaded', run);
