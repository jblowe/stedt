#!/usr/bin/env python3
"""Export the normalized stedt.sqlite -> flat files (the editable source of truth).

  data/etyma/<tag>.yaml        one cognate set (reconstruction + notes + mesoroots)
  data/wordlists/<srcabbr>.tsv reflexes grouped by source; morpheme tagging in 'analysis'
  data/reference/*.yaml        thesaurus, languages, languagegroups, bibliography

Lossless for curated content. Intentionally dropped (documented): modtime/uid (Git
provides history/authorship), refcount/seqlocked (derived/stale workflow flags), and
the legacy lexicon 'chapter'/'semcat' columns (both are superseded hand-entered
category codes, independent of and not derivable from semkey, retained only in the
archived dump). NB: etyma.chapter is NOT legacy — it is a real thesaurus placement
that often differs from semkey, so it IS preserved (emitted when it differs).
Morpheme 'ind' gaps are
re-densified by position (order preserved, absolute surface-position not); same-slot
tags are preserved via '|' within a slot; orphan lx_et_hash rows (rn absent from
lexicon) are preserved in reference/orphan-links.tsv.

Benign, intentional normalizations (semantically lossless, recoverable from the dump):
etyma.status case-canonicalized (delete -> DELETE); sentinel-zero integer fields
(languagenames.pi_page, srcbib.scope/infascicle, mesoroots.old_tag) emitted only when
nonzero (0 <-> absent/NULL); empty-text notes (no xmlnote) are skipped.
"""
import sqlite3, os, csv, yaml, re
from itertools import groupby

DB = "/home/luke/local/stedt/stedt.sqlite"
ROOT = "/home/luke/local/stedt/data"

class _D(yaml.SafeDumper): pass
_NEL = ('\x85', ' ', ' ')   # YAML folds these to spaces; double-quote forces \-escaping
def _str(d, s):
    if any(ch in s for ch in _NEL):
        return d.represent_scalar('tag:yaml.org,2002:str', s, style='"')
    return d.represent_scalar('tag:yaml.org,2002:str', s, style='|' if '\n' in s else None)
_D.add_representer(str, _str)
def dump(o): return yaml.dump(o, Dumper=_D, allow_unicode=True, sort_keys=False, width=100)

def safe(name): return re.sub(r'[^A-Za-z0-9._-]', '_', name) or '_blank'
def clean(s):   return '' if s is None else str(s)

def main():
    db = sqlite3.connect(DB); db.row_factory = sqlite3.Row; c = db.cursor()
    for d in ('etyma', 'wordlists', 'reference'):
        os.makedirs(os.path.join(ROOT, d), exist_ok=True)

    # ---- reference maps ----
    grp = {r['grpid']: r for r in c.execute("SELECT * FROM languagegroups")}
    lang = {r['lgid']: r for r in c.execute("SELECT * FROM languagenames")}

    # ---- collect notes by the entity they annotate ----
    enotes, cnotes, snotes, lnotes = {}, {}, {}, []   # E->tag, C->semkey, S->srcabbr, L->reflex
    for r in c.execute("SELECT spec,rn,tag,id,notetype,xmlnote,ord,noteid FROM notes ORDER BY ord, noteid"):
        if not clean(r['xmlnote']): continue
        rec = {'type': r['notetype'], 'text': r['xmlnote']}
        if r['spec'] == 'E':   enotes.setdefault(r['tag'], []).append(rec)
        elif r['spec'] == 'C': cnotes.setdefault(clean(r['id']), []).append(rec)
        elif r['spec'] == 'S': snotes.setdefault(clean(r['id']), []).append(rec)
        elif r['spec'] == 'L': lnotes.append({'rn': r['rn'], **rec})

    # ---- reference files ----
    thes = []
    for r in c.execute("SELECT * FROM chapters ORDER BY id"):
        if not r['semkey']: continue
        e = {'semkey': r['semkey'], 'title': r['chaptertitle']}
        for k, col in (('semcat', 'semcat'), ('old_chapter', 'old_chapter'), ('old_subchapter', 'old_subchapter')):
            if clean(r[col]): e[k] = r[col]
        if r['semkey'] in cnotes: e['notes'] = cnotes[r['semkey']]
        thes.append(e)
    open(f"{ROOT}/reference/thesaurus.yaml", "w").write(dump(thes))

    langs = []
    for r in c.execute("SELECT * FROM languagenames ORDER BY lgid"):
        d = {'lgid': r['lgid'], 'name': r['language'], 'abbr': r['lgabbr'],
             'grpid': r['grpid'], 'source': r['srcabbr']}
        for k, col in (('iso', 'silcode'), ('lgcode', 'lgcode'), ('sort', 'lgsort'),
                       ('srcofdata', 'srcofdata'), ('picode', 'picode'), ('pinotes', 'pinotes'), ('notes', 'notes')):
            if clean(r[col]): d[k] = r[col]
        if r['pi_page']: d['pi_page'] = r['pi_page']
        langs.append({k: v for k, v in d.items() if v not in ('', None)})
    open(f"{ROOT}/reference/languages.yaml", "w").write(dump(langs))

    groups = []
    for r in c.execute("SELECT * FROM languagegroups ORDER BY grpid"):
        e = {k: v for k, v in {
            'grpid': r['grpid'], 'grpno': r['grpno'], 'abbr': r['groupabbr'],
            'name': r['grp'], 'proto_language': r['plg'], 'genetic': bool(r['genetic']),
        }.items() if v not in ('', None)}
        e['lineage'] = [r['grp0'], r['grp1'], r['grp2'], r['grp3'], r['grp4']]   # parent grpid per level
        groups.append(e)
    open(f"{ROOT}/reference/languagegroups.yaml", "w").write(dump(groups))

    FULLBIB = ['srcabbr','citation','author','year','title','imprint','location','status','dataformat',
               'format','callnumber','scope','totalnum','refonly','citechk','pi','infascicle','haveit',
               'todo','proofer','inputter','dbprep','dbload','dbcheck','notes']
    bib = []
    for r in c.execute("SELECT * FROM srcbib ORDER BY srcabbr"):
        e = {}
        for k in FULLBIB:
            v = r[k]
            if k in ('scope', 'infascicle'):
                if v: e[k] = v
            elif clean(v):
                e[k] = v
        if r['srcabbr'] in snotes: e['annotations'] = snotes[r['srcabbr']]
        bib.append(e)
    open(f"{ROOT}/reference/bibliography.yaml", "w").write(dump(bib))

    lnotes.sort(key=lambda x: x['rn'])
    open(f"{ROOT}/reference/reflex-notes.yaml", "w").write(dump(lnotes))

    # HPTB (Handbook of Proto-Tibeto-Burman, Matisoff 2003) reconstructions + links to etyma
    hlinks = {}
    for r in c.execute("SELECT tag,hptbid,ord FROM et_hptb_hash ORDER BY hptbid, ord"):
        hlinks.setdefault(r['hptbid'], []).append(r['tag'])
    hptb = []
    for r in c.execute("SELECT * FROM hptb ORDER BY hptbid"):
        e = {k: v for k, v in {
            'hptbid': r['hptbid'], 'plg': r['plg'], 'protoform': r['protoform'], 'gloss': r['protogloss'],
            'pages': r['pages'], 'mainpage': r['mainpage'], 'init': r['init'], 'allofams': r['bare'],
            'semclass': r['semclass1'], 'semclass2': r['semclass2'], 'tags': r['tags'],
        }.items() if clean(v)}
        # etyma links = UNION of et_hptb_hash and the richer hptb.tags string (order-preserving)
        links = list(hlinks.get(r['hptbid'], []))
        for tok in clean(r['tags']).split(','):
            m = re.match(r'\d+', tok.strip())
            if m and int(m.group()) not in links:
                links.append(int(m.group()))
        if links: e['etyma'] = links
        hptb.append(e)
    open(f"{ROOT}/reference/hptb.yaml", "w").write(dump(hptb))

    oc = [{k: v for k, v in {'chapter': r['chapter'], 'heading': r['heading'], 'semcat': r['semcat'],
           'subcat': r['subcat'], 'cf': r['cf'], 'n': r['n']}.items() if clean(v)}
          for r in c.execute("SELECT * FROM otherchapters ORDER BY id")]
    open(f"{ROOT}/reference/otherchapters.yaml", "w").write(dump(oc))

    mc = [{k: v for k, v in {'chapter': r['chapter'], 'subchapter': r['subchapter'], 'semcat': r['semcat'],
           'heading': r['heading'], 'frqdb': r['frqdb'], 'frqsubcats': r['frqsubcats']}.items() if clean(v)}
          for r in c.execute("SELECT * FROM majorcats ORDER BY id")]
    open(f"{ROOT}/reference/majorcats.yaml", "w").write(dump(mc))

    pirows = [{'lgid': r['lgid'], 'page': r['page']} for r in c.execute("SELECT lgid,page FROM pi ORDER BY lgid, page")]
    open(f"{ROOT}/reference/pi.yaml", "w").write(dump(pirows))

    n_gw = 0
    with open(f"{ROOT}/reference/glosswords.tsv", "w", newline='') as f:
        w = csv.writer(f, delimiter='\t', lineterminator='\n')
        w.writerow(['word', 'rn', 'semcat', 'subcat', 'semkey'])
        for r in c.execute("SELECT word,rn,semcat,subcat,semkey FROM glosswords ORDER BY id"):
            w.writerow([clean(r['word']), clean(r['rn']), clean(r['semcat']), clean(r['subcat']), clean(r['semkey'])])
            n_gw += 1

    print(f"  reference: thesaurus({len(thes)}) languages({len(langs)}) groups({len(groups)}) "
          f"bib({len(bib)}) reflex-notes({len(lnotes)}) hptb({len(hptb)}) otherchapters({len(oc)}) "
          f"majorcats({len(mc)}) pi({len(pirows)}) glosswords({n_gw})")

    # ---- etyma ----
    meso = {}
    for r in c.execute("SELECT * FROM mesoroots ORDER BY tag, id"):
        gg = grp.get(r['grpid'])
        m = {'grpid': r['grpid'], 'group': (gg['grpno'] if gg else None),
             'form': r['form'], 'gloss': r['gloss']}
        if clean(r['variant']): m['variant'] = r['variant']
        if clean(r['old_note']): m['source'] = r['old_note']   # bibliographic provenance citation
        if r['old_tag']: m['old_tag'] = r['old_tag']
        meso.setdefault(r['tag'], []).append({k: v for k, v in m.items() if v not in ('', None)})
    PHON =['handle', 'prefix', 'initial', 'medial', 'rhyme', 'tone', 'suffix', 'initcover', 'rhymecover']
    n_ety = 0
    for r in c.execute("SELECT * FROM etyma ORDER BY tag"):
        g = grp.get(r['grpid'])
        d = {'tag': r['tag'],
             'grpid': r['grpid'],
             'proto_language': g['plg'] if g else None,
             'protoform': r['protoform'],
             'gloss': r['protogloss'],
             'semkey': r['semkey'],
             'sequence': float(r['sequence']) if r['sequence'] is not None else None,
             'status': {'DELETE': 'DELETE', 'KEEP': 'KEEP'}.get((r['status'] or '').upper(), r['status'] or ''),  # canonical-cased
             'public': bool(r['public'])}          # original publish flag (historically unreliable)
        if r['exemplary'] == 'x': d['exemplary'] = True
        for k in ('xrefs', 'allofams', 'possallo'):
            if clean(r[k]): d[k] = r[k]
        if clean(r['notes']): d['references'] = r['notes']
        if clean(r['chapter']) and r['chapter'] != (r['semkey'] or ''):
            d['chapter'] = r['chapter']   # etyma.chapter: real thesaurus placement distinct from semkey
        phon = {k: r[k] for k in PHON if clean(r[k])}
        if phon: d['phonology'] = phon
        if r['tag'] in meso: d['mesoroots'] = meso[r['tag']]
        if r['tag'] in enotes: d['notes'] = enotes[r['tag']]
        # keep status/public always (curation state), drop other empties
        d = {k: v for k, v in d.items() if v not in ('', None) or k in ('status', 'public')}
        open(f"{ROOT}/etyma/{r['tag']}.yaml", "w").write(dump(d))
        n_ety += 1
    print(f"  etyma: {n_ety} files")

    # ---- wordlists (reflexes grouped by source), with reconstructed analysis ----
    # analysis: morpheme slots separated by ',', same-ind tags joined by '|', deterministic order.
    analysis = {}
    hashrows = c.execute("SELECT rn, ind, tag_str FROM lx_et_hash ORDER BY rn, ind, tag_str").fetchall()
    for rn, grp_rows in groupby(hashrows, key=lambda r: r['rn']):
        slots = ['|'.join(clean(x['tag_str']) for x in srows)
                 for _, srows in groupby(grp_rows, key=lambda r: r['ind'])]
        analysis[rn] = ','.join(slots)
    # orphan lx_et_hash rows (rn absent from lexicon) preserved verbatim so the link count round-trips
    lex_rns = {row[0] for row in c.execute("SELECT rn FROM lexicon")}
    orphans = [[clean(r['rn']), clean(r['ind']), clean(r['tag_str'])]
               for r in c.execute("SELECT rn, ind, tag_str FROM lx_et_hash ORDER BY rn, ind")
               if r['rn'] not in lex_rns]
    with open(f"{ROOT}/reference/orphan-links.tsv", "w", newline='') as f:
        w = csv.writer(f, delimiter='\t', lineterminator='\n')
        w.writerow(['rn', 'ind', 'tag_str']); w.writerows(orphans)
    COLS = ['rn', 'lgid', 'language', 'reflex', 'originalreflex', 'gloss', 'originalgloss',
            'gfn', 'originalgfn', 'semkey', 'srcid', 'src_set_rn', 'maintainer', 'status', 'analysis']
    buckets = {}
    for r in c.execute("SELECT * FROM lexicon"):
        ln = lang.get(r['lgid'])
        src = ln['srcabbr'] if ln and clean(ln['srcabbr']) else '_orphan'
        row = [clean(r['rn']), clean(r['lgid']), (ln['language'] if ln else ''),
               clean(r['reflex']), clean(r['originalreflex']), clean(r['gloss']),
               clean(r['originalgloss']), clean(r['gfn']), clean(r['originalgfn']), clean(r['semkey']),
               clean(r['srcid']), clean(r['src_set_rn']), clean(r['maintainer']), clean(r['status']),
               clean(analysis.get(r['rn'], ''))]
        buckets.setdefault(src, []).append(row)
    seen_fn = {}
    for src in buckets:                       # guard: safe() filename must be injective
        fn = safe(src)
        if fn in seen_fn:
            raise ValueError(f"wordlist filename collision: {src!r} and {seen_fn[fn]!r} both -> {fn}.tsv")
        seen_fn[fn] = src
    for src, rows in buckets.items():
        rows.sort(key=lambda x: int(x[0]))
        with open(f"{ROOT}/wordlists/{safe(src)}.tsv", "w", newline='') as f:
            w = csv.writer(f, delimiter='\t', quoting=csv.QUOTE_MINIMAL, lineterminator='\n')
            w.writerow(COLS); w.writerows(rows)
    print(f"  wordlists: {len(buckets)} source files, {sum(len(v) for v in buckets.values())} reflexes")
    db.close()
    # size
    total = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(ROOT) for f in fs)
    print(f"\n  data/ total: {total/1e6:.1f} MB")

if __name__ == "__main__":
    main()
