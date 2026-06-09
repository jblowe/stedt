// Client-side search for the static STEDT site. Reproduces the site's search query logic exactly
// (reflexes via FTS5 MATCH, etyma via LIKE) — but runs the queries fully IN-MEMORY via the
// official SQLite WASM build (which includes FTS5). The DB is downloaded once and cached.
//
// Why in-memory and not range requests: GitHub Pages force-gzips files and serves COMPRESSED
// byte-ranges, which breaks the byte-offset math a range-based VFS needs. A whole-file fetch
// is gzip-transparent, so we download the DB once (gzip transfer), keep it in memory, and
// cache the bytes (Cache API, ETag-revalidated) so repeat visits/searches are instant.
import sqlite3InitModule from '@sqlite.org/sqlite-wasm';

const base = () => (typeof window !== 'undefined' && window.STEDT_BASE) || '';
// Cache-key the DB by a data-content version (injected by `stedt render`) so it re-downloads only
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

// --- the two queries, matching the site's search semantics ---
// A reflex can belong to several etyma (polymorphemic) — aggregate them all (non-DELETE only),
// rather than GROUP BY picking one arbitrarily. json_group_array → parsed/deduped in stedtSearch.
// Each result row carries its source (the WORK it's attested in: srcabbr + srcbib.citation), its
// Stammbaum subgroup (grpno + grp, for grouping), and its lexical note (lxnote) — same detail the
// entry pages show. (Per-syllable tag positions live in lx_et_hash.ind for future syllable links.)
const RFX_COLS = `ln.language AS language, l.reflex AS form, l.gloss AS gloss, l.gfn AS gfn, l.rn AS rn, l.lgid AS lgid,
         ln.srcabbr AS srcabbr, sb.citation AS citation, g.grpno AS grpno, g.grp AS subgroup, nt.note AS note,
         json_group_array(json_object('tag', e.tag, 'pf', e.protoform, 'ind', h.ind))
           FILTER (WHERE e.tag IS NOT NULL) AS etyma`;
const RFX_JOINS = `
  FROM lexicon l JOIN languagenames ln ON ln.lgid = l.lgid
  LEFT JOIN languagegroups g ON g.grpid = ln.grpid
  LEFT JOIN srcbib sb ON sb.srcabbr = ln.srcabbr
  LEFT JOIN lxnote nt ON nt.rn = l.rn
  LEFT JOIN lx_et_hash h ON h.rn = l.rn AND h.tag > 0
  LEFT JOIN etyma e ON e.tag = h.tag AND coalesce(upper(e.status), '') != 'DELETE'`;
const REFLEX_SQL = `
  SELECT ${RFX_COLS}${RFX_JOINS}
  WHERE l.rn IN (SELECT rowid FROM lexicon_fts WHERE lexicon_fts MATCH ? LIMIT ?)
    AND ln.language NOT LIKE '*%'
  GROUP BY l.rn LIMIT ?`;

const ETYMA_SQL = `
  SELECT e.tag AS tag, g.plg AS plg, e.protoform AS protoform, e.protogloss AS protogloss, e.semkey AS semkey, e.nreflex AS nreflex
  FROM etyma e LEFT JOIN languagegroups g ON g.grpid = e.grpid
  WHERE coalesce(upper(e.status), '') != 'DELETE'
    AND (e.protogloss LIKE ? OR e.protoform LIKE ?
         OR replace(replace(replace(e.protoform, '-', ''), '|', ''), '◦', '') LIKE ?)
  ORDER BY CASE WHEN upper(e.protogloss) LIKE upper(?) || '%' THEN 0 ELSE 1 END, e.protogloss
  LIMIT ?`;

const ETYMA_ALL_SQL = `
  SELECT e.tag AS tag, g.plg AS plg, e.protoform AS protoform, e.protogloss AS protogloss, e.semkey AS semkey, e.nreflex AS nreflex
  FROM etyma e LEFT JOIN languagegroups g ON g.grpid = e.grpid
  WHERE coalesce(upper(e.status), '') != 'DELETE' ORDER BY e.tag LIMIT ?`;

// Every reflex (lexicon row) carries its own gloss-level semkey — independent of any etymon.
// The thesaurus browse drills category -> etymon, so the ~310k reflexes tagged to no etymon
// are otherwise unreachable by meaning. This lists the attested forms filed directly under a
// semantic node, lazily (on expand), reusing the already-loaded search DB.
const FORMS_BY_CAT_SQL = (n) => `
  SELECT l.rn AS rn, l.reflex AS reflex, l.gloss AS gloss, l.gfn AS gfn, l.lgid AS lgid,
         ln.language AS language, ln.srcabbr AS srcabbr, sb.citation AS citation, nt.note AS note,
         json_group_array(json_object('tag', e.tag, 'pf', e.protoform, 'ind', h.ind))
           FILTER (WHERE e.tag IS NOT NULL) AS etyma
  FROM lexicon l JOIN languagenames ln ON ln.lgid = l.lgid
  LEFT JOIN srcbib sb ON sb.srcabbr = ln.srcabbr
  LEFT JOIN lxnote nt ON nt.rn = l.rn
  LEFT JOIN lx_et_hash h ON h.rn = l.rn AND h.tag > 0
  LEFT JOIN etyma e ON e.tag = h.tag AND coalesce(upper(e.status), '') != 'DELETE'
  WHERE l.semkey IN (${Array(n).fill('?').join(',')})
    AND ln.language NOT LIKE '*%'
  GROUP BY l.rn
  ORDER BY ln.language, l.reflex`;

// Shape a reflex row's aggregated-etyma JSON (from json_group_array) in ONE place, so the search
// results and the thesaurus-category attestations derive identical etyma/tag/pf/syn. Without this the
// two drifted: the category list dropped lx_et_hash.ind and never built r.syn, so its shared reflexRow
// silently lost per-syllable links and always fell back to chips. Mutates r in place.
export function shapeReflexEtyma(r) {
  let ets = [];
  try { ets = JSON.parse(r.etyma || '[]'); } catch (e) { ets = []; }
  const seen = new Set(), uniq = [], byInd = {}; let conflict = false;
  for (const x of ets) {
    if (!x || x.tag == null) continue;
    if (!seen.has(x.tag)) { seen.add(x.tag); uniq.push(x); }
    if (x.ind != null) {                       // syllable position -> etymon, for per-syllable links
      if (byInd[x.ind] != null && byInd[x.ind] !== x.tag) conflict = true;
      else byInd[x.ind] = x.tag;
    }
  }
  r.etyma = uniq;
  r.tag = uniq.length ? uniq[0].tag : null;     // first etymon: compact single-link consumers (home dropdown)
  r.pf = uniq.length ? uniq[0].pf : null;
  // ind->tag map for per-syllable etymon links; null if a syllable is ambiguously multi-tagged
  r.syn = (!conflict && Object.keys(byInd).length) ? byInd : null;
}

export async function stedtFormsByCategory(semkeys) {
  const keys = (Array.isArray(semkeys) ? semkeys : [semkeys]).filter(Boolean);
  if (!keys.length) return [];
  const db = await getDb();
  const rows = run(db, FORMS_BY_CAT_SQL(keys.length), keys);
  for (const r of rows) shapeReflexEtyma(r);
  return rows;
}

// AND the whitespace-separated tokens (FTS5 treats a space between terms as AND), each wrapped as
// a quoted phrase so it can match in ANY column (form/gloss/language). So "hit Lotha" finds rows
// where 'hit' (gloss) AND 'Lotha' (language) both occur — the combined query the single box used
// to fail silently (it matched the whole input as one adjacent phrase → always zero).
const ftsQ = (s) => {
  const toks = s.replace(/["()*:^]/g, ' ').split(/\s+/).filter(Boolean);
  return toks.length ? toks.map((t) => '"' + t + '"').join(' ') : '""';
};

// excludes proto-language pseudo-forms (language '*…'): those are reconstructions, surfaced under
// the Reconstructions section, not "attested forms" — so they shouldn't appear/count as reflexes.
const REFLEX_COUNT_SQL = `
  SELECT count(*) AS n
  FROM lexicon_fts f JOIN lexicon l ON l.rn = f.rowid JOIN languagenames ln ON ln.lgid = l.lgid
  WHERE f.lexicon_fts MATCH ? AND ln.language NOT LIKE '*%'`;
const ETYMA_COUNT_SQL = `
  SELECT count(*) AS n FROM etyma e
  WHERE coalesce(upper(e.status), '') != 'DELETE'
    AND (e.protogloss LIKE ? OR e.protoform LIKE ?
         OR replace(replace(replace(e.protoform, '-', ''), '|', ''), '◦', '') LIKE ?)`;
const ETYMA_COUNT_ALL_SQL = `SELECT count(*) AS n FROM etyma WHERE coalesce(upper(status), '') != 'DELETE'`;
// Language-name matches are their own result type: a query that names a language should offer a
// direct jump to that language's page, not just bury it in the reflex list.
const LANG_SQL = `
  SELECT ln.language AS language, ln.lgid AS lgid, count(l.rn) AS n
  FROM languagenames ln JOIN lexicon l ON l.lgid = ln.lgid
  WHERE ln.language LIKE ? AND ln.language NOT LIKE '*%'
  GROUP BY ln.lgid`;

// FTS5's unicode61 tokenizer doesn't insert boundaries between Han characters, so a CJK substring
// is only found when it stands alone as a token — silently undercounting in this Chinese-heavy
// corpus. Detect CJK and route those queries through a substring LIKE over the stored lexicon text
// (mirroring the original site's RLIKE form search) instead of FTS MATCH.
const hasCJK = (s) => /[㐀-鿿豈-﫿]|[\ud840-\ud87f][\udc00-\udfff]/.test(s || '');
const likeToks = (s) => s.replace(/["()*:^%_]/g, ' ').split(/\s+/).filter(Boolean);
const _likeWhere = (n) => Array(n).fill('(reflex LIKE ? OR gloss LIKE ?)').join(' AND ');
const reflexLikeSql = (n) => `
  SELECT ${RFX_COLS}${RFX_JOINS}
  WHERE l.rn IN (SELECT l2.rn FROM lexicon l2 JOIN languagenames n2 ON n2.lgid = l2.lgid
                 WHERE ${_likeWhere(n)} AND n2.language NOT LIKE '*%' LIMIT ?)
  GROUP BY l.rn LIMIT ?`;
const reflexLikeCountSql = (n) => `
  SELECT count(*) AS n FROM lexicon l JOIN languagenames ln ON ln.lgid = l.lgid
  WHERE ${_likeWhere(n)} AND ln.language NOT LIKE '*%'`;

// Natural-order key for a Stammbaum grpno so "6.1.10" sorts after "6.1.2" (lexical would invert
// them); blanks sort last. Used to group/order the attested-form results by subgroup.
const gkey = (s) => String(s == null || s === '' ? '~~' : s).split('.').map((x) => x.padStart(4, '0')).join('.');

// limit caps the rows fetched per type (the page windows them client-side); the *Total fields are
// the true match counts so the UI can show "first N of M shown" instead of silently truncating.
export async function stedtSearch(query, limit = 40) {
  query = (query || '').trim();
  const db = await getDb();
  // a leading "*" is reconstruction notation, not a search operator; "*" alone means "all"
  const qe = (query.startsWith('*') && query !== '*') ? query.slice(1).trim() : query;
  // limit <= 0 / null means "no cap": fetch every match and let the page infinite-scroll through
  // them (SQLite reads LIMIT -1 as unbounded). The home dropdown still passes a small limit.
  const lim = (limit == null || limit <= 0) ? -1 : limit;

  let etyma = [], etymaTotal = 0;
  if (query === '*') {
    etyma = run(db, ETYMA_ALL_SQL, [lim]);
    etymaTotal = run(db, ETYMA_COUNT_ALL_SQL, [])[0].n;
  } else if (qe) {
    const like = '%' + qe + '%';
    const nohy = '%' + qe.replace(/[-|◦\s]/g, '') + '%';   // morpheme-boundary–insensitive
    etyma = run(db, ETYMA_SQL, [like, like, nohy, qe, lim]);
    etymaTotal = run(db, ETYMA_COUNT_SQL, [like, like, nohy])[0].n;
  }

  let reflexes = [], reflexTotal = 0;
  if (qe && query !== '*') {
    const inner = lim < 0 ? -1 : lim + 40;
    if (hasCJK(qe)) {
      // CJK substrings are invisible to FTS MATCH (see hasCJK note) — match them with LIKE instead.
      const toks = likeToks(qe), p = [];
      for (const t of toks) { const w = '%' + t + '%'; p.push(w, w); }
      reflexTotal = run(db, reflexLikeCountSql(toks.length), p)[0].n;
      reflexes = run(db, reflexLikeSql(toks.length), [...p, inner, lim]);
    } else {
      const m = ftsQ(qe);
      reflexTotal = run(db, REFLEX_COUNT_SQL, [m])[0].n;
      reflexes = run(db, REFLEX_SQL, [m, inner, lim]);
    }
    // parse the aggregated etyma JSON into deduped etyma/tag/pf/syn (shared with the category list)
    for (const r of reflexes) {
      shapeReflexEtyma(r);
      r._gk = gkey(r.grpno);   // precompute the subgroup sort key once (invariant per row)
    }
    // order by subgroup (then language, form) so the page can render Stammbaum-grouped sections
    reflexes.sort((a, b) => {
      const ga = a._gk, gb = b._gk;
      return ga < gb ? -1 : ga > gb ? 1
        : (a.language || '') < (b.language || '') ? -1 : (a.language || '') > (b.language || '') ? 1
        : (a.form || '') < (b.form || '') ? -1 : (a.form || '') > (b.form || '') ? 1 : 0;
    });
  }

  let languages = [], languageTotal = 0;
  if (qe && query !== '*' && qe.length >= 2) {
    const rows = run(db, LANG_SQL, ['%' + qe + '%']);
    // A canonical language page aggregates every source-variant lgid of a (name, subgroup), so its
    // form count is the SUM across variants — match that (was: the single largest variant's count,
    // which underreported multi-source lects ~2-4x). Link to the best-attested lgid = that lect's
    // canonical page. (Same-name lects in different subgroups, e.g. Lahu (Red), merge into one row —
    // a rare imprecision, as the search DB carries no subgroup id.)
    const byName = new Map();
    for (const r of rows) {
      const cur = byName.get(r.language);
      if (!cur) byName.set(r.language, { language: r.language, lgid: r.lgid, n: r.n, _max: r.n });
      else { cur.n += r.n; if (r.n > cur._max) { cur._max = r.n; cur.lgid = r.lgid; } }
    }
    const ql = qe.toLowerCase();
    const list = [...byName.values()].sort((a, b) =>
      ((a.language.toLowerCase() === ql ? 0 : 1) - (b.language.toLowerCase() === ql ? 0 : 1)) || (b.n - a.n));
    languageTotal = list.length;
    languages = list.slice(0, lim < 0 ? list.length : Math.min(lim, 50));
  }

  return { etyma, etymaTotal, reflexes, reflexTotal, languages, languageTotal };
}

if (typeof window !== 'undefined') {
  window.stedtDbLoaded = false;
  window.stedtSearch = stedtSearch;
  window.stedtFormsByCategory = stedtFormsByCategory;
}
