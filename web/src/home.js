// Home-page autocomplete. Queries the shared WASM search (window.stedtSearch, from search.js) and
// renders compact suggestions. Was a hand-rolled inline <script> in templates/home.html that drifted
// from every other surface (hardcoded /etymon/ URLs, and it linked a reflex to its etymon instead of
// its attestation). Now it imports the SAME url helpers + esc/altstar the result rows use (rows.js),
// so it can't drift again: a reflex suggestion links to its #rn attestation (the attestation-links
// convention), an etymon to its page, a language to its page. Kept deliberately compact (no source /
// note / chips) — it's an autocomplete, not a result row.
import { B, esc, altstar, glossQ, etymonHref, languageHref, reflexHref } from './rows.js';

const bs = document.getElementById('bs'), d = document.getElementById('drop');
if (bs && d) {
  let t;
  // Combobox state (input has role=combobox, #drop role=listbox — static attrs in home.html).
  // `act` is the active-descendant index into the dropdown's option anchors, -1 = none.
  let act = -1;
  const opts = () => [...d.querySelectorAll('a')];
  const open = () => { d.style.display = 'block'; bs.setAttribute('aria-expanded', 'true'); };
  const close = () => { d.style.display = 'none'; bs.setAttribute('aria-expanded', 'false'); setActive(-1); };
  const setActive = i => {
    const os = opts();
    act = os.length ? i : -1;
    os.forEach((o, n) => { o.classList.toggle('active', n === act); o.setAttribute('aria-selected', n === act ? 'true' : 'false'); });
    if (act >= 0) bs.setAttribute('aria-activedescendant', os[act].id);
    else bs.removeAttribute('aria-activedescendant');
  };
  const note = m => { d.innerHTML = `<div class="cap" style="padding:10px 12px">${m}</div>`; open(); };
  const langRow = x => `<a href="${languageHref(x.lgid)}"><span class="k">lang</span><span>${esc(x.language)}</span></a>`;
  const etymonRow = e => `<a href="${etymonHref(e.tag)}"><span class="k">recon</span><span><span class="recon"><span class="star">*</span>${altstar(esc(e.protoform))}</span> · <span class="gl">${esc(e.protogloss)}</span></span></a>`;
  const reflexRow = x => `<a href="${reflexHref(x.lgid, x.rn)}"><span class="k">${esc(x.language)}</span><span><span class="lat">${esc(x.form)}</span> ${x.gfn ? `<span class="pos">${esc(x.gfn)}</span>` : ''}<span class="g">${glossQ(x.gloss)}</span></span></a>`;
  bs.addEventListener('input', () => {
    clearTimeout(t);
    const q = bs.value.trim();
    if (q.length < 2) { close(); return; }
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
      opts().forEach((o, n) => { o.id = `bs-opt-${n}`; o.setAttribute('role', 'option'); });
      setActive(-1);
      h ? open() : close();
    }, 180);
  });
  bs.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      const n = opts().length;
      if (!n || d.style.display === 'none') return;
      e.preventDefault();
      setActive(((act + (e.key === 'ArrowDown' ? 1 : -1)) % n + n) % n);
    } else if (e.key === 'Escape') {
      close();
    } else if (e.key === 'Enter' && act >= 0) {
      e.preventDefault();   // an option is active: follow it instead of submitting the form
      location = opts()[act].href;
    }
  });
  // plain Enter (no active option) falls through to the form; without JS the same form GETs
  // /search?q= server-side — here we preventDefault and navigate so JS users don't double-load
  bs.closest('form').addEventListener('submit', e => {
    e.preventDefault();
    location = `${B}/search?q=${encodeURIComponent(bs.value)}`;
  });
  document.addEventListener('click', e => { if (!e.target.closest('.bigsearch')) close(); });
}
