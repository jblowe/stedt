// Phonological-inventory viewer: render one page of the vendored Phonological Inventories monograph
// (Namkung, ed. 1996) to a canvas, entirely in the browser. pdf.js slices the requested page from
// the ~1.2 MB PDF on demand, so the site ships only the PDF — no pre-rendered page images committed
// to the repo, and the view never drifts from the source. This module (pdf.js + glue) is fetched
// lazily by language-page.js the first time a reader opens the inventory, so it costs nothing on a
// page nobody expands; the PDF is loaded once per session and shared across pages.
import * as pdfjsLib from 'pdfjs-dist';

var BASE = (typeof window !== 'undefined' && window.STEDT_BASE) || '';
pdfjsLib.GlobalWorkerOptions.workerSrc = BASE + '/assets/pdf.worker.min.mjs';

var docs = {}; // url -> Promise<PDFDocumentProxy>, so one fetch serves every page on the site
function getDoc(url) {
  return docs[url] || (docs[url] = pdfjsLib.getDocument({ url: url }).promise);
}

// Crop the page's white margins so the inventory fills the column (the build-time version trimmed
// with ImageMagick -trim; here we scan the rendered pixels for the ink bounding box). The page is
// black ink on white, so the red channel alone distinguishes ink from paper.
function inkBox(ctx, w, h) {
  var d = ctx.getImageData(0, 0, w, h).data, INK = 245;
  var top = h, left = w, right = -1, bottom = -1;
  for (var y = 0; y < h; y++) {
    for (var x = 0; x < w; x++) {
      if (d[(y * w + x) * 4] < INK) {
        if (x < left) left = x;
        if (x > right) right = x;
        if (y < top) top = y;
        if (y > bottom) bottom = y;
      }
    }
  }
  if (right < left) return { x: 0, y: 0, w: w, h: h }; // blank page — show it whole
  var pad = Math.round(w * 0.012);
  left = Math.max(0, left - pad);
  top = Math.max(0, top - pad);
  right = Math.min(w - 1, right + pad);
  bottom = Math.min(h - 1, bottom + pad);
  return { x: left, y: top, w: right - left + 1, h: bottom - top + 1 };
}

// Render `pageNum` of `url` into `figure` (prepended before the caption). CSS caps the display at
// 600px; the canvas backing store is scaled by devicePixelRatio so it stays crisp.
export async function render(figure, url, pageNum) {
  var note = document.createElement('p');
  note.className = 'phoninv-load';
  note.textContent = 'Rendering…';
  figure.prepend(note);
  try {
    var pdf = await getDoc(url);
    var page = await pdf.getPage(pageNum);
    // Backing-store density ≥2 so the trimmed page stays crisp when CSS scales it to fill the
    // ~600px column (the content is narrower than the full page, so width:100% would otherwise
    // upscale it). Capped at 3 to bound memory on high-DPI phones.
    var q = Math.min(Math.max(window.devicePixelRatio || 1, 2), 3);
    var unit = page.getViewport({ scale: 1 });
    var vp = page.getViewport({ scale: (600 * q) / unit.width });
    var full = document.createElement('canvas');
    full.width = Math.ceil(vp.width);
    full.height = Math.ceil(vp.height);
    var fctx = full.getContext('2d');
    await page.render({ canvasContext: fctx, viewport: vp, background: '#ffffff' }).promise;
    var box = inkBox(fctx, full.width, full.height);
    var canvas = document.createElement('canvas');
    canvas.className = 'phoninv-img';
    canvas.width = box.w;
    canvas.height = box.h;
    canvas.getContext('2d').drawImage(full, box.x, box.y, box.w, box.h, 0, 0, box.w, box.h);
    figure.prepend(canvas);
  } finally {
    note.remove();
  }
}
