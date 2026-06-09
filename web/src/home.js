// Home-page autocomplete. Queries the shared WASM search (window.stedtSearch, from search.js) and
// renders compact suggestions. Was a hand-rolled inline <script> in templates/home.html that drifted
// from every other surface (hardcoded /etymon/ URLs, and it linked a reflex to its etymon instead of
// its attestation). Now it imports the SAME url helpers + esc/altstar the result rows use (rows.js),
// so it can't drift again: a reflex suggestion links to its #rn attestation (the attestation-links
// convention), an etymon to its page, a language to its page. Kept deliberately compact (no source /
// note / chips) — it's an autocomplete, not a result row.
import { B, esc, altstar, etymonHref, languageHref, reflexHref } from './rows.js';

const bs = document.getElementById('bs'), d = document.getElementById('drop');
if (bs && d) {
  let t;
  const note = m => { d.innerHTML = `<div class="cap" style="padding:10px 12px">${m}</div>`; d.style.display = 'block'; };
  const langRow = x => `<a href="${languageHref(x.lgid)}"><span class="k">lang</span><span>${esc(x.language)}</span></a>`;
  const etymonRow = e => `<a href="${etymonHref(e.tag)}"><span class="k">recon</span><span><span class="recon">${altstar(esc(e.protoform))}</span> · <span class="gl">${esc(e.protogloss)}</span></span></a>`;
  const reflexRow = x => `<a href="${reflexHref(x.lgid, x.rn)}"><span class="k">${esc(x.language)}</span><span><span class="lat">${esc(x.form)}</span> ${x.gfn ? `<span class="pos">${esc(x.gfn)}</span>` : ''}<span class="gl">${esc(x.gloss)}</span></span></a>`;
  bs.addEventListener('input', () => {
    clearTimeout(t);
    const q = bs.value.trim();
    if (q.length < 2) { d.style.display = 'none'; return; }
    t = setTimeout(async () => {
      if (!window.stedtSearch) return;
      if (!window.stedtDbLoaded) note('Loading search…');
      let j;
      try { j = await window.stedtSearch(q, 8); } catch (e) { note('Search is unavailable.'); return; }
      const h = [
        ...(j.languages || []).map(langRow),
        ...j.etyma.map(etymonRow),
        ...j.reflexes.map(reflexRow),
      ].join('');
      d.innerHTML = h;
      d.style.display = h ? 'block' : 'none';
    }, 180);
  });
  bs.addEventListener('keydown', e => { if (e.key === 'Enter') location = `${B}/search?q=${encodeURIComponent(bs.value)}`; });
  document.addEventListener('click', e => { if (!e.target.closest('.bigsearch')) d.style.display = 'none'; });
}
