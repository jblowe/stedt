// Pins the cross-view row contract (see project-attestation-links): one builder + one URL per
// entity, and identical reflex markup whether it's rendered in the search results or the thesaurus
// attestations. Pure, no deps — run with `npm test` (or `node web/test/rows.test.mjs`). rows.js
// reads no DOM at import and falls back to B='' off-browser, so it imports cleanly here.
import assert from 'node:assert/strict';
import {
  reflexRow, etymonRow, languageRow,
  reflexHref, languageHref, etymonHref, sourceHref,
} from '../src/rows.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ok  ' + name); };

// --- canonical URLs ---
test('reflexHref → language page anchored at the row', () => assert.equal(reflexHref(7, 42), '/language/7#rn42'));
test('languageHref → language page TOP (no anchor)', () => assert.equal(languageHref(7), '/language/7'));
test('etymonHref', () => assert.equal(etymonHref(9), '/etymon/9'));
test('sourceHref escapes the abbr', () => assert.equal(sourceHref('A&B'), '/source/A&amp;B'));

// --- reflex row: the contract that drifted before ---
const base = { lgid: 7, rn: 42, language: 'Lahu', gloss: 'ladder', gfn: 'n', srcabbr: 'JAM', citation: 'JAM 1988', etyma: [{ tag: 9, pf: 'gam' }] };
const fromSearch = reflexRow({ ...base, form: 'gâ' });      // search payload uses `form`
const fromCategory = reflexRow({ ...base, reflex: 'gâ' });  // category payload uses `reflex`

test('reflex row: search-shape and category-shape are byte-identical', () => assert.equal(fromSearch, fromCategory));

test('reflex row: exact markup (snapshot — change deliberately)', () => assert.equal(fromSearch,
  '<div class="rx-hit">' +
  '<a class="rx-go" href="/language/7#rn42" aria-label="Lahu: go to this entry"></a>' +
  '<a class="lang" href="/language/7">Lahu</a>' +
  '<span class="rx-mid"><span class="lat">gâ</span> <span class="g">ladder</span> <span class="pos">n</span>' +
  ' <span class="vias"><a class="via" href="/etymon/9">› *gam</a></span></span>' +
  '<span class="rx-src"><a href="/source/JAM">JAM 1988</a></span></div>'));

test('reflex row: whole row → #rn line via the overlay', () => assert.match(fromSearch, /<a class="rx-go" href="\/language\/7#rn42"/));
test('reflex row: language name → language TOP (no #rn)', () => assert.match(fromSearch, /<a class="lang" href="\/language\/7">Lahu<\/a>/));
test('reflex row: via chip → its etymon', () => assert.match(fromSearch, /<a class="via" href="\/etymon\/9">/));
test('reflex row: the form is NOT its own link (the overlay carries it)', () => assert.doesNotMatch(fromSearch, /<a[^>]*>gâ<\/a>/));

// a noted gloss stays an interactive .noted (not swallowed by the overlay)
test('reflex row: a note becomes a .noted gloss with its popover', () => {
  const noted = reflexRow({ ...base, form: 'gâ', note: 'see also' });
  assert.match(noted, /<span class="g noted" tabindex="0">ladder<span class="notepop" role="note">see also<\/span><\/span>/);
});

// tagged syllables carry their own etymon links instead of the form being plain
test('reflex row: a tagged syllable → its etymon', () => {
  const syl = reflexRow({ ...base, form: 'gâ', syn: { 0: 9 } });
  assert.match(syl, /<a class="syl" href="\/etymon\/9">/);
});

// --- etymon + language rows ---
test('etymon row → /etymon and a comma-formatted reflex count', () => {
  const e = etymonRow({ tag: 9, protoform: 'gam', protogloss: 'ladder', plg: 'PTB', nreflex: 1234 });
  assert.match(e, /class="ety-hit" href="\/etymon\/9"/);
  assert.match(e, / · 1,234 reflexes/);
});
test('language row → /language TOP', () => {
  const l = languageRow({ lgid: 7, language: 'Lahu', n: 12 });
  assert.match(l, /class="ety-hit" href="\/language\/7"/);
  assert.match(l, /12 attested forms/);
});

console.log(`\n${n} checks passed`);
