// Client-side search for the static STEDT site. Recreates render.py's search_data() exactly
// (reflexes via FTS5 MATCH, etyma via LIKE) — but runs the queries fully IN-MEMORY via the
// official SQLite WASM build (which includes FTS5). The DB is downloaded once and cached.
//
// Why in-memory and not range requests: GitHub Pages force-gzips files and serves COMPRESSED
// byte-ranges, which breaks the byte-offset math a range-based VFS needs. A whole-file fetch
// is gzip-transparent, so we download the DB once (gzip transfer), keep it in memory, and
// cache the bytes (Cache API, ETag-revalidated) so repeat visits/searches are instant.
import sqlite3InitModule from '@sqlite.org/sqlite-wasm';

const base = () => (typeof window !== 'undefined' && window.STEDT_BASE) || '';
// Cache-key the DB by a data-content version (injected by build_static) so it re-downloads only
// when the data changes — not on every deploy (GitHub Pages' ETag is mtime-based, so it churns).
const dbUrl = () => base() + '/search.sqlite3'
  + ((typeof window !== 'undefined' && window.STEDT_DB_VERSION) ? '?v=' + window.STEDT_DB_VERSION : '');

let _dbp = null;
function getDb() {
  if (!_dbp) {
    _dbp = loadDb().then((db) => { if (typeof window !== 'undefined') window.stedtDbLoaded = true; return db; });
  }
  return _dbp;
}

async function loadDb() {
  const sqlite3 = await sqlite3InitModule({ locateFile: () => base() + '/assets/sqlite3.wasm' });
  const bytes = await fetchDbBytes(dbUrl());
  const p = sqlite3.wasm.allocFromTypedArray(bytes);
  const db = new sqlite3.oo1.DB();
  db.checkRc(sqlite3.capi.sqlite3_deserialize(
    db.pointer, 'main', p, bytes.length, bytes.length,
    sqlite3.capi.SQLITE_DESERIALIZE_FREEONCLOSE | sqlite3.capi.SQLITE_DESERIALIZE_RESIZEABLE,
  ));
  return db;
}

// Download once; serve from the Cache API afterward so repeat visits don't re-download. The URL
// carries the data version, so a cache hit means "same data" — no revalidation needed; a data
// change yields a new URL (miss). Old versions are evicted so storage holds one DB at a time.
// Falls back to a plain fetch where caches are unavailable (e.g. file://).
async function fetchDbBytes(url) {
  try {
    const cache = await caches.open('stedt-search-db');
    const hit = await cache.match(url);
    if (hit) return new Uint8Array(await hit.arrayBuffer());
    const buf = await (await fetch(url)).arrayBuffer();
    for (const k of await cache.keys()) await cache.delete(k);   // evict older DB versions
    await cache.put(url, new Response(buf));
    return new Uint8Array(buf);
  } catch (e) {
    return new Uint8Array(await (await fetch(url)).arrayBuffer());
  }
}

function run(db, sql, params) {
  const rows = [];
  db.exec({ sql, bind: params, rowMode: 'object', resultRows: rows });
  return rows;
}

// --- the two queries, identical to render.py's search_data() ---
const REFLEX_SQL = `
  SELECT ln.language AS language, l.reflex AS form, l.gloss AS gloss, l.rn AS rn,
         e.tag AS tag, e.protoform AS pf, e.protogloss AS pg
  FROM lexicon l JOIN languagenames ln ON ln.lgid = l.lgid
  LEFT JOIN lx_et_hash h ON h.rn = l.rn AND h.tag > 0
  LEFT JOIN etyma e ON e.tag = h.tag
  WHERE l.rn IN (SELECT rowid FROM lexicon_fts WHERE lexicon_fts MATCH ? LIMIT ?)
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

const ftsQ = (s) => { s = s.replace(/"/g, ' ').trim(); return s ? '"' + s + '"' : '""'; };

export async function stedtSearch(query, limit = 40) {
  query = (query || '').trim();
  const db = await getDb();
  // a leading "*" is reconstruction notation, not a search operator; "*" alone means "all"
  const qe = (query.startsWith('*') && query !== '*') ? query.slice(1).trim() : query;

  let etyma = [];
  if (query === '*') {
    etyma = run(db, ETYMA_ALL_SQL, [limit]);
  } else if (qe) {
    const like = '%' + qe + '%';
    const nohy = '%' + qe.replace(/[-|◦\s]/g, '') + '%';   // morpheme-boundary–insensitive
    etyma = run(db, ETYMA_SQL, [like, like, nohy, qe, limit]);
  }

  let reflexes = [];
  if (qe && query !== '*') {
    reflexes = run(db, REFLEX_SQL, [ftsQ(qe), limit + 40, limit]);
  }
  return { etyma, reflexes };
}

if (typeof window !== 'undefined') {
  window.stedtDbLoaded = false;
  window.stedtSearch = stedtSearch;
}
