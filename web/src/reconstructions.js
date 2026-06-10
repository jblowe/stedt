// Reconstructions index: the full etyma list ships once as JSON in <script id="recon-data"> and is
// rendered client-side in windows, with an instant in-page filter. The payload is a compact
// positional ARRAY (to keep the ~4k-etyma JSON small) carrying the RAW protoform; we adapt each row
// to the shared etymonRow so it renders identically to the search results' reconstruction rows.
import { windowedList } from './windowed.js';
import { etymonRow, norm } from './rows.js';

(function () {
  var DATA = JSON.parse(document.getElementById('recon-data').textContent);
  // Filter key goes in a NEW trailing slot — the payload's own slots (5 exemplary, 6 provisional)
  // must stay untouched (writing the key into r[5] once badged every etymon "exemplary").
  for (var i = 0; i < DATA.length; i++) { var r = DATA[i]; r[7] = norm(r[1] + ' ' + r[2] + ' ' + r[3] + ' #' + r[0]); }
  var view = DATA;
  var list = document.getElementById('recon-list'),
    none = document.querySelector('.rnone'),
    count = document.getElementById('rcount'),
    input = document.getElementById('rfilter');
  var row = r => etymonRow({ tag: r[0], protoform: r[1], protogloss: r[2], plg: r[3], nreflex: r[4], exemplary: r[5], provisional: r[6] });
  function updateCount(shown) {
    var t = DATA.length, m = view.length;
    // 'reconstructions', not 'etyma' — the sitewide term (nav, About, search, group metabars)
    var s = (m === t) ? t.toLocaleString() + (t === 1 ? ' reconstruction' : ' reconstructions')
      : m.toLocaleString() + (m === 1 ? ' match' : ' matches');
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
    view = q ? DATA.filter(function (r) { return r[7].indexOf(q) >= 0; }) : DATA;
    win.reset(view);
  }
  var tmr; input.addEventListener('input', function () { clearTimeout(tmr); tmr = setTimeout(apply, 90); });
  win.reset(DATA);
})();
