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
// SYNC(db-fetch) ↔ web/src/legacy-shim.js fetchDbBytes — same shape, separate cache key.
async function fetchDbBytes(url) {
  // Never cache a non-OK body: a transient 404/500 stored under the versioned URL would brick
  // search until the next data version, because cache hits are never revalidated.
  // Streams the body so the page can show progress on the first-visit download
  // (a stedt-db-progress event per chunk; search-page.js renders it in the status line).
  const get = async () => {
    const res = await fetch(url);
    if (!res.ok) throw new Error('search DB fetch failed: HTTP ' + res.status);
    const total = +res.headers.get('Content-Length') || 0;
    if (!res.body || !total) return res.arrayBuffer();
    const reader = res.body.getReader(), parts = [];
    let loaded = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      parts.push(value);
      loaded += value.length;
      try { dispatchEvent(new CustomEvent('stedt-db-progress', { detail: { loaded, total } })); } catch (e) { /* non-window context */ }
    }
    const buf = new Uint8Array(loaded);
    let o = 0;
    for (const p of parts) { buf.set(p, o); o += p.length; }
    return buf.buffer;
  };
  try {
    const cache = await caches.open('stedt-search-db');
    const hit = await cache.match(url);
    if (hit) return new Uint8Array(await hit.arrayBuffer());
    const buf = await get();
    for (const k of await cache.keys()) await cache.delete(k);   // evict older DB versions
    await cache.put(url, new Response(buf));
    return new Uint8Array(buf);
  } catch (e) {
    return new Uint8Array(await get());                          // caches unavailable (e.g. file://)
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
const RFX_COLS = `ln.language AS language, ln.lgsort AS lgsort, l.reflex AS form, l.gloss AS gloss, l.gfn AS gfn, l.rn AS rn, l.lgid AS lgid,
         ln.srcabbr AS srcabbr, sb.citation AS citation, l.srcid AS srcid, l.semkey AS semkey, c.chaptertitle AS cat,
         g.grpno AS grpno, g.grp AS subgroup, nt.note AS note,
         json_group_array(json_object('tag', e.tag, 'pf', e.protoform, 'pg', e.protogloss, 'ind', h.ind))
           FILTER (WHERE e.tag IS NOT NULL) AS etyma`;
const RFX_JOINS = `
  FROM lexicon l JOIN languagenames ln ON ln.lgid = l.lgid
  LEFT JOIN languagegroups g ON g.grpid = ln.grpid
  LEFT JOIN srcbib sb ON sb.srcabbr = ln.srcabbr
  LEFT JOIN lxnote nt ON nt.rn = l.rn
  LEFT JOIN lx_et_hash h ON h.rn = l.rn AND h.tag > 0
  LEFT JOIN etyma e ON e.tag = h.tag AND coalesce(upper(e.status), '') != 'DELETE'
  LEFT JOIN chapters c ON c.semkey = l.semkey`;
const REFLEX_SQL = `
  SELECT ${RFX_COLS}${RFX_JOINS}
  WHERE l.rn IN (SELECT rowid FROM lexicon_fts WHERE lexicon_fts MATCH ? LIMIT ?)
    AND ln.language NOT LIKE '*%'
  GROUP BY l.rn LIMIT ?`;

const ETYMA_SQL = `
  SELECT e.tag AS tag, g.plg AS plg, e.protoform AS protoform, e.protogloss AS protogloss, e.semkey AS semkey, e.nreflex AS nreflex, e.exemplary AS exemplary, e.public AS public
  FROM etyma e LEFT JOIN languagegroups g ON g.grpid = e.grpid
  WHERE coalesce(upper(e.status), '') != 'DELETE'
    AND (e.protogloss LIKE ? OR e.protoform LIKE ?
         OR replace(replace(replace(e.protoform, '-', ''), '|', ''), '◦', '') LIKE ?)
  ORDER BY CASE WHEN upper(e.protogloss) LIKE upper(?) || '%' THEN 0 ELSE 1 END, e.protogloss
  LIMIT ?`;

const ETYMA_ALL_SQL = `
  SELECT e.tag AS tag, g.plg AS plg, e.protoform AS protoform, e.protogloss AS protogloss, e.semkey AS semkey, e.nreflex AS nreflex, e.exemplary AS exemplary, e.public AS public
  FROM etyma e LEFT JOIN languagegroups g ON g.grpid = e.grpid
  WHERE coalesce(upper(e.status), '') != 'DELETE' ORDER BY e.tag LIMIT ?`;

// Every reflex (lexicon row) carries its own gloss-level semkey — independent of any etymon.
// The thesaurus browse drills category -> etymon, so the ~310k reflexes tagged to no etymon
// are otherwise unreachable by meaning. This lists the attested forms filed directly under a
// semantic node, lazily (on expand), reusing the already-loaded search DB.
const FORMS_BY_CAT_SQL = (n) => `
  SELECT l.rn AS rn, l.reflex AS reflex, l.gloss AS gloss, l.gfn AS gfn, l.lgid AS lgid,
         ln.language AS language, ln.lgsort AS lgsort, ln.srcabbr AS srcabbr, sb.citation AS citation, l.srcid AS srcid, nt.note AS note,
         json_group_array(json_object('tag', e.tag, 'pf', e.protoform, 'pg', e.protogloss, 'ind', h.ind))
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
  // re-sort with the shared collation key: the SQL ORDER BY is binary in WASM (no custom
  // collations registered there), which would order these unlike the server-rendered lists
  rows.sort((a, b) => {
    // SYNC(reflex-order): curated lgsort first, display name as fallback (see shapeSortReflexes)
    const la = sortkey(a.lgsort || a.language), lb = sortkey(b.lgsort || b.language);
    if (la !== lb) return la < lb ? -1 : 1;
    const fa = sortkey(a.reflex), fb = sortkey(b.reflex);
    return fa < fb ? -1 : fa > fb ? 1 : 0;
  });
  return rows;
}

// AND the whitespace-separated tokens (FTS5 treats a space between terms as AND), each wrapped as
// a quoted phrase so it can match in ANY column (form/gloss/language). So "hit Lotha" finds rows
// where 'hit' (gloss) AND 'Lotha' (language) both occur — the combined query the single box used
// to fail silently (it matched the whole input as one adjacent phrase → always zero).
// Two invariants, both load-bearing:
//  - every quoted term must be a SINGLE FTS token: the index is detail=column (no position
//    lists), where FTS5 rejects multi-token phrases — and unicode61 splits word-internal
//    punctuation, so a raw quoted 'b-riŋ' / "k'a" (the normal shape of STEDT forms) used to
//    throw and take the whole search down. Replacing every separator with a space first makes
//    that impossible; adjacency was never expressible at detail=column, so nothing is lost.
//  - commas are OR groups ('frog, snail' = either gloss), the original site's documented idiom;
//    tokens within a group still AND. FTS5's AND binds tighter than OR, so groups need parens.
const ftsTok = (s) => s.replace(/[^\p{L}\p{N}\p{M}]+/gu, ' ').split(/\s+/).filter(Boolean);
const ftsQ = (s) => {
  const groups = s.split(/[,，]/)
    .map((g) => ftsTok(g).map((t) => '"' + t + '"').join(' '))
    .filter(Boolean);
  if (!groups.length) return '""';   // separator-only query; matches nothing, throws nothing
  return groups.length === 1 ? groups[0] : groups.map((g) => '(' + g + ')').join(' OR ');
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
  SELECT ln.language AS language, ln.lgid AS lgid, ln.grpid AS grpid, count(l.rn) AS n
  FROM languagenames ln JOIN lexicon l ON l.lgid = ln.lgid
  WHERE ln.language LIKE ? AND ln.language NOT LIKE '*%'
  GROUP BY ln.lgid`;

// FTS5's unicode61 tokenizer doesn't insert boundaries between Han characters, so a CJK substring
// is only found when it stands alone as a token — silently undercounting in this Chinese-heavy
// corpus. Detect CJK and route those queries through a substring LIKE over the stored lexicon text
// (mirroring the original site's RLIKE form search) instead of FTS MATCH.
const hasCJK = (s) => /[㐀-鿿豈-﫿]|[\ud840-\ud87f][\udc00-\udfff]/.test(s || '');
const likeToks = (s) => s.replace(/["()*:^%_]/g, ' ').split(/\s+/).filter(Boolean);
// comma = OR group, like ftsQ: '头, 蛇' is head-OR-snake, not an empty AND intersection
const likeGroups = (s) => s.split(/[,，]/).map(likeToks).filter((g) => g.length);
const _likeWhere = (groups) => groups
  .map((g) => '(' + g.map(() => '(reflex LIKE ? OR gloss LIKE ?)').join(' AND ') + ')')
  .join(' OR ');
const reflexLikeSql = (groups) => `
  SELECT ${RFX_COLS}${RFX_JOINS}
  WHERE l.rn IN (SELECT l2.rn FROM lexicon l2 JOIN languagenames n2 ON n2.lgid = l2.lgid
                 WHERE (${_likeWhere(groups)}) AND n2.language NOT LIKE '*%' LIMIT ?)
  GROUP BY l.rn LIMIT ?`;
const reflexLikeCountSql = (groups) => `
  SELECT count(*) AS n FROM lexicon l JOIN languagenames ln ON ln.lgid = l.lgid
  WHERE (${_likeWhere(groups)}) AND ln.language NOT LIKE '*%'`;

// ---- fielded syntax: a `field:value` term narrows one axis --------------------------------
// form:/gloss:/language: filter that FTS column; subgroup: restricts every result type to a
// Stammbaum subtree (matched by group name, plg abbreviation, or grpno — descendants included);
// pform:/pgloss: target a reconstruction's form/gloss (the p- prefix pairs them). Bare terms keep
// matching anywhere, all terms AND. (Documented by the expandable 'Search syntax' reference under
// the box — keep in step.)
const FIELDS = { form: 'form', reflex: 'form', gloss: 'gloss', language: 'language', lg: 'language',
                 subgroup: 'subgroup', group: 'subgroup', pform: 'proto', proto: 'proto', pgloss: 'pgloss',
                 source: 'source', src: 'source', pos: 'pos', tag: 'tag', etymon: 'tag' };
// tokenizer: a value with spaces takes quotes — subgroup:"Central Loloish", language:"Lotha Naga".
// (Unquoted, the space ends the value and the rest becomes bare terms.)
const _qtoks = (s) => s.match(/[A-Za-z]+:"[^"]*"|"[^"]*"|\S+/g) || [];
const _unq = (v) => (v.length > 1 && v.startsWith('"') && v.endsWith('"')) ? v.slice(1, -1) : v;
const _fieldOf = (w) => {
  const m = w.match(/^([A-Za-z]+):(.+)$/s);
  return m && FIELDS[m[1].toLowerCase()] ? [FIELDS[m[1].toLowerCase()], _unq(m[2])] : null;
};
const hasFields = (s) => _qtoks(s).some((w) => _fieldOf(w));
const parseFields = (s) => {
  const q = { cols: [], bare: [], subgroup: [], proto: [], pgloss: [], source: [], pos: [], tag: [] };
  for (const raw of _qtoks(s)) {
    const f = _fieldOf(raw);
    if (!f) { q.bare.push(_unq(raw)); continue; }
    if (f[0] === 'tag') { const n = parseInt(f[1], 10); if (n > 0) q.tag.push(n); }
    else if (f[0] !== 'form' && f[0] !== 'gloss' && f[0] !== 'language') q[f[0]].push(f[1]);
    // a multi-word column value becomes several column-filtered tokens, ANDed — adjacency isn't
    // expressible anyway (detail=column drops positions), and the tokens must co-occur in the column
    else for (const t of ftsTok(f[1])) q.cols.push(f[0] + ':"' + t + '"');
  }
  return q;
};

// subgroup: terms -> grpid list. Match a term against group name (substring), plg abbr, or
// grpno, then take the whole subtree by grpno prefix; several subgroup: terms intersect.
let _groupsCache = null;
const subgroupGrpids = (db, terms) => {
  if (!_groupsCache) _groupsCache = run(db, 'SELECT grpid, grpno, grp, plg FROM languagegroups');
  let ids = null;
  for (const t of terms) {
    const tl = t.toLowerCase();
    const pref = _groupsCache
      .filter((g) => (g.grp || '').toLowerCase().includes(tl) || (g.plg || '').toLowerCase() === tl || String(g.grpno) === t)
      .map((g) => String(g.grpno));
    const set = new Set();
    for (const g of _groupsCache) {
      const no = String(g.grpno || '');
      if (pref.some((p) => no === p || no.startsWith(p + '.'))) set.add(g.grpid);
    }
    ids = ids === null ? set : new Set([...ids].filter((x) => set.has(x)));
  }
  return ids ? [...ids] : [];
};

// source: terms -> srcabbr list (exact abbreviation, else citation substring; terms union —
// a record has one source, so intersecting two different source: terms could only be empty)
let _srcCache = null;
const sourceAbbrs = (db, terms) => {
  if (!_srcCache) _srcCache = run(db, 'SELECT srcabbr, citation FROM srcbib');
  const out = new Set();
  for (const t of terms) {
    const tl = t.toLowerCase();
    for (const r of _srcCache) {
      if ((r.srcabbr || '').toLowerCase() === tl || (r.citation || '').toLowerCase().includes(tl)) out.add(r.srcabbr);
    }
  }
  return [...out];
};

const _ph = (n) => Array(n).fill('?').join(',');
// reflex query/count for a fielded search: optional FTS MATCH, optional subgroup restriction.
// With no MATCH (subgroup:-only browse) it scans lexicon once — a few hundred ms in WASM.
// the non-FTS axes a fielded reflex query can carry (params in this order, after any MATCH)
const _axes = (x) => (x.ng ? ` AND ln.grpid IN (${_ph(x.ng)})` : '')
  + (x.ns ? ` AND ln.srcabbr IN (${_ph(x.ns)})` : '')
  + (x.np ? ` AND (${Array(x.np).fill('l.gfn LIKE ?').join(' OR ')})` : '')
  + (x.nt ? ` AND EXISTS (SELECT 1 FROM lx_et_hash h2 WHERE h2.rn = l.rn AND h2.tag IN (${_ph(x.nt)}))` : '');
const reflexFieldCountSql = (m, x) => `
  SELECT count(*) AS n
  FROM ${m ? 'lexicon_fts f JOIN lexicon l ON l.rn = f.rowid' : 'lexicon l'}
  JOIN languagenames ln ON ln.lgid = l.lgid
  WHERE ${m ? 'f.lexicon_fts MATCH ? AND ' : ''}ln.language NOT LIKE '*%'${_axes(x)}`;
const reflexFieldSql = (m, x) => `
  SELECT ${RFX_COLS}${RFX_JOINS}
  WHERE ${m ? 'l.rn IN (SELECT rowid FROM lexicon_fts WHERE lexicon_fts MATCH ? LIMIT ?) AND ' : ''}ln.language NOT LIKE '*%'${_axes(x)}
  GROUP BY l.rn LIMIT ?`;
const ETYMA_COLS = `e.tag AS tag, g.plg AS plg, e.protoform AS protoform, e.protogloss AS protogloss,
  e.semkey AS semkey, e.nreflex AS nreflex, e.exemplary AS exemplary, e.public AS public`;
const _NOHY = "replace(replace(replace(e.protoform, '-', ''), '|', ''), '◦', '')";
const etymaFieldSql = (where, count) => `
  SELECT ${count ? 'count(*) AS n' : ETYMA_COLS}
  FROM etyma e LEFT JOIN languagegroups g ON g.grpid = e.grpid
  WHERE coalesce(upper(e.status), '') != 'DELETE'${where ? ' AND ' + where : ''}
  ${count ? '' : 'ORDER BY e.protogloss LIMIT ?'}`;
const langFieldSql = (nLang, ng) => `
  SELECT ln.language AS language, ln.lgid AS lgid, count(l.rn) AS n
  FROM languagenames ln JOIN lexicon l ON l.lgid = ln.lgid
  WHERE ln.language NOT LIKE '*%'${' AND ln.language LIKE ?'.repeat(nLang)}${ng ? ` AND ln.grpid IN (${_ph(ng)})` : ''}
  GROUP BY ln.lgid`;

// SYNC(grpno-order) ↔ stedt/render/text.py natkey — natural order for a Stammbaum grpno: per
// '.'-segment, digit runs compare numerically and before alpha tokens ('6.1.10' after '6.1.2',
// 'X' after every number). Each segment becomes '0'+zero-padded digits (to 8 — beyond any
// Stammbaum numbering; natkey's ints are unbounded) or '1'+token, mirroring natkey's
// (kind, value) tuples; the '.' joiner collates below both prefixes, so a prefix grpno
// sorts before its extensions like Python's list comparison. Blanks (unjoined rows) sort last,
// as the server's blank-seeing caller (language.py) forces explicitly.
const gkey = (s) => (s == null || s === '' ? '2' : String(s).split('.')
  .map((x) => (/^\d+$/.test(x) ? '0' + x.padStart(8, '0') : '1' + x)).join('.'));

// SYNC(sortkey) ↔ stedt/render/text.py sortkey — case/accent-insensitive collation key (NFD,
// strip combining marks, casefold), so client-sorted lists order like the server-rendered ones
// (binary order exiles 'kûi' past all ASCII 'kuiy').
const sortkey = (s) => (s || '').normalize('NFD').replace(/\p{M}+/gu, '').toLowerCase();

// the fielded engine: every term ANDs; each result type runs only when the query carries
// criteria that apply to it (form:/language: say nothing about reconstructions, so a
// form:-only query shows no Reconstructions section instead of a misleading zero-match scan).
function fieldedSearch(db, qe, lim) {
  const q = parseFields(qe);
  const grpids = q.subgroup.length ? subgroupGrpids(db, q.subgroup) : null;
  const srcs = q.source.length ? sourceAbbrs(db, q.source) : null;
  const inner = lim < 0 ? -1 : lim + 40;
  const out = { etyma: [], etymaTotal: 0, reflexes: [], reflexTotal: 0, languages: [], languageTotal: 0 };
  if (q.subgroup.length && !(grpids && grpids.length)) return out;  // no such subgroup: honest empty
  if (q.source.length && !(srcs && srcs.length)) return out;        // no such source: honest empty

  // reflexes — bare + column terms feed one FTS MATCH; subgroup/source/pos/tag restrict in SQL
  const ftsTerms = [...q.bare.flatMap(ftsTok).map((t) => '"' + t + '"'), ...q.cols];
  const m = ftsTerms.length ? ftsTerms.join(' ') : null;
  const x = { ng: grpids ? grpids.length : 0, ns: srcs ? srcs.length : 0, np: q.pos.length, nt: q.tag.length };
  const ng = x.ng;
  const xp = [...(grpids || []), ...(srcs || []), ...q.pos.map((t) => t + '%'), ...q.tag];
  if (m || ng || x.ns || x.np || x.nt) {
    out.reflexTotal = run(db, reflexFieldCountSql(m, x), [...(m ? [m] : []), ...xp])[0].n;
    out.reflexes = run(db, reflexFieldSql(m, x), [...(m ? [m, inner] : []), ...xp, lim]);
    shapeSortReflexes(out.reflexes);
  }

  // reconstructions — proto:/pgloss:/bare terms AND a subgroup's own etyma (etyma.grpid)
  const ewhere = [], eparams = [];
  for (const t of q.proto) {
    ewhere.push(`(e.protoform LIKE ? OR ${_NOHY} LIKE ?)`);
    eparams.push('%' + t + '%', '%' + t.replace(/[-|◦\s]/g, '') + '%');
  }
  for (const t of q.pgloss) { ewhere.push('e.protogloss LIKE ?'); eparams.push('%' + t + '%'); }
  for (const t of q.bare) {
    ewhere.push(`(e.protogloss LIKE ? OR e.protoform LIKE ? OR ${_NOHY} LIKE ?)`);
    eparams.push('%' + t + '%', '%' + t + '%', '%' + t.replace(/[-|◦\s]/g, '') + '%');
  }
  if (ng) { ewhere.push(`e.grpid IN (${_ph(ng)})`); eparams.push(...grpids); }
  if (q.tag.length) { ewhere.push(`e.tag IN (${_ph(q.tag.length)})`); eparams.push(...q.tag); }
  if (q.proto.length || q.pgloss.length || q.bare.length || q.tag.length || (ng && !m)) {
    const w = ewhere.join(' AND ');
    out.etymaTotal = run(db, etymaFieldSql(w, true), eparams)[0].n;
    out.etyma = run(db, etymaFieldSql(w, false), [...eparams, lim]);
  }

  // languages — language: terms, or a pure subgroup browse (any other axis means the user is
  // after records, not a roster: 'tag:695 subgroup:Kiranti' shouldn't list 35 Kiranti lects)
  const lterms = q.cols.filter((c) => c.startsWith('language:')).map((c) => c.slice(10, -1));
  if (lterms.length || (ng && !m && !q.bare.length && !q.tag.length && !q.pos.length && !q.source.length)) {
    const rows = run(db, langFieldSql(lterms.length, ng), [...lterms.map((t) => '%' + t + '%'), ...(grpids || [])]);
    const byName = new Map();
    for (const r of rows) {
      const cur = byName.get(r.language);
      if (!cur) byName.set(r.language, { language: r.language, lgid: r.lgid, n: r.n, _max: r.n });
      else { cur.n += r.n; if (r.n > cur._max) { cur._max = r.n; cur.lgid = r.lgid; } }
    }
    const list = [...byName.values()].sort((a, b) => b.n - a.n);
    out.languageTotal = list.length;
    out.languages = list.slice(0, lim < 0 ? list.length : Math.min(lim, 50));
  }
  return out;
}

// parse the aggregated etyma JSON into deduped etyma/tag/pf/syn (shared with the category list),
// then order by subgroup (then language, form) so the page renders Stammbaum-grouped sections
function shapeSortReflexes(reflexes) {
  for (const r of reflexes) {
    shapeReflexEtyma(r);
    r._gk = gkey(r.grpno);   // precompute the sort keys once (invariant per row)
    // SYNC(reflex-order) ↔ stedt/render/etymon.py reflex sort: the curated languagenames.lgsort
    // orders listings (it files 'Burmese (Inscriptional)' with Written Burmese); display name is
    // only the fallback.
    r._lk = sortkey(r.lgsort || r.language);
    r._fk = sortkey(r.form);
  }
  reflexes.sort((a, b) => {
    const ga = a._gk, gb = b._gk;
    return ga < gb ? -1 : ga > gb ? 1
      : a._lk < b._lk ? -1 : a._lk > b._lk ? 1
      : a._fk < b._fk ? -1 : a._fk > b._fk ? 1 : 0;
  });
}

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

  // field:value terms switch to the fielded engine (one AND group; commas stay plain-search syntax)
  if (qe && query !== '*' && hasFields(qe)) return fieldedSearch(db, qe, lim);

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
      const groups = likeGroups(qe), p = [];
      for (const g of groups) for (const t of g) { const w = '%' + t + '%'; p.push(w, w); }
      reflexTotal = groups.length ? run(db, reflexLikeCountSql(groups), p)[0].n : 0;
      reflexes = groups.length ? run(db, reflexLikeSql(groups), [...p, inner, lim]) : [];
    } else {
      const m = ftsQ(qe);
      reflexTotal = run(db, REFLEX_COUNT_SQL, [m])[0].n;
      reflexes = run(db, REFLEX_SQL, [m, inner, lim]);
    }
    shapeSortReflexes(reflexes);
  }

  let languages = [], languageTotal = 0;
  if (qe && query !== '*' && qe.length >= 2) {
    const rows = run(db, LANG_SQL, ['%' + qe + '%']);
    // A canonical language page aggregates every source-variant lgid of a (name, subgroup), so its
    // form count is the SUM across variants — match that (was: the single largest variant's count,
    // which underreported multi-source lects ~2-4x). Link to the best-attested lgid = that lect's
    // canonical page. Keyed by (name, subgroup): same-name lects in different subgroups — Lahu (Red)
    // exists in two — are distinct lects with distinct pages, so they must not merge.
    const byName = new Map();
    for (const r of rows) {
      const key = r.language + ' ' + (r.grpid == null ? '' : r.grpid);
      const cur = byName.get(key);
      if (!cur) byName.set(key, { language: r.language, lgid: r.lgid, n: r.n, _max: r.n });
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
