// Reconstructions index: the full etyma list ships once as JSON in <script id="recon-data"> and is
// rendered client-side in windows, with an instant in-page filter. Shares the URL + escape helpers
// with the other views. NOTE: it keeps its own compact-ARRAY row rather than rows.js `etymonRow`,
// because the payload is a positional array (to keep the ~4k-etyma JSON small) and — unlike the
// search etymon row — it does NOT comma-format the reflex count and pre-applies `alt()` server-side.
// Aligning it with `etymonRow` is a deliberate output change (see project-attestation-links).
import { windowedList } from './windowed.js';
import { esc, norm, etymonHref } from './rows.js';

(function () {
  var DATA = JSON.parse(document.getElementById('recon-data').textContent);
  for (var i = 0; i < DATA.length; i++) { var r = DATA[i]; r[5] = norm(r[1] + ' ' + r[2] + ' ' + r[3] + ' #' + r[0]); }
  var view = DATA;
  var list = document.getElementById('recon-list'),
    none = document.querySelector('.rnone'),
    count = document.getElementById('rcount'),
    input = document.getElementById('rfilter');
  function row(r) {
    var rc = r[4] ? (' · ' + r[4] + (r[4] == 1 ? ' reflex' : ' reflexes')) : '';
    return '<a class="ety-hit" href="' + etymonHref(r[0]) + '">' +
      '<span class="pf2 lat">' + esc(r[1]) + '</span>' +
      '<span class="pg2">' + esc(r[2]) + '</span>' +
      '<span class="tagn">' + esc(r[3]) + ' #' + esc(r[0]) + rc + '</span></a>';
  }
  function updateCount(shown) {
    var t = DATA.length, m = view.length;
    var s = (m === t) ? t.toLocaleString() + ' etyma' : m.toLocaleString() + (m === 1 ? ' match' : ' matches');
    if (shown < m) s += ' · ' + shown.toLocaleString() + ' shown';
    count.textContent = s;
  }
  var win = windowedList(list, {
    row: row, onRender: function (shown) {
      updateCount(shown); none.style.display = view.length ? 'none' : 'block';
    }
  });
  function apply() {
    var q = norm(input.value.trim());
    view = q ? DATA.filter(function (r) { return r[5].indexOf(q) >= 0; }) : DATA;
    win.reset(view);
  }
  var tmr; input.addEventListener('input', function () { clearTimeout(tmr); tmr = setTimeout(apply, 90); });
  win.reset(DATA);
})();
