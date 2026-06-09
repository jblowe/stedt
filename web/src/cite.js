// Citation helpers for the etymon + source "Cite this entry" boxes: stamp today's date into every
// .adate span, and wire each .copybtn to copy its data-cite text (with [ACCESSED] replaced by the
// date). The per-page citation strings ride in the data-cite attributes; this is just the behavior.
(function () {
  var D = new Date().toISOString().slice(0, 10);
  document.querySelectorAll('.adate').forEach(function (e) { e.textContent = D; });
  document.querySelectorAll('.copybtn').forEach(function (b) {
    b.addEventListener('click', function () {
      navigator.clipboard.writeText((b.dataset.cite || '').replace(/\[ACCESSED\]/g, D));
      b.textContent = 'Copied';
    });
  });
})();
