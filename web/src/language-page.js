// Language page: attested-form sections render their rows lazily. Each <details> carries its forms
// as inert <script class="seg-src"> text and materialises them the first time it opens (or on load
// if it starts open), so a 7,700-form lect doesn't build ~50k DOM nodes the reader never looks at.
// reveal() also handles a #rn<id> deep link (e.g. from a thesaurus "attested forms" link) that
// points into a section not yet opened, and tags the row with .rn-target for the highlight — a
// lazily-injected row can't be relied on to match :target (the fragment was set before it existed),
// so the class is applied explicitly rather than left to CSS.
(function () {
  function fill(d) {
    if (d.dataset.filled) return;
    var s = d.querySelector('script.seg-src'), b = d.querySelector('.seg-body');
    if (s && b) { b.innerHTML = s.textContent; d.dataset.filled = '1'; }
  }
  var segs = [].slice.call(document.querySelectorAll('details.seg'));
  segs.forEach(function (d) {
    d.addEventListener('toggle', function () { if (d.open) { fill(d); filterRows(d); } });
    if (d.open) fill(d);
  });

  // ---- source filter: show only one source's record of this lect (the canonical page keeps
  // every source; this restores the original's language×source view as a view, not a page).
  // Rows carry their source in the a.src href; unopened sections are counted by scanning their
  // inert template text, so chips and section-hiding work without materialising anything.
  var pick = document.getElementById('srcpick'), cur = '';
  function rowAbbr(r) {
    var a = r.querySelector('a.src'), m = a && a.getAttribute('href').match(/\/source\/([^\/#?]+)$/);
    return m ? decodeURIComponent(m[1]) : '';
  }
  function filterRows(d) {
    if (!pick || !d.dataset.filled) return;
    [].forEach.call(d.querySelectorAll('.seg-body .rfx'), function (r) {
      r.classList.toggle('srchide', !!cur && rowAbbr(r) !== cur);
    });
  }
  function segCount(d) {                       // matching rows, without forcing a fill
    if (!cur) return null;
    var s = d.querySelector('script.seg-src');
    if (d.dataset.filled || !s) {
      var k = 0;
      [].forEach.call(d.querySelectorAll('.seg-body .rfx'), function (r) { if (rowAbbr(r) === cur) k++; });
      return k;
    }
    return s.textContent.split('/source/' + cur + '"').length - 1;
  }
  function applyFilter() {
    if (!pick) return;
    var total = 0;
    segs.forEach(function (d) {
      var c = d.querySelector('summary .c');
      if (c && c.dataset.n == null) c.dataset.n = c.textContent;
      if (d.dataset.defopen == null) d.dataset.defopen = d.open ? '1' : '0';
      filterRows(d);
      var k = segCount(d);
      total += k || 0;
      if (c) c.textContent = (k == null) ? c.dataset.n : k + ' of ' + c.dataset.n;
      d.classList.toggle('srchide', k === 0);  // a section with nothing to show steps aside
    });
    // a small filtered view opens itself (the server's own openall rule: <100 rows);
    // clearing the filter restores each section's build-time state
    var btn = document.querySelector('.toggle-all');
    if (cur && total < 100) {
      segs.forEach(function (d) { if (!d.classList.contains('srchide')) { fill(d); filterRows(d); d.open = true; } });
      if (btn) { btn.setAttribute('data-all', '1'); btn.textContent = 'Collapse all'; }
    } else if (!cur) {
      segs.forEach(function (d) { d.open = d.dataset.defopen === '1'; });
      if (btn) { btn.setAttribute('data-all', '0'); btn.textContent = 'Expand all'; }
    }
    var q = new URLSearchParams(location.search);
    if (cur) q.set('src', cur); else q.delete('src');
    var qs = q.toString();
    history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
  }
  if (pick) {
    pick.addEventListener('change', function () { cur = pick.value; applyFilter(); });
    [].forEach.call(document.querySelectorAll('.src-only'), function (b) {
      b.addEventListener('click', function () {
        cur = (cur === b.dataset.abbr) ? '' : b.dataset.abbr;  // click again to clear
        pick.value = cur;
        applyFilter();
      });
    });
    var want = new URLSearchParams(location.search).get('src');
    if (want) {
      pick.value = want;
      // an unknown ?src (typo, stale link, other lect's source) must not blank the page
      if (pick.value === want) { cur = want; applyFilter(); }
      else history.replaceState(null, '', location.pathname + location.hash);
    }
  }
  var btn = document.querySelector('.toggle-all');
  if (btn) btn.addEventListener('click', function () {
    var open = btn.getAttribute('data-all') !== '1';
    segs.forEach(function (d) { if (open) fill(d); d.open = open; });
    btn.setAttribute('data-all', open ? '1' : '0');
    btn.textContent = open ? 'Collapse all' : 'Expand all';
  });
  function reveal() {
    var prev = document.querySelector('.rfx.rn-target'); if (prev) prev.classList.remove('rn-target');
    var h = location.hash; if (!h || h.length < 2) return;
    var id; try { id = decodeURIComponent(h.slice(1)); } catch (e) { return; }
    var el = document.getElementById(id);
    if (!el) {
      var needle = 'id="' + id + '"';
      for (var i = 0; i < segs.length; i++) {
        var s = segs[i].querySelector('script.seg-src');
        if (s && s.textContent.indexOf(needle) >= 0) { fill(segs[i]); segs[i].open = true; break; }
      }
      el = document.getElementById(id);
    }
    if (!el) return;
    var d = el.closest('details'); if (d && !d.open) { fill(d); d.open = true; }
    el.classList.add('rn-target');
    el.scrollIntoView({ block: 'center' });
    // A cold load scrolls before web fonts arrive; their reflow can nudge the row off its mark, so
    // re-settle once fonts are ready — but only if this row is still the target.
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () {
      if (location.hash.slice(1) === id) el.scrollIntoView({ block: 'center' });
    });
  }
  window.addEventListener('hashchange', reveal); reveal();
})();
