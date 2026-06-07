#!/usr/bin/env python3
"""Export the normalized stedt.sqlite -> flat files (the editable source of truth).

  data/etyma/<tag>.yaml        one cognate set (reconstruction + notes + mesoroots)
  data/wordlists/<srcabbr>.tsv reflexes grouped by source; morpheme tagging in 'analysis'
  data/reference/*.yaml        thesaurus, languages, languagegroups, bibliography

Lossless for meaningful data. Intentionally dropped (documented): modtime/uid (Git
provides history/authorship), public/refcount/seqlocked (stale workflow flags),
legacy 'chapter'/'semcat' duplicates of semkey. 'ind' gaps are re-densified by
morpheme position (cognate membership unaffected).
"""
import sqlite3, os, csv, yaml, re

DB = "/home/luke/local/stedt/stedt.sqlite"
ROOT = "/home/luke/local/stedt/data"

class _D(yaml.SafeDumper): pass
def _str(d, s):
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
        elif r['spec'] == 'C': cnotes.setdefault(r['id'], []).append(rec)
        elif r['spec'] == 'S': snotes.setdefault(r['id'], []).append(rec)
        elif r['spec'] == 'L': lnotes.append({'rn': r['rn'], **rec})

    # ---- reference files ----
    thes = []
    for r in c.execute("SELECT semkey,chaptertitle,semcat FROM chapters ORDER BY id"):
        if not r['semkey']: continue
        e = {'semkey': r['semkey'], 'title': r['chaptertitle']}
        if clean(r['semcat']): e['semcat'] = r['semcat']
        if r['semkey'] in cnotes: e['notes'] = cnotes[r['semkey']]
        thes.append(e)
    open(f"{ROOT}/reference/thesaurus.yaml", "w").write(dump(thes))

    langs = []
    for r in c.execute("SELECT * FROM languagenames ORDER BY lgid"):
        d = {'lgid': r['lgid'], 'name': r['language'], 'abbr': r['lgabbr'],
             'grpid': r['grpid'], 'source': r['srcabbr']}
        for k, col in (('iso', 'silcode'), ('lgcode', 'lgcode'), ('sort', 'lgsort'), ('notes', 'notes')):
            if clean(r[col]): d[k] = r[col]
        langs.append({k: v for k, v in d.items() if v not in ('', None)})
    open(f"{ROOT}/reference/languages.yaml", "w").write(dump(langs))

    groups = []
    for r in c.execute("SELECT * FROM languagegroups ORDER BY grpid"):
        groups.append({k: v for k, v in {
            'grpid': r['grpid'], 'grpno': r['grpno'], 'abbr': r['groupabbr'],
            'name': r['grp'], 'proto_language': r['plg'], 'genetic': bool(r['genetic']),
        }.items() if v not in ('', None)})
    open(f"{ROOT}/reference/languagegroups.yaml", "w").write(dump(groups))

    bib = []
    for r in c.execute("SELECT * FROM srcbib ORDER BY srcabbr"):
        e = {k: v for k, v in {
            'srcabbr': r['srcabbr'], 'citation': r['citation'], 'author': r['author'],
            'year': r['year'], 'title': r['title'], 'imprint': r['imprint'],
            'location': r['location'], 'notes': r['notes'],
        }.items() if clean(v)}
        if r['srcabbr'] in snotes: e['annotations'] = snotes[r['srcabbr']]
        bib.append(e)
    open(f"{ROOT}/reference/bibliography.yaml", "w").write(dump(bib))

    lnotes.sort(key=lambda x: x['rn'])
    open(f"{ROOT}/reference/reflex-notes.yaml", "w").write(dump(lnotes))
    print(f"  reference: thesaurus({len(thes)}) languages({len(langs)}) groups({len(groups)}) "
          f"bib({len(bib)}) reflex-notes({len(lnotes)})")

    # ---- etyma ----
    meso = {}
    for r in c.execute("SELECT * FROM mesoroots ORDER BY tag, id"):
        gg = grp.get(r['grpid'])
        m = {'grpid': r['grpid'], 'group': (gg['grpno'] if gg else None),
             'form': r['form'], 'gloss': r['gloss']}
        if clean(r['variant']): m['variant'] = r['variant']
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
             'status': r['status'] or '',          # KEEP | DELETE | '' (blank) — always recorded
             'public': bool(r['public'])}          # original publish flag (historically unreliable)
        if r['exemplary'] == 'x': d['exemplary'] = True
        for k in ('xrefs', 'allofams', 'possallo'):
            if clean(r[k]): d[k] = r[k]
        if clean(r['notes']): d['references'] = r['notes']
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
    analysis = {row[0]: row[1] for row in c.execute(
        "SELECT rn, group_concat(tag_str, ',') FROM "
        "(SELECT rn, ind, tag_str FROM lx_et_hash ORDER BY rn, ind) GROUP BY rn")}
    COLS = ['rn', 'lgid', 'language', 'reflex', 'originalreflex', 'gloss', 'originalgloss',
            'gfn', 'semkey', 'srcid', 'src_set_rn', 'status', 'analysis']
    buckets = {}
    for r in c.execute("SELECT * FROM lexicon"):
        ln = lang.get(r['lgid'])
        src = ln['srcabbr'] if ln and clean(ln['srcabbr']) else '_orphan'
        row = [clean(r['rn']), clean(r['lgid']), (ln['language'] if ln else ''),
               clean(r['reflex']), clean(r['originalreflex']), clean(r['gloss']),
               clean(r['originalgloss']), clean(r['gfn']), clean(r['semkey']),
               clean(r['srcid']), clean(r['src_set_rn']), clean(r['status']),
               clean(analysis.get(r['rn'], ''))]
        buckets.setdefault(src, []).append(row)
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
