// Legacy (/_legacy/) data-plane shim. The rootcanal front-end (Prototype/Scriptaculous/jQuery-1.8/
// TableKit/Opentip) is reused VERBATIM; this file is the only new JS. It replaces rootcanal's server
// AJAX endpoints with in-browser WASM-SQLite queries by intercepting at the XMLHttpRequest layer —
// so Prototype's Ajax.Request/Updater, jQuery's $.getJSON (autoSuggest), and Opentip's ajax all get
// synthesized responses without touching their code. The DB (legacy.sqlite3) is downloaded once and
// cached, mirroring src/search.js. Bundled IIFE and loaded FIRST in <head> so the XHR patch is in
// place before any rootcanal script runs.
import sqlite3InitModule from '@sqlite.org/sqlite-wasm';

const base = () => (typeof window !== 'undefined' && window.STEDT_BASE) || '';
const dbUrl = () => base() + '/legacy.sqlite3'
  + ((typeof window !== 'undefined' && window.STEDT_LEGACY_DB_VERSION) ? '?v=' + window.STEDT_LEGACY_DB_VERSION : '');

// ---------------------------------------------------------------------------- WASM DB load (cached)
let _dbp = null;
function getDb() { if (!_dbp) _dbp = loadDb(); return _dbp; }

async function loadDb() {
  const sqlite3 = await sqlite3InitModule({ locateFile: () => base() + '/assets/sqlite3.wasm' });
  const bytes = await fetchDbBytes(dbUrl());
  const p = sqlite3.wasm.allocFromTypedArray(bytes);
  const db = new sqlite3.oo1.DB();
  db.checkRc(sqlite3.capi.sqlite3_deserialize(
    db.pointer, 'main', p, bytes.length, bytes.length,
    sqlite3.capi.SQLITE_DESERIALIZE_FREEONCLOSE | sqlite3.capi.SQLITE_DESERIALIZE_RESIZEABLE));
  // MySQL RLIKE/REGEXP, case-insensitive. SQLite calls regexp(pattern, value). Cache compiled
  // patterns (same pattern for every row of a query → one compile per query).
  const rxCache = new Map();
  db.createFunction('regexp', (_ctx, pat, s) => {
    if (s == null) return 0;
    let re = rxCache.get(pat);
    if (re === undefined) { try { re = new RegExp(pat, 'i'); } catch (e) { re = null; } rxCache.set(pat, re); }
    return re && re.test(String(s)) ? 1 : 0;
  });
  if (typeof window !== 'undefined') window.stedtLegacyDbLoaded = true;
  return db;
}

// SYNC(db-fetch) ↔ web/src/search.js fetchDbBytes — same shape, separate cache key.
async function fetchDbBytes(url) {
  // Never cache a non-OK body: a transient 404/500 stored under the versioned URL would brick
  // the legacy search until the next data version (cache hits are never revalidated).
  const get = async () => {
    const res = await fetch(url);
    if (!res.ok) throw new Error('legacy DB fetch failed: HTTP ' + res.status);
    return res.arrayBuffer();
  };
  try {
    const cache = await caches.open('stedt-legacy-db');           // own cache key, separate from the main site
    const hit = await cache.match(url);
    if (hit) return new Uint8Array(await hit.arrayBuffer());
    const buf = await get();
    for (const k of await cache.keys()) await cache.delete(k);     // evict older DB versions
    await cache.put(url, new Response(buf));
    return new Uint8Array(buf);
  } catch (e) {
    return new Uint8Array(await get());                            // caches unavailable (e.g. file://)
  }
}

// rows as arrays of strings (TableKit reads data[i] as a positional array; DBI returns strings,
// and several transforms compare to '0' / read neighbors, so stringify non-null values).
function rows(db, sql, params) {
  const out = [];
  db.exec({ sql, bind: params || [], rowMode: 'array', resultRows: out });
  return out.map((r) => r.map((v) => (v == null ? null : String(v))));
}

// ---------------------------------------------------------------------- rootcanal WHERE translation
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');      // regex-escape a literal
// split a field value the way Table.pm query_where does: commas → OR, '&' → AND (ignoring \-escapes
// is fine for our inputs). Returns an array (OR) of arrays (AND) of term strings.
function terms(v) {
  return v.split(',').map((s) => s.trim()).filter(Boolean)
    .map((g) => g.split('&').map((s) => s.trim()).filter(Boolean));
}
const hasLetter = (s) => /\p{Letter}/u.test(s);
const isInt = (s) => /^\d+$/.test(s);

// OR/AND a per-term SQL fragment builder into one boolean clause, collecting bind params.
function clause(val, mk, bind) {
  const ors = terms(val).map((andTerms) => {
    const ands = andTerms.map((t) => mk(t, bind)).filter(Boolean);
    return ands.length > 1 ? '(' + ands.join(' AND ') + ')' : ands[0];
  }).filter(Boolean);
  return ors.length ? (ors.length > 1 ? '(' + ors.join(' OR ') + ')' : ors[0]) : '';
}

// where_word via FTS5 (proven identical to MySQL word-boundary RLIKE on this data); '*'-prefixed = raw.
function ftsExpr(val) {
  const ors = terms(val).map((andTerms) =>
    andTerms.map((t) => t.startsWith('*') ? '"' + t.slice(1).replace(/"/g, '') + '"'
                                          : '"' + t.replace(/"/g, '') + '"').join(' '));
  return ors.join(' OR ');
}

// ------------------------------------------------------------------------------- result column sets
const ETYMA_FIELDS = ['etyma.tag', 'num_recs', 'chapters.chaptertitle', 'etyma.chapter', 'etyma.sequence',
  'etyma.protoform', 'etyma.protogloss', 'etyma.grpid', 'languagegroups.plg', 'languagegroups.grpno',
  'etyma.notes', 'num_notes', 'num_comparanda', 'etyma.status', 'etyma.public', 'users.username'];
const ETYMA_SELECT = `SELECT e.tag, e.num_recs, ch.chaptertitle, e.chapter, e.sequence, e.protoform,
  e.protogloss, e.grpid, g.plg, g.grpno, e.notes, e.num_notes, e.num_comparanda, e.status, e.public, ''
  FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid LEFT JOIN chapters ch ON ch.semkey=e.chapter`;

// guest (privs=2) lexicon columns. user_an ("your analysis") / other_an ("others' analyses") are
// empty for us — we kept only the canonical uid=8 tagging — but are emitted (after analysis) so the
// column layout + the offset-based transforms match the original guest view exactly.
const LEX_FIELDS = ['lexicon.rn', 'analysis', 'user_an', 'other_an', 'lexicon.reflex', 'lexicon.gloss',
  'lexicon.gfn', 'languagenames.lgid', 'languagenames.language', 'languagegroups.grpid',
  'languagegroups.grpno', 'languagegroups.grp', 'citation', 'languagenames.srcabbr', 'lexicon.srcid',
  'lexicon.semkey', 'chapters.chaptertitle', 'num_notes'];
const LEX_SELECT = `SELECT l.rn, l.analysis, '' AS user_an, '' AS other_an, l.reflex, l.gloss, l.gfn,
  ln.lgid, ln.language, g.grpid, g.grpno, g.grp, sb.citation, ln.srcabbr, l.srcid, l.semkey,
  ch.chaptertitle, l.num_notes
  FROM lexicon l LEFT JOIN languagenames ln ON ln.lgid=l.lgid
  LEFT JOIN languagegroups g ON g.grpid=ln.grpid
  LEFT JOIN srcbib sb ON sb.srcabbr=ln.srcabbr
  LEFT JOIN chapters ch ON ch.semkey=l.semkey`;
const LEX_ORDER = ` ORDER BY g.grp0,g.grp1,g.grp2,g.grp3,g.grp4, ln.lgsort, l.reflex, ln.srcabbr, l.srcid`;
const ETYMA_ORDER = ` ORDER BY e.chapter, e.sequence`;
// rootcanal's get_query returns just the first item (LIMIT 1) for a pane with no search criteria
// (e.g. the etyma pane on a language-only search); a real search caps at 10000.
const LIM = (hasWhere) => ` LIMIT ${hasWhere ? 10000 : 1}`;

// --------------------------------------------------------------------------------- search handlers
function searchEtyma(db, p) {
  const where = [], bind = [];
  const s = p.get('s') || '', f = p.get('f') || '', tag = p.get('etyma.tag') || '';
  if (tag && isInt(tag)) { where.push('e.tag=?'); bind.push(tag); }
  if (s && (hasLetter(s) || /\d/.test(s)))                                    // protogloss = where_word
    { const c = clause(s, (t, b) => { b.push('\\b' + esc(t) + '\\b'); return 'e.protogloss REGEXP ?'; }, bind); if (c) where.push(c); }
  if (f && hasLetter(f))                                                      // protoform = where_rlike (raw)
    { const c = clause(f, (t, b) => { b.push(t.replace(/^\*/, '')); return 'e.protoform REGEXP ?'; }, bind); if (c) where.push(c); }
  else if (f && isInt(f)) { where.push('e.tag=?'); bind.push(f); }
  const sql = ETYMA_SELECT + (where.length ? ' WHERE ' + where.join(' AND ') : '') + ETYMA_ORDER + LIM(where.length);
  return { table: 'etyma', fields: ETYMA_FIELDS, data: rows(db, sql, bind) };
}

function searchLexicon(db, p) {
  const where = [], bind = [];
  const s = p.get('s') || '', f = p.get('f') || '', lg = p.get('lg') || '',
        lggrp = p.get('lggrp') || '', lgcode = p.get('lgcode') || '', analysis = p.get('analysis') || '';
  if (analysis && isInt(analysis)) { where.push('l.rn IN (SELECT rn FROM lx_et_hash WHERE tag=?)'); bind.push(analysis); }
  if (s && (hasLetter(s) || /\d/.test(s)))                                    // gloss = where_word → FTS
    { where.push('l.rn IN (SELECT rowid FROM lexicon_fts WHERE lexicon_fts MATCH ?)'); bind.push('gloss:(' + ftsExpr(s) + ')'); }
  if (f && isInt(f)) { where.push('l.rn IN (SELECT rn FROM lx_et_hash WHERE tag=?)'); bind.push(f); }
  else if (f && hasLetter(f))                                                 // reflex = where_rlike (raw)
    { const c = clause(f, (t, b) => { b.push(t.replace(/^\*/, '')); return 'l.reflex REGEXP ?'; }, bind); if (c) where.push(c); }
  if (lg && hasLetter(lg)) {                                                  // language: '='→exact, else word-start
    const inner = clause(lg, (t, b) => {
      if (t.startsWith('=')) { b.push(t.slice(1)); return 'language=?'; }
      b.push('\\b' + esc(t.replace(/^\*/, ''))); return 'language REGEXP ?';
    }, bind);
    if (inner) where.push('ln.lgid IN (SELECT lgid FROM languagenames WHERE ' + inner + ')');
  }
  if (/^(X|\d+)(\.\d+)*$/.test(lggrp)) {                                      // group: grpno + subgroups (unless strict)
    if (p.get('strict_grp')) { where.push('ln.grpid IN (SELECT grpid FROM languagegroups WHERE grpno=?)'); bind.push(lggrp); }
    else { where.push('ln.grpid IN (SELECT grpid FROM languagegroups WHERE grpno=? OR grpno LIKE ?)'); bind.push(lggrp, lggrp + '.%'); }
  }
  if (lgcode && isInt(lgcode)) { where.push('ln.lgcode=?'); bind.push(lgcode); }
  const sql = LEX_SELECT + (where.length ? ' WHERE ' + where.join(' AND ') : '') + LEX_ORDER + LIM(where.length);
  return { table: 'lexicon', fields: LEX_FIELDS, data: rows(db, sql, bind) };
}

// autosuggest/lgs: distinct languages whose name has a word starting with q → [{s, v:"="+s}]
function autosuggestLgs(db, q) {
  if (!q) return [];
  const r = rows(db, `SELECT DISTINCT language FROM languagenames
    WHERE language REGEXP ? AND coalesce(language,'')!='' ORDER BY language LIMIT 50`, ['\\b' + esc(q)]);
  return r.map(([lang]) => ({ s: lang, v: '=' + lang }));
}

// search/elink popup (tt/et_info.tt): mesoroots + allofams for the hovered tag(s). (Minimal faithful
// markup; refined alongside the etymon page.)
function elink(db, tags) {
  let html = '';
  for (const tag of tags) {
    if (!isInt(tag)) continue;
    const er = rows(db, `SELECT e.tag, g.plg, e.protoform, e.protogloss, e.chapter, e.sequence
      FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid WHERE e.tag=?`, [tag]);
    if (!er.length) continue;
    const [t, plg, pf, pg, chap, seq] = er[0];
    html += `<div class="et_info"><b>${plg || ''} *${pf || ''}</b> ${pg || ''} (#${t})`;
    const allo = rows(db, `SELECT e.tag, e.sequence, g.plg, e.protoform, e.protogloss
      FROM etyma e LEFT JOIN languagegroups g ON g.grpid=e.grpid
      WHERE e.chapter=? AND CAST(e.sequence AS INTEGER)=CAST(? AS INTEGER) AND e.sequence!='0' AND e.sequence!='0.0'
      ORDER BY e.sequence`, [chap, seq]);
    if (allo.length > 1) {
      html += '<ul>' + allo.map(([at, , aplg, apf, apg]) =>
        // base() is already the legacy base (/stedt/_legacy) on these pages — adding another
        // /_legacy segment 404'd every allofam link in the etymon-info popup
        `<li><a href="${base()}/etymon/${at}">#${at} ${aplg || ''} *${apf || ''} ${apg || ''}</a></li>`).join('') + '</ul>';
    }
    html += '</div>';
  }
  return html || '<div class="et_info">(no info)</div>';
}

// ------------------------------------------------------------------------------- endpoint dispatch
// Returns a Promise<{ctype, body}> or null if the path isn't a legacy endpoint.
function dispatch(path, params) {
  if (/(^|\/)search\/ajax$/.test(path)) {
    const tbl = params.get('tbl');
    return getDb().then((db) => json(tbl === 'etyma' ? searchEtyma(db, params) : searchLexicon(db, params)));
  }
  if (/(^|\/)search\/etyma$/.test(path)) return getDb().then((db) => json(searchEtyma(db, params)));
  if (/(^|\/)autosuggest\/lgs$/.test(path)) return getDb().then((db) => json(autosuggestLgs(db, params.get('q') || '')));
  if (/(^|\/)search\/elink$/.test(path)) return getDb().then((db) => html(elink(db, params.getAll('t'))));
  if (/(^|\/)notes\/notes_for_rn$/.test(path)) return getDb().then((db) => {
    const r = rows(db, 'SELECT html FROM lexnotes WHERE rn=?', [params.get('rn') || '']);
    const s = r.length && r[0][0] ? r[0][0] : '';
    // rebase render_note's root-relative xref links into the legacy subtree
    return html(s.replace(/href="\/etymon\//g, 'href="' + base() + '/etymon/'));
  });
  return null;
}
const json = (o) => ({ ctype: 'application/json', body: JSON.stringify(o) });
const html = (s) => ({ ctype: 'text/html; charset=utf-8', body: s });

// ------------------------------------------------------------------------------ XMLHttpRequest shim
// On legacy pages every XHR targets one of the endpoints above; non-matching URLs delegate to a real
// XHR (defensive). We replace window.XMLHttpRequest with a wrapper so we can set readyState/status
// (read-only on a native XHR) for the synthetic path.
(function installXHR() {
  if (typeof window === 'undefined' || window.__stedtLegacyXHR) return;
  const RealXHR = window.XMLHttpRequest;
  const isEndpoint = (u) => /(^|\/)(search\/ajax|search\/etyma|search\/elink|autosuggest\/lgs|notes\/notes_for_rn)(\?|$)/.test(u || '');

  function ShimXHR() {
    this._real = new RealXHR();
    this._intercept = false; this._url = ''; this._method = 'GET';
    this.readyState = 0; this.status = 0; this.statusText = '';
    this.responseText = ''; this.response = ''; this.responseXML = null;
    this.onreadystatechange = null; this.onload = null; this.onerror = null;
    this._listeners = {};
  }
  ShimXHR.prototype.open = function (method, url, async) {
    this._method = method; this._url = url; this._intercept = isEndpoint(url);
    if (!this._intercept) return this._real.open.apply(this._real, arguments);
    this.readyState = 1;
  };
  ShimXHR.prototype.setRequestHeader = function () {
    if (!this._intercept) return this._real.setRequestHeader.apply(this._real, arguments);
  };
  ShimXHR.prototype.getResponseHeader = function (h) {
    if (!this._intercept) return this._real.getResponseHeader.apply(this._real, arguments);
    return /content-type/i.test(h) ? this._ctype : null;
  };
  ShimXHR.prototype.getAllResponseHeaders = function () {
    if (!this._intercept) return this._real.getAllResponseHeaders.apply(this._real, arguments);
    return 'Content-Type: ' + (this._ctype || '') + '\r\n';
  };
  ShimXHR.prototype.addEventListener = function (type, fn) {
    if (!this._intercept) return this._real.addEventListener.apply(this._real, arguments);
    (this._listeners[type] = this._listeners[type] || []).push(fn);
  };
  ShimXHR.prototype.removeEventListener = function (type, fn) {
    if (!this._intercept) return this._real.removeEventListener.apply(this._real, arguments);
    const a = this._listeners[type]; if (a) { const i = a.indexOf(fn); if (i >= 0) a.splice(i, 1); }
  };
  ShimXHR.prototype.abort = function () { if (!this._intercept) return this._real.abort.apply(this._real, arguments); };

  ShimXHR.prototype._fire = function (type) {
    const ev = { type, target: this, currentTarget: this };
    if (type === 'readystatechange' && this.onreadystatechange) this.onreadystatechange(ev);
    if (type === 'load' && this.onload) this.onload(ev);
    if (type === 'error' && this.onerror) this.onerror(ev);
    (this._listeners[type] || []).slice().forEach((fn) => fn.call(this, ev));
  };

  ShimXHR.prototype.send = function (body) {
    const self = this;
    if (!this._intercept) {
      // delegate to a real XHR, mirroring its state back onto this wrapper
      const r = this._real;
      r.onreadystatechange = function () {
        self.readyState = r.readyState; self.status = r.status; self.statusText = r.statusText;
        try { self.responseText = r.responseText; } catch (e) {}
        try { self.responseXML = r.responseXML; } catch (e) {}
        self.response = r.response; self._fire('readystatechange');
        if (r.readyState === 4) self._fire(r.status >= 200 && r.status < 300 ? 'load' : 'error');
      };
      return r.send.apply(r, arguments);
    }
    // synthetic: parse params from query string + (form-encoded) body, run, respond async
    const qIdx = this._url.indexOf('?');
    const params = new URLSearchParams(qIdx >= 0 ? this._url.slice(qIdx + 1) : '');
    if (typeof body === 'string' && body) new URLSearchParams(body).forEach((v, k) => params.append(k, v));
    const path = (qIdx >= 0 ? this._url.slice(0, qIdx) : this._url);
    let pr;
    try { pr = dispatch(path, params); } catch (e) { pr = Promise.reject(e); }
    if (!pr) pr = Promise.resolve(html(''));
    Promise.resolve(pr).then((res) => {
      self._ctype = res.ctype; self.responseText = res.body; self.response = res.body;
      self.status = 200; self.statusText = 'OK'; self.readyState = 4;
      self._fire('readystatechange'); self._fire('load');
    }).catch((err) => {
      self._ctype = 'text/plain'; self.responseText = String(err && err.message || err);
      self.status = 500; self.statusText = 'Error'; self.readyState = 4;
      self._fire('readystatechange'); self._fire('error');
    });
  };

  window.XMLHttpRequest = ShimXHR;
  window.__stedtLegacyXHR = true;
})();

// Expose for the gnis bootstrap + tests.
if (typeof window !== 'undefined') {
  window.stedtLegacy = { getDb, searchEtyma, searchLexicon, autosuggestLgs };
}
