// Thesaurus "Attestations": on page load, query the search WASM DB (window.stedtFormsByCategory,
// from search.js) for every reflex filed at this node's semkey(s) — carried in data-semkeys — then
// render in 200-row windows with an in-memory filter, so a 13k-form category stays a light DOM.
import { windowedList } from './windowed.js';

(function () {
  var wrap = document.querySelector('.catwrap'); if (!wrap) return;
  var B = window.STEDT_BASE || '';
  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  };
  var norm = function (s) { return String(s == null ? '' : s).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, ''); };
  var altstar = function (s) { return String(s).replace(/^\s*\*\s*/, '').replace(/⪤\s*\*?/g, '⪤ *'); };
  var list = wrap.querySelector('.catlist'),
    count = wrap.querySelector('.catcount'),
    input = wrap.querySelector('.catfilter');
  var DATA = null, view = [], loaded = false, loading = false;
  function row(r) {
    var home = B + '/language/' + r.lgid + '#rn' + r.rn;
    var gl = r.note ? '<span class="g noted" tabindex="0">' + esc(r.gloss) + '<span class="notepop" role="note">' + esc(r.note) + '</span></span>' : '<span class="g">' + esc(r.gloss) + '</span>';
    var pos = r.gfn ? ' <span class="pos">' + esc(r.gfn) + '</span>' : '';
    var via = (r.etyma && r.etyma.length) ? ' <span class="vias">' + r.etyma.map(function (x) {
      return '<a class="via" href="' + B + '/etymon/' + x.tag + '">› *' + altstar(esc(x.pf)) + '</a>';
    }).join(' ') + '</span>' : '';
    var src = r.srcabbr ? '<a href="' + B + '/source/' + esc(r.srcabbr) + '">' + esc(r.citation || r.srcabbr) + '</a>' : '';
    return '<div class="rx-hit"><a class="lang" href="' + home + '">' + esc(r.language) + '</a>' +
      '<span class="rx-mid"><a class="lat" href="' + home + '">' + esc(r.reflex) + '</a> ' + gl + pos + via + '</span>' +
      '<span class="rx-src">' + src + '</span></div>';
  }
  function updateCount(shown) {
    if (!DATA) { count.textContent = ''; return; }
    var t = DATA.length, m = view.length;
    var s = (m === t) ? t.toLocaleString() + (t === 1 ? ' form' : ' forms')
      : m.toLocaleString() + (m === 1 ? ' match' : ' matches') + ' of ' + t.toLocaleString();
    if (shown < m) s += ' · ' + shown.toLocaleString() + ' shown';
    count.textContent = s;
  }
  var win = windowedList(list, { row: row, onRender: function (shown) { updateCount(shown); } });
  function apply() {
    var q = norm(input.value.trim());
    view = q ? DATA.filter(function (r) { return r._k.indexOf(q) >= 0; }) : DATA;
    win.reset(view);
  }
  function load() {
    if (loaded || loading) return; loading = true; count.textContent = 'Loading forms…';
    var keys; try { keys = JSON.parse(wrap.getAttribute('data-semkeys')); } catch (e) { keys = []; }
    var go = function () {
      window.stedtFormsByCategory(keys).then(function (rows) {
        DATA = rows || [];
        for (var i = 0; i < DATA.length; i++) { var r = DATA[i]; r._k = norm(r.reflex + ' ' + r.gloss + ' ' + r.language); }
        view = DATA; loaded = true; loading = false; apply();
      }).catch(function () { count.textContent = 'Could not load forms.'; loading = false; });
    };
    var wait = function (n) {
      if (window.stedtFormsByCategory) return go();
      if (n <= 0) { count.textContent = 'Search is unavailable.'; loading = false; return; }
      setTimeout(function () { wait(n - 1); }, 150);
    };
    wait(40);
  }
  var tmr; input.addEventListener('input', function () { if (!loaded) return; clearTimeout(tmr); tmr = setTimeout(apply, 90); });
  load();   // attestations are shown by default (no expand) — fetch on page load
})();
