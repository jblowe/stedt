#!/usr/bin/env python3
"""Compile the all-TSV flat files in data/ -> stedt.sqlite (the canonical build).

Inverse of stedt.dev.export_tsv. Produces the exact schema the renderer reads: reconstructs
lx_et_hash from each reflex's 'analysis' column, et_hptb_hash from hptb 'etyma_links', and
the notes table from the etymon_notes / chapter_notes / per-source notes+annotations files.
See data/FORMAT.md for the layout.

Args:  [OUT_SQLITE] [DATA_DIR]  (default to stedt.paths.DB / stedt.paths.DATA)
"""
import sqlite3, os, csv, glob, sys, re

from stedt.paths import DATA, DB

OUT = sys.argv[1] if len(sys.argv) > 1 else DB
ROOT = sys.argv[2] if len(sys.argv) > 2 else DATA
csv.field_size_limit(10**7)

TABLES = {
 'etyma': ['chapter','sequence','tag','grpid','protoform','protogloss','xrefs','notes','possallo',
           'allofams','status','public','handle','prefix','initial','medial','rhyme','tone','suffix',
           'initcover','rhymecover','exemplary','semkey'],
 'lexicon': ['status','reflex','originalreflex','gloss','originalgloss','gfn','originalgfn','srcid','rn',
             'semcat','lgid','semkey','src_set_rn','maintainer'],
 'lx_et_hash': ['rn','tag','ind','tag_str'],
 'languagenames': ['lgsort','srcabbr','language','lgabbr','notes','silcode','lgcode','lgid','grpid',
                   'srcofdata','picode','pinotes','pi_page'],
 'languagegroups': ['grpno','groupabbr','grp','plg','genetic','grpid','grp0','grp1','grp2','grp3','grp4'],
 'chapters': ['semkey','chaptertitle','semcat','old_chapter','old_subchapter','id'],
 'srcbib': ['srcabbr','citation','author','year','imprint','title','location','status','dataformat',
            'format','callnumber','scope','totalnum','refonly','citechk','pi','infascicle','haveit',
            'todo','proofer','inputter','dbprep','dbload','dbcheck','notes'],
 'notes': ['rn','tag','id','notetype','spec','ord','noteid','xmlnote'],
 'mesoroots': ['tag','grpid','form','gloss','id','variant','old_tag','old_note'],
 'hptb': ['hptbid','plg','protoform','protogloss','pages','mainpage','init','bare','semclass1','semclass2','tags'],
 'et_hptb_hash': ['tag','hptbid','ord'],
 'otherchapters': ['chapter','heading','semcat','subcat','cf','n','id'],
 'majorcats': ['chapter','subchapter','semcat','heading','frqdb','frqsubcats','id'],
 'glosswords': ['word','rn','semcat','subcat','semkey','id'],
 'pi': ['lgid','page'],
}
PK = {'etyma':'tag','lexicon':'rn','languagenames':'lgid','languagegroups':'grpid',
      'chapters':'id','notes':'noteid','mesoroots':'id'}
INT = {'rn','tag','lgid','grpid','noteid','id','ind','ord','src_set_rn','genetic','lgcode','public',
       'pi_page','grp0','grp1','grp2','grp3','grp4','scope','infascicle','hptbid','frqdb','frqsubcats',
       'n','page','old_tag'}
TEXT_OVERRIDE = {('notes', 'id')}  # notes.id is polymorphic (semkey for C, srcabbr for S) -> keep TEXT
def coldef(cols, pk, table=None):
    parts = []
    for x in cols:
        is_int = x in INT and (table, x) not in TEXT_OVERRIDE
        parts.append((f"{x} INTEGER" if is_int else x) + (" PRIMARY KEY" if x == pk else ""))
    return ', '.join(parts)

def rows(path):
    """Yield dict rows from a TSV, or nothing if the file is absent."""
    if not os.path.exists(path): return
    with open(path, encoding='utf-8', newline='') as f:
        yield from csv.DictReader(f, delimiter='\t')

def i(v):  return int(v) if v not in (None, '') else None
def s(v):  return None if v in (None, '') else v   # '' -> NULL (absent optional field)

def main():
    if os.path.exists(OUT): os.remove(OUT)
    db = sqlite3.connect(OUT); c = db.cursor()
    c.execute("PRAGMA journal_mode=OFF"); c.execute("PRAGMA synchronous=OFF")
    for t, cols in TABLES.items():
        c.execute(f"CREATE TABLE {t} ({coldef(cols, PK.get(t), t)})")
    def insert(t, rowdicts):
        cols = TABLES[t]
        c.executemany(f"INSERT INTO {t} VALUES ({','.join('?'*len(cols))})",
                      [[d.get(k) for k in cols] for d in rowdicts])

    noteid = [0]
    notes = []
    def add_note(spec, key, notetype, text):
        if not text: return
        noteid[0] += 1
        notes.append({'rn': key if spec == 'L' else 0, 'tag': key if spec == 'E' else 0,
                      'id': key if spec in ('C', 'S') else '', 'notetype': notetype or 'T',
                      'spec': spec, 'ord': 0, 'noteid': noteid[0], 'xmlnote': text})

    # ---- reference ----
    insert('languagegroups', [{'grpno': s(g['grpno']), 'groupabbr': s(g['abbr']), 'grp': s(g['name']),
        'plg': s(g['proto_language']), 'genetic': i(g['genetic']), 'grpid': i(g['grpid']),
        'grp0': i(g['grp0']), 'grp1': i(g['grp1']), 'grp2': i(g['grp2']), 'grp3': i(g['grp3']),
        'grp4': i(g['grp4'])} for g in rows(f"{ROOT}/languagegroups.tsv")])
    insert('languagenames', [{'lgsort': s(l['sort']), 'srcabbr': s(l['source']), 'language': s(l['name']),
        'lgabbr': s(l['abbr']), 'notes': s(l['notes']), 'silcode': s(l['iso']), 'lgcode': i(l['lgcode']),
        'lgid': i(l['lgid']), 'grpid': i(l['grpid']), 'srcofdata': s(l['srcofdata']), 'picode': s(l['picode']),
        'pinotes': s(l['pinotes']), 'pi_page': i(l['pi_page'])} for l in rows(f"{ROOT}/languages.tsv")])

    chap = []
    for n, t in enumerate(rows(f"{ROOT}/thesaurus.tsv"), 1):
        chap.append({'semkey': t['semkey'], 'chaptertitle': s(t['title']), 'semcat': s(t['semcat']),
                     'old_chapter': s(t['old_chapter']), 'old_subchapter': s(t['old_subchapter']), 'id': n})
    insert('chapters', chap)
    for cn in rows(f"{ROOT}/chapter_notes.tsv"): add_note('C', cn['semkey'], cn['type'], cn['text'])

    # hptb (+ et_hptb_hash from the resolved etyma_links column)
    hptb, ehh = [], []
    for h in rows(f"{ROOT}/hptb.tsv"):
        hptb.append({'hptbid': i(h['hptbid']), 'plg': s(h['plg']), 'protoform': s(h['protoform']),
            'protogloss': s(h['gloss']), 'pages': s(h['pages']), 'mainpage': s(h['mainpage']), 'init': s(h['init']),
            'bare': s(h['allofams']), 'semclass1': s(h['semclass']), 'semclass2': s(h['semclass2']), 'tags': s(h['tags'])})
        for o, tok in enumerate(t for t in (h['etyma_links'] or '').split(',') if t):
            ehh.append({'tag': int(tok), 'hptbid': i(h['hptbid']), 'ord': o})
    insert('hptb', hptb); insert('et_hptb_hash', ehh)

    def with_id(rs):  return [{**r, 'id': n} for n, r in enumerate(rs, 1)]
    insert('otherchapters', with_id([{k: s(r[k]) for k in ('chapter','heading','semcat','subcat','cf','n')}
                                     for r in rows(f"{ROOT}/otherchapters.tsv")]))
    insert('majorcats', with_id([{k: s(r[k]) for k in ('chapter','subchapter','semcat','heading','frqdb','frqsubcats')}
                                 for r in rows(f"{ROOT}/majorcats.tsv")]))
    insert('pi', [{'lgid': i(p['lgid']), 'page': i(p['page'])} for p in rows(f"{ROOT}/pi.tsv")])
    insert('glosswords', [{'word': g['word'], 'rn': i(g['rn']), 'semcat': g['semcat'],
                           'subcat': g['subcat'], 'semkey': g['semkey'], 'id': n}
                          for n, g in enumerate(rows(f"{ROOT}/glosswords.tsv"), 1)])

    # ---- etyma + children ----
    PHON = ['handle','prefix','initial','medial','rhyme','tone','suffix','initcover','rhymecover']
    ety = []
    for d in rows(f"{ROOT}/etyma.tsv"):
        ety.append({'chapter': d['chapter'] or d['semkey'] or '',
            'sequence': float(d['sequence']) if d['sequence'] else None,
            'tag': i(d['tag']), 'grpid': i(d['grpid']), 'protoform': s(d['protoform']), 'protogloss': s(d['gloss']),
            'xrefs': s(d['xrefs']), 'notes': s(d['references']), 'possallo': s(d['possallo']), 'allofams': s(d['allofams']),
            'status': d['status'], 'public': 1 if d['public'] == '1' else 0,
            'exemplary': 'x' if d['exemplary'] == 'x' else '', 'semkey': d['semkey'] or '',
            **{k: s(d[k]) for k in PHON}})
    insert('etyma', ety)
    meso = [{'tag': i(m['tag']), 'grpid': i(m['grpid']), 'form': s(m['form']), 'gloss': s(m['gloss']),
             'id': n, 'variant': s(m['variant']), 'old_tag': i(m['old_tag']), 'old_note': s(m['source'])}
            for n, m in enumerate(rows(f"{ROOT}/mesoroots.tsv"), 1)]
    insert('mesoroots', meso)
    for en in rows(f"{ROOT}/etymon_notes.tsv"): add_note('E', i(en['tag']), en['type'], en['text'])
    print(f"  etyma {len(ety)}  mesoroots {len(meso)}")

    # ---- per-source: srcbib + lexicon (+lx_et_hash) + reflex notes + annotations ----
    srcbib, lex, links = [], [], []
    nref = 0
    for srcdir in sorted(glob.glob(f"{ROOT}/sources/*")):
        for b in rows(f"{srcdir}/source.tsv"):
            srcbib.append({k: (i(b.get(k)) if k in ('scope', 'infascicle') else s(b.get(k)))
                           for k in TABLES['srcbib']})
        for b in rows(f"{srcdir}/source.tsv"):
            for a in rows(f"{srcdir}/annotations.tsv"): add_note('S', b['srcabbr'], a['type'], a['text'])
        for row in rows(f"{srcdir}/wordlist.tsv"):
            rn = int(row['rn']); nref += 1
            lex.append({'status': row['status'], 'reflex': row['reflex'],
                'originalreflex': row['originalreflex'], 'gloss': row['gloss'],
                'originalgloss': row['originalgloss'], 'gfn': row['gfn'], 'originalgfn': row['originalgfn'],
                'maintainer': row['maintainer'], 'srcid': row['srcid'], 'rn': rn, 'semcat': None,
                'lgid': i(row['lgid']), 'semkey': row['semkey'], 'src_set_rn': i(row['src_set_rn']) or 0})
            for ind, slot in enumerate((row['analysis'] or '').split(',') if row['analysis'] else []):
                for tok in slot.split('|'):
                    m = re.match(r'\d+', tok)
                    links.append({'rn': rn, 'tag': int(m.group()) if m else 0, 'ind': ind, 'tag_str': tok})
        for ln in rows(f"{srcdir}/notes.tsv"): add_note('L', int(ln['rn']), ln['type'], ln['text'])
    insert('srcbib', srcbib); insert('lexicon', lex); insert('lx_et_hash', links)

    # orphan rows (rn absent from any wordlist)
    for ln in rows(f"{ROOT}/orphan_reflex_notes.tsv"): add_note('L', int(ln['rn']), ln['type'], ln['text'])
    for row in rows(f"{ROOT}/orphan_links.tsv"):
        m = re.match(r'\d+', row['tag_str'] or '')
        links2 = {'rn': int(row['rn']), 'tag': int(m.group()) if m else 0,
                  'ind': i(row['ind']) or 0, 'tag_str': row['tag_str']}
        c.execute("INSERT INTO lx_et_hash VALUES (?,?,?,?)", [links2[k] for k in TABLES['lx_et_hash']])
    insert('notes', notes)
    db.commit()
    print(f"  lexicon {nref}  srcbib {len(srcbib)}  notes {len(notes)}")

    print("  indexes + FTS…")
    for stmt in [
        "CREATE INDEX ix_lex_lgid ON lexicon(lgid)", "CREATE INDEX ix_lex_semkey ON lexicon(semkey)",
        "CREATE INDEX ix_h_tag ON lx_et_hash(tag)", "CREATE INDEX ix_h_rn ON lx_et_hash(rn)",
        "CREATE INDEX ix_ln_grpid ON languagenames(grpid)", "CREATE INDEX ix_ln_src ON languagenames(srcabbr)",
        "CREATE INDEX ix_ety_semkey ON etyma(semkey)", "CREATE INDEX ix_ety_grpid ON etyma(grpid)",
        "CREATE INDEX ix_notes_tag ON notes(tag, spec)", "CREATE INDEX ix_notes_rn ON notes(rn, spec)",
        "CREATE INDEX ix_meso_tag ON mesoroots(tag, grpid)", "CREATE UNIQUE INDEX ix_src ON srcbib(srcabbr)",
        "CREATE INDEX ix_chap_semkey ON chapters(semkey)",
    ]: c.execute(stmt)
    c.execute("""CREATE VIRTUAL TABLE lexicon_fts USING fts5(
        form, gloss, language, rn UNINDEXED, tokenize='unicode61 remove_diacritics 2')""")
    c.execute("""INSERT INTO lexicon_fts(form,gloss,language,rn)
        SELECT l.reflex, l.gloss, ln.language, l.rn FROM lexicon l LEFT JOIN languagenames ln ON ln.lgid=l.lgid""")
    db.commit(); c.execute("VACUUM"); db.commit(); db.close()
    print(f"\nDB size: {os.path.getsize(OUT)/1e6:.1f} MB  -> {OUT}")

if __name__ == "__main__":
    main()
