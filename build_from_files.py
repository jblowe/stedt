#!/usr/bin/env python3
"""Compile the flat files in data/ -> stedt.sqlite (the canonical build going forward).

Inverse of export_files.py. Produces the same schema serve.py reads:
reconstructs lx_et_hash from each reflex's 'analysis' column and the notes table
from etymon/thesaurus/bibliography/reflex-note sources.
"""
import sqlite3, os, csv, glob, yaml, sys, re

ROOT = "/home/luke/local/stedt/data"
OUT = sys.argv[1] if len(sys.argv) > 1 else "/home/luke/local/stedt/stedt.sqlite"
csv.field_size_limit(10**7)

# Same schema as the dump-based build, so serve.py is unchanged.
TABLES = {
 'etyma': ['chapter','sequence','tag','grpid','protoform','protogloss','xrefs','notes','possallo',
           'allofams','status','public','handle','prefix','initial','medial','rhyme','tone','suffix',
           'initcover','rhymecover','exemplary','semkey'],
 'lexicon': ['status','reflex','originalreflex','gloss','originalgloss','gfn','srcid','rn','semcat',
             'lgid','semkey','src_set_rn'],
 'lx_et_hash': ['rn','tag','ind','tag_str'],
 'languagenames': ['lgsort','srcabbr','language','lgabbr','notes','silcode','lgcode','lgid','grpid'],
 'languagegroups': ['grpno','groupabbr','grp','plg','genetic','grpid'],
 'chapters': ['semkey','chaptertitle','semcat','id'],
 'srcbib': ['srcabbr','citation','author','year','imprint','title','location','notes'],
 'notes': ['rn','tag','id','notetype','spec','ord','noteid','xmlnote'],
 'mesoroots': ['tag','grpid','form','gloss','id','variant'],
}
PK = {'etyma':'tag','lexicon':'rn','languagenames':'lgid','languagegroups':'grpid',
      'chapters':'id','notes':'noteid','mesoroots':'id'}
INT = {'rn','tag','lgid','grpid','noteid','id','ind','ord','src_set_rn','genetic','lgcode','public'}
def coldef(cols, pk):
    return ', '.join((f"{x} INTEGER" if x in INT else x) + (" PRIMARY KEY" if x == pk else "") for x in cols)
def loadyaml(p): return yaml.safe_load(open(p, encoding='utf-8')) or []

def main():
    if os.path.exists(OUT): os.remove(OUT)
    db = sqlite3.connect(OUT); c = db.cursor()
    c.execute("PRAGMA journal_mode=OFF"); c.execute("PRAGMA synchronous=OFF")
    for t, cols in TABLES.items():
        c.execute(f"CREATE TABLE {t} ({coldef(cols, PK.get(t))})")
    def insert(t, rowdicts):
        cols = TABLES[t]
        c.executemany(f"INSERT INTO {t} VALUES ({','.join('?'*len(cols))})",
                      [[d.get(k) for k in cols] for d in rowdicts])

    noteid = [0]
    notes = []
    def add_note(spec, key, lst):
        for n in (lst or []):
            noteid[0] += 1
            notes.append({'rn': key if spec == 'L' else 0, 'tag': key if spec == 'E' else 0,
                          'id': key if spec in ('C', 'S') else '', 'notetype': n.get('type', 'T'),
                          'spec': spec, 'ord': 0, 'noteid': noteid[0], 'xmlnote': n.get('text', '')})

    # ---- reference ----
    groups = loadyaml(f"{ROOT}/reference/languagegroups.yaml")
    insert('languagegroups', [{'grpno': g.get('grpno'), 'groupabbr': g.get('abbr'), 'grp': g.get('name'),
        'plg': g.get('proto_language'), 'genetic': int(g.get('genetic', True)), 'grpid': g['grpid']} for g in groups])
    langs = loadyaml(f"{ROOT}/reference/languages.yaml")
    insert('languagenames', [{'lgsort': l.get('sort'), 'srcabbr': l.get('source'), 'language': l.get('name'),
        'lgabbr': l.get('abbr'), 'notes': l.get('notes'), 'silcode': l.get('iso'), 'lgcode': l.get('lgcode'),
        'lgid': l['lgid'], 'grpid': l.get('grpid')} for l in langs])
    thes = loadyaml(f"{ROOT}/reference/thesaurus.yaml")
    chap = []
    for i, t in enumerate(thes, 1):
        chap.append({'semkey': t['semkey'], 'chaptertitle': t.get('title'), 'semcat': t.get('semcat'), 'id': i})
        add_note('C', t['semkey'], t.get('notes'))
    insert('chapters', chap)
    bib = loadyaml(f"{ROOT}/reference/bibliography.yaml")
    for b in bib: add_note('S', b['srcabbr'], b.get('annotations'))
    insert('srcbib', [{k: b.get(k) for k in TABLES['srcbib']} for b in bib])
    for ln in loadyaml(f"{ROOT}/reference/reflex-notes.yaml"):
        add_note('L', ln['rn'], [ln])

    # ---- etyma ----
    ety, meso = [], []
    mid = 0
    for p in glob.glob(f"{ROOT}/etyma/*.yaml"):
        d = loadyaml(p)
        ph = d.get('phonology', {})
        ety.append({'chapter': d.get('semkey'), 'sequence': d.get('sequence'), 'tag': d['tag'],
            'grpid': d.get('grpid'), 'protoform': d.get('protoform'), 'protogloss': d.get('gloss'),
            'xrefs': d.get('xrefs'), 'notes': d.get('references'), 'possallo': d.get('possallo'),
            'allofams': d.get('allofams'), 'status': d.get('status'),
            'public': 1 if d.get('public') else 0,
            'handle': ph.get('handle'), 'prefix': ph.get('prefix'), 'initial': ph.get('initial'),
            'medial': ph.get('medial'), 'rhyme': ph.get('rhyme'), 'tone': ph.get('tone'),
            'suffix': ph.get('suffix'), 'initcover': ph.get('initcover'), 'rhymecover': ph.get('rhymecover'),
            'exemplary': 'x' if d.get('exemplary') else '', 'semkey': d.get('semkey')})
        for m in d.get('mesoroots', []):
            mid += 1
            meso.append({'tag': d['tag'], 'grpid': m.get('grpid'), 'form': m.get('form'),
                         'gloss': m.get('gloss'), 'id': mid, 'variant': m.get('variant')})
        add_note('E', d['tag'], d.get('notes'))
    insert('etyma', ety); insert('mesoroots', meso)
    print(f"  etyma {len(ety)}  mesoroots {len(meso)}")

    # ---- wordlists -> lexicon + lx_et_hash (from analysis) ----
    lex, links = [], []
    nref = 0
    for p in glob.glob(f"{ROOT}/wordlists/*.tsv"):
        with open(p, encoding='utf-8', newline='') as f:
            for row in csv.DictReader(f, delimiter='\t'):
                rn = int(row['rn']); nref += 1
                lex.append({'status': row.get('status'), 'reflex': row.get('reflex'),
                    'originalreflex': row.get('originalreflex'), 'gloss': row.get('gloss'),
                    'originalgloss': row.get('originalgloss'), 'gfn': row.get('gfn'),
                    'srcid': row.get('srcid'), 'rn': rn, 'semcat': None,
                    'lgid': int(row['lgid']) if row.get('lgid') else None, 'semkey': row.get('semkey'),
                    'src_set_rn': int(row['src_set_rn']) if row.get('src_set_rn') else 0})
                an = row.get('analysis') or ''
                if an:
                    for ind, tok in enumerate(an.split(',')):
                        m = re.match(r'\d+', tok)   # tag = leading digits ('4?', '1pl+two' -> 4, 1)
                        links.append({'rn': rn, 'tag': int(m.group()) if m else 0,
                                      'ind': ind, 'tag_str': tok})
        if len(lex) > 200000:
            insert('lexicon', lex); insert('lx_et_hash', links); lex, links = [], []
    insert('lexicon', lex); insert('lx_et_hash', links)
    insert('notes', notes)
    db.commit()
    print(f"  lexicon {nref}  notes {len(notes)}")

    print("  indexes + FTS…")
    for s in [
        "CREATE INDEX ix_lex_lgid ON lexicon(lgid)", "CREATE INDEX ix_lex_semkey ON lexicon(semkey)",
        "CREATE INDEX ix_h_tag ON lx_et_hash(tag)", "CREATE INDEX ix_h_rn ON lx_et_hash(rn)",
        "CREATE INDEX ix_ln_grpid ON languagenames(grpid)", "CREATE INDEX ix_ln_src ON languagenames(srcabbr)",
        "CREATE INDEX ix_ety_semkey ON etyma(semkey)", "CREATE INDEX ix_ety_grpid ON etyma(grpid)",
        "CREATE INDEX ix_notes_tag ON notes(tag, spec)", "CREATE INDEX ix_notes_rn ON notes(rn, spec)",
        "CREATE INDEX ix_meso_tag ON mesoroots(tag, grpid)", "CREATE UNIQUE INDEX ix_src ON srcbib(srcabbr)",
        "CREATE INDEX ix_chap_semkey ON chapters(semkey)",
    ]: c.execute(s)
    c.execute("""CREATE VIRTUAL TABLE lexicon_fts USING fts5(
        form, gloss, language, rn UNINDEXED, tokenize='unicode61 remove_diacritics 2')""")
    c.execute("""INSERT INTO lexicon_fts(form,gloss,language,rn)
        SELECT l.reflex, l.gloss, ln.language, l.rn FROM lexicon l LEFT JOIN languagenames ln ON ln.lgid=l.lgid""")
    db.commit(); c.execute("VACUUM"); db.commit(); db.close()
    print(f"\nDB size: {os.path.getsize(OUT)/1e6:.1f} MB  -> {OUT}")

if __name__ == "__main__":
    main()
