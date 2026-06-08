// Client-side search for the static STEDT site. Recreates serve.py's search_data()
// exactly — the same two SQL queries (reflexes via FTS5, etyma via LIKE) — but runs them
// in the browser against search.db over HTTP range requests (sql.js-httpvfs). Returns the
// same {etyma, reflexes} shape the old /api/search returned, so the existing dropdown +
// results rendering are reused verbatim.
import { createDbWorker } from "sql.js-httpvfs";

const base = () => (typeof window !== "undefined" && window.STEDT_BASE) || "";

let _dbp = null;
function getDb() {
  if (!_dbp) {
    _dbp = createDbWorker(
      [{ from: "inline", config: { serverMode: "full", url: base() + "/search.db", requestChunkSize: 4096 } }],
      base() + "/assets/sqlite.worker.js",
      base() + "/assets/sql-wasm.wasm",
    ).then((w) => { _worker = w; return w.db; });
  }
  return _dbp;
}
let _worker = null;
export async function searchStats() {        // proof/diagnostics: bytes fetched vs total
  await getDb();
  return _worker ? _worker.worker.getStats() : null;
}

// --- the two queries, identical to serve.py's search_data() ---
const REFLEX_SQL = `
  SELECT ln.language AS language, l.reflex AS form, l.gloss AS gloss, l.rn AS rn,
         e.tag AS tag, e.protoform AS pf, e.protogloss AS pg
  FROM lexicon l JOIN languagenames ln ON ln.lgid = l.lgid
  LEFT JOIN lx_et_hash h ON h.rn = l.rn AND h.tag > 0
  LEFT JOIN etyma e ON e.tag = h.tag
  WHERE l.rn IN (SELECT rn FROM lexicon_fts WHERE lexicon_fts MATCH ? LIMIT ?)
  GROUP BY l.rn LIMIT ?`;

const ETYMA_SQL = `
  SELECT e.tag AS tag, g.plg AS plg, e.protoform AS protoform, e.protogloss AS protogloss, e.semkey AS semkey
  FROM etyma e LEFT JOIN languagegroups g ON g.grpid = e.grpid
  WHERE coalesce(upper(e.status), '') != 'DELETE'
    AND (e.protogloss LIKE ? OR e.protoform LIKE ?
         OR replace(replace(replace(e.protoform, '-', ''), '|', ''), '◦', '') LIKE ?)
  ORDER BY CASE WHEN upper(e.protogloss) LIKE upper(?) || '%' THEN 0 ELSE 1 END, e.protogloss
  LIMIT ?`;

const ETYMA_ALL_SQL = `
  SELECT e.tag AS tag, g.plg AS plg, e.protoform AS protoform, e.protogloss AS protogloss, e.semkey AS semkey
  FROM etyma e LEFT JOIN languagegroups g ON g.grpid = e.grpid
  WHERE coalesce(upper(e.status), '') != 'DELETE' ORDER BY e.tag LIMIT ?`;

const ftsQ = (q) => { q = q.replace(/"/g, " ").trim(); return q ? '"' + q + '"' : '""'; };

export async function stedtSearch(q, limit = 40) {
  q = (q || "").trim();
  const db = await getDb();
  // a leading "*" is reconstruction notation, not a search operator; "*" alone means "all"
  const qe = (q.startsWith("*") && q !== "*") ? q.slice(1).trim() : q;

  let etyma = [];
  if (q === "*") {
    etyma = await db.query(ETYMA_ALL_SQL, [limit]);
  } else if (qe) {
    const like = "%" + qe + "%";
    const nohy = "%" + qe.replace(/[-|◦\s]/g, "") + "%";   // morpheme-boundary–insensitive
    etyma = await db.query(ETYMA_SQL, [like, like, nohy, qe, limit]);
  }

  let reflexes = [];
  if (qe && q !== "*") {
    reflexes = await db.query(REFLEX_SQL, [ftsQ(qe), limit + 40, limit]);
  }
  return { etyma, reflexes };
}

if (typeof window !== "undefined") {
  window.stedtSearch = stedtSearch;
  // warm the worker + wasm + first DB pages while the user reads the page
  window.addEventListener("DOMContentLoaded", () => { try { getDb(); } catch (e) {} });
}
