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
    d.addEventListener('toggle', function () { if (d.open) fill(d); });
    if (d.open) fill(d);
  });
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
