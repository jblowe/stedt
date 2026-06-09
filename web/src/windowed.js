// Windowed infinite-scroll list engine, shared by the big client-rendered lists (the
// reconstructions index, search results, and thesaurus attestations). Rows render in CHUNK-sized
// batches to keep the DOM light, but a trailing spacer reserves the whole list's (over)estimated
// height up front — so the scrollbar reflects the FULL dataset from first paint instead of growing
// as you scroll. Scrolling toward the end renders the rows that belong there in one batch. The
// height estimate is biased high on purpose (MARGIN): real content then only ever settles UP toward
// a bar you've dragged down, never grows past it.
export function windowedList(list, opts) {
  opts = opts || {};
  var CHUNK = opts.chunk || 200, row = opts.row, MARGIN = opts.margin || 1.15, BUFFER = 600;
  var data = [], shown = 0, rowH = 0;
  var spacer = document.createElement('div');
  spacer.className = 'wl-spacer'; spacer.setAttribute('aria-hidden', 'true');
  list.parentNode.insertBefore(spacer, list.nextSibling);
  function resize() {                        // reserve (over)estimated height for the unrendered tail
    var rem = data.length - shown;
    spacer.style.height = (rem > 0 && rowH > 0) ? Math.ceil(rem * rowH * MARGIN) + 'px' : '';
  }
  function renderTo(target) {                // render rows [shown,target) in a single batch
    if (target > data.length) target = data.length;
    if (target > shown) {
      var h = '';
      for (var i = shown; i < target; i++) h += row(data[i]);
      list.insertAdjacentHTML('beforeend', h);
      shown = target;
      if (list.offsetHeight > 0) rowH = list.offsetHeight / shown;   // running average; adapts to wrap/zoom
    }
    resize();
    if (opts.onRender) opts.onRender(shown, data.length);
  }
  function fill() {                          // render until rendered rows cover the viewport (+buffer)
    var vh = window.innerHeight || document.documentElement.clientHeight, guard = 0;
    while (shown < data.length && guard++ < 4000) {
      var top = spacer.getBoundingClientRect().top;   // boundary between real rows and the reserve
      if (top >= vh + BUFFER) break;
      var step = CHUNK;
      if (rowH > 0) { var need = Math.ceil((vh + BUFFER - top) / rowH); if (need > step) step = need; }
      renderTo(shown + step);
    }
  }
  function reset(newData) {                  // (re)bind data, e.g. after an in-page filter change
    data = newData || []; shown = 0; list.innerHTML = '';
    renderTo(CHUNK); fill();
  }
  var queued = false;
  function onScroll() {
    if (queued) return; queued = true;
    requestAnimationFrame(function () { queued = false; fill(); });
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll, { passive: true });
  return { reset: reset, fill: fill };
}
