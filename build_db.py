#!/usr/bin/env python3
"""Build stedt.sqlite from the FULL normalized MySQL dump (not the denorm CSVs).

One streaming pass over the 331MB dump; each target table's INSERT lines are
parsed and loaded with real relations preserved. Cognate links come from the
authoritative lx_et_hash table. FTS5 (diacritic-folded) is built over reflexes
joined to their language name.
"""
import sqlite3, os, time

BASE = "/home/luke/local/stedt/stedtdb_v1.0"
SQLDUMP = os.path.join(BASE, "STEDT_public_20160602.sql")
OUT = "/home/luke/local/stedt/stedt.sqlite"

# ---- columns (from the dump's CREATE TABLE statements) ----
TABLES = {
 'etyma': ['chapter','sequence','tag','grpid','protoform','protogloss','xrefs','notes',
           'possallo','allofams','status','handle','prefix','initial','medial','rhyme',
           'tone','suffix','initcover','rhymecover','exemplary','modtime','public','uid',
           'semkey','refcount','seqlocked'],
 'lexicon': ['status','reflex','originalreflex','gloss','originalgloss','gfn','originalgfn',
             'srcid','rn','chapter','semcat','modtime','lgid','semkey','maintainer','src_set_rn'],
 'lx_et_hash': ['uid','rn','tag','ind','tag_str'],
 'languagenames': ['lgsort','srcabbr','language','lgabbr','notes','srcofdata','pinotes','picode',
                   'lgcode','silcode','lgid','grpid','pi_page','modtime'],
 'languagegroups': ['grpno','groupabbr','grp','plg','genetic','grpid','grp0','grp1','grp2','grp3','grp4'],
 'chapters': ['semkey','chaptertitle','v','f','c','s1','s2','s3','semcat','old_chapter','old_subchapter','id'],
 'srcbib': ['srcabbr','citation','author','year','imprint','title','status','location','notes','dataformat',
            'format','haveit','todo','proofer','inputter','dbprep','dbload','dbcheck','callnumber','scope',
            'refonly','citechk','pi','totalnum','infascicle'],
 'notes': ['rn','tag','id','notetype','spec','ord','datetime','noteid','xmlnote','uid'],
 'mesoroots': ['tag','grpid','form','gloss','id','old_tag','old_note','variant','uid'],
 'glosswords': ['word','rn','semcat','subcat','id','modtime','semkey'],
 'majorcats': ['chapter','subchapter','semcat','heading','frqdb','frqsubcats','id'],
 'hptb': ['hptbid','plg','protoform','protogloss','mainpage','pages','tags','modtime','init','bare','semclass1','semclass2'],
}
PK = {'etyma':'tag','lexicon':'rn','languagenames':'lgid','languagegroups':'grpid',
      'chapters':'id','notes':'noteid','mesoroots':'id'}
INT_COLS = {'rn','tag','lgid','grpid','noteid','uid','id','ord','mseq','hptbid','src_set_rn',
            'public','refcount','seqlocked','ind','genetic','lgcode','pi_page','scope','infascicle',
            'frqdb','frqsubcats','v','f','c','s1','s2','s3','grp0','grp1','grp2','grp3','grp4','old_tag'}

ESC = {'n':'\n','t':'\t','r':'\r','0':'\0','\\':'\\',"'":"'",'"':'"','Z':'\x1a','b':'\b'}
def decode(x):
    out=[]; k=0; L=len(x)
    while k<L:
        c=x[k]
        if c=='\\' and k+1<L: out.append(ESC.get(x[k+1],x[k+1])); k+=2
        else: out.append(c); k+=1
    return ''.join(out)

def parse_values(s):
    """Parse `(...),(...),...;` -> list of rows. Fast path uses str.find for quotes."""
    rows=[]; i=0; n=len(s)
    while i<n and s[i] in ' \t\r\n': i+=1
    while i<n and s[i]=='(':
        i+=1; row=[]
        while True:
            while s[i]==' ': i+=1
            if s[i]=="'":
                j=i+1
                while True:
                    q=s.find("'", j)
                    b=q-1; cnt=0
                    while s[b]=='\\': cnt+=1; b-=1
                    if cnt%2==0: break
                    j=q+1
                raw=s[i+1:q]
                row.append(decode(raw) if '\\' in raw else raw)
                i=q+1
            else:
                j=i
                while s[i] not in ',)': i+=1
                tok=s[j:i].strip()
                row.append(None if tok.upper()=='NULL' else tok)
            while s[i]==' ': i+=1
            if s[i]==',': i+=1; continue
            if s[i]==')': i+=1; break
        rows.append(row)
        while i<n and s[i] in ' \t\r\n': i+=1
        if i<n and s[i]==',':
            i+=1
            while i<n and s[i] in ' \t\r\n': i+=1
        else: break
    return rows

def coldef(cols, pk):
    parts=[]
    for x in cols:
        d = f"{x} INTEGER" if x in INT_COLS else x
        if x==pk: d += " PRIMARY KEY"
        parts.append(d)
    return ', '.join(parts)

def main():
    t0=time.time()
    if os.path.exists(OUT): os.remove(OUT)
    db=sqlite3.connect(OUT); c=db.cursor()
    c.execute("PRAGMA journal_mode=OFF"); c.execute("PRAGMA synchronous=OFF")
    for t,cols in TABLES.items():
        c.execute(f"CREATE TABLE {t} ({coldef(cols, PK.get(t))})")
    ins = {t: f"INSERT INTO {t} VALUES ({','.join('?'*len(cols))})" for t,cols in TABLES.items()}
    counts = {t:0 for t in TABLES}

    with open(SQLDUMP, encoding='utf-8', errors='replace') as f:
        for line in f:
            if not line.startswith("INSERT INTO `"): continue
            end = line.index('`', 13); t = line[13:end]
            if t not in TABLES: continue
            vstart = line.index(' VALUES ', end) + 8
            rows = parse_values(line[vstart:])
            ncol = len(TABLES[t])
            rows = [r[:ncol] + [None]*(ncol-len(r)) for r in rows]
            c.executemany(ins[t], rows)
            counts[t] += len(rows)
    db.commit()
    for t in TABLES: print(f"  {t:16s} {counts[t]:>7,}")

    print("  building indexes + FTS…")
    for stmt in [
        "CREATE INDEX ix_lex_lgid ON lexicon(lgid)",
        "CREATE INDEX ix_lex_semkey ON lexicon(semkey)",
        "CREATE INDEX ix_lex_srcset ON lexicon(src_set_rn)",
        "CREATE INDEX ix_h_tag ON lx_et_hash(tag)",
        "CREATE INDEX ix_h_rn ON lx_et_hash(rn)",
        "CREATE INDEX ix_ln_grpid ON languagenames(grpid)",
        "CREATE INDEX ix_ln_srcabbr ON languagenames(srcabbr)",
        "CREATE INDEX ix_ety_semkey ON etyma(semkey)",
        "CREATE INDEX ix_ety_grpid ON etyma(grpid)",
        "CREATE INDEX ix_ety_public ON etyma(public)",
        "CREATE INDEX ix_notes_tag ON notes(tag, spec)",
        "CREATE INDEX ix_notes_rn ON notes(rn, spec)",
        "CREATE INDEX ix_notes_id ON notes(id, spec)",
        "CREATE INDEX ix_meso_tag ON mesoroots(tag, grpid)",
        "CREATE UNIQUE INDEX ix_src ON srcbib(srcabbr)",
        "CREATE INDEX ix_chap_semkey ON chapters(semkey)",
    ]:
        c.execute(stmt)
    c.execute("""CREATE VIRTUAL TABLE lexicon_fts USING fts5(
        form, gloss, language, rn UNINDEXED, tokenize='unicode61 remove_diacritics 2')""")
    c.execute("""INSERT INTO lexicon_fts(form,gloss,language,rn)
        SELECT l.reflex, l.gloss, ln.language, l.rn
        FROM lexicon l LEFT JOIN languagenames ln ON ln.lgid=l.lgid""")
    db.commit(); c.execute("VACUUM"); db.commit(); db.close()
    print(f"\nDB size: {os.path.getsize(OUT)/1e6:.1f} MB  ({time.time()-t0:.1f}s)  -> {OUT}")

if __name__=="__main__":
    main()
