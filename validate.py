#!/usr/bin/env python3
"""Validate the STEDT all-TSV flat-file source in data/ for referential integrity.

Exit code 1 if any ERRORs (integrity violations that must block a merge);
WARNINGs (data-quality issues) are reported but do not fail. Run: python3 validate.py
"""
import csv, glob, os, re, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
csv.field_size_limit(10**7)
rel = lambda p: os.path.relpath(p, ROOT)
errors, warns = [], []
def err(m): errors.append(m)
def warn(m): warns.append(m)

def read_tsv(path, expect):
    """Yield rows (dicts) of a TSV, ERRORing on a missing file or unexpected header."""
    if not os.path.exists(path):
        err(f"{rel(path)}: missing"); return
    with open(path, encoding='utf-8', newline='') as f:
        rdr = csv.DictReader(f, delimiter='\t')
        if rdr.fieldnames != expect:
            err(f"{rel(path)}: unexpected columns {rdr.fieldnames}"); return
        yield from rdr

def keyset(path, expect, key):
    """Set of `key` values; ERROR on blank or duplicate keys."""
    s = set()
    for r in read_tsv(path, expect):
        v = r[key]
        if v == '':         err(f"{rel(path)}: blank {key}")
        elif v in s:        err(f"{rel(path)}: duplicate {key} {v!r}")
        else:               s.add(v)
    return s

COLS = {
 'etyma': ['tag','grpid','protoform','gloss','semkey','chapter','sequence','status','public',
           'exemplary','xrefs','allofams','possallo','references','handle','prefix','initial',
           'medial','rhyme','tone','suffix','initcover','rhymecover'],
 'mesoroots': ['tag','grpid','form','gloss','variant','old_tag','source'],
 'etymon_notes': ['tag','type','text'],
 'languages': ['lgid','name','abbr','grpid','source','iso','lgcode','sort','srcofdata','picode',
               'pinotes','pi_page','notes'],
 'languagegroups': ['grpid','grpno','abbr','name','proto_language','genetic','grp0','grp1','grp2','grp3','grp4'],
 'thesaurus': ['semkey','title','semcat','old_chapter','old_subchapter'],
 'chapter_notes': ['semkey','type','text'],
 'hptb': ['hptbid','plg','protoform','gloss','pages','mainpage','init','allofams','semclass','semclass2','tags','etyma_links'],
 'majorcats': ['chapter','subchapter','semcat','heading','frqdb','frqsubcats'],
 'otherchapters': ['chapter','heading','semcat','subcat','cf','n'],
 'pi': ['lgid','page'],
 'glosswords': ['word','rn','semcat','subcat','semkey'],
 'orphan_links': ['rn','ind','tag_str'],
 'orphan_reflex_notes': ['rn','type','text'],
 'source': ['srcabbr','citation','author','year','imprint','title','location','status','dataformat',
            'format','callnumber','scope','totalnum','refonly','citechk','pi','infascicle','haveit',
            'todo','proofer','inputter','dbprep','dbload','dbcheck','notes'],
 'wordlist': ['rn','lgid','language','reflex','originalreflex','gloss','originalgloss','gfn',
              'originalgfn','semkey','srcid','src_set_rn','maintainer','status','analysis'],
 'notes': ['rn','type','text'],
 'annotations': ['type','text'],
}
def isint(v): return bool(v) and (v[1:] if v[0] in '+-' else v).isdigit()

# ---- reference tables ----
grpids  = keyset(f"{ROOT}/languagegroups.tsv", COLS['languagegroups'], 'grpid')
semkeys = keyset(f"{ROOT}/thesaurus.tsv", COLS['thesaurus'], 'semkey')
langrows = list(read_tsv(f"{ROOT}/languages.tsv", COLS['languages']))
lgids, lgname = set(), {}
for l in langrows:
    if l['lgid'] == '' or not isint(l['lgid']): err(f"languages.tsv: bad lgid {l['lgid']!r}"); continue
    if int(l['lgid']) in lgids: err(f"languages.tsv: duplicate lgid {l['lgid']}")
    lgids.add(int(l['lgid'])); lgname[int(l['lgid'])] = l['name']
for g in read_tsv(f"{ROOT}/languagegroups.tsv", COLS['languagegroups']):
    for k in ('grp0','grp1','grp2','grp3','grp4'):
        if not isint(g[k]): err(f"languagegroups.tsv grpid {g['grpid']}: non-integer {k} {g[k]!r}")
    if g['genetic'] not in ('0','1'): err(f"languagegroups.tsv grpid {g['grpid']}: genetic must be 0/1")
# structural-only tables (header check; build dereferences these)
for fn in ('majorcats', 'otherchapters', 'pi'):
    list(read_tsv(f"{ROOT}/{fn}.tsv", COLS[fn]))
for cn in read_tsv(f"{ROOT}/chapter_notes.tsv", COLS['chapter_notes']):
    if cn['semkey'] not in semkeys: warn(f"chapter_notes.tsv: semkey {cn['semkey']!r} not in thesaurus")

# ---- etyma + children ----
etyma_tags = set()
VALID_STATUS = {'KEEP', 'DELETE', ''}
for d in read_tsv(f"{ROOT}/etyma.tsv", COLS['etyma']):
    if not isint(d['tag']): err(f"etyma.tsv: non-integer tag {d['tag']!r}"); continue
    tag = int(d['tag'])
    if tag in etyma_tags: err(f"etyma.tsv: duplicate tag {tag}")
    etyma_tags.add(tag)
    if d['status'].upper() not in VALID_STATUS: warn(f"etyma.tsv #{tag}: unknown status {d['status']!r}")
    if d['grpid'] and d['grpid'] not in grpids:  warn(f"etyma.tsv #{tag}: grpid {d['grpid']} not in languagegroups")
    if d['semkey'] and d['semkey'] not in semkeys: err(f"etyma.tsv #{tag}: semkey {d['semkey']!r} not in thesaurus")
    if d['chapter'] and d['chapter'] not in semkeys: warn(f"etyma.tsv #{tag}: chapter {d['chapter']!r} not in thesaurus")
    if d['sequence'] and not re.match(r'^-?\d+(\.\d+)?$', d['sequence']):
        err(f"etyma.tsv #{tag}: non-numeric sequence {d['sequence']!r}")
    if d['public'] not in ('0','1'): err(f"etyma.tsv #{tag}: public must be 0/1")
print(f"  etyma: {len(etyma_tags)} tags")

for m in read_tsv(f"{ROOT}/mesoroots.tsv", COLS['mesoroots']):
    if not isint(m['tag']) or int(m['tag']) not in etyma_tags:
        err(f"mesoroots.tsv: row references etymon #{m['tag']} with no etyma.tsv row")
    if m['grpid'] and m['grpid'] not in grpids:
        warn(f"mesoroots.tsv tag {m['tag']}: grpid {m['grpid']} not in languagegroups")
for n in read_tsv(f"{ROOT}/etymon_notes.tsv", COLS['etymon_notes']):
    if not isint(n['tag']) or int(n['tag']) not in etyma_tags:
        err(f"etymon_notes.tsv: note references etymon #{n['tag']} with no etyma.tsv row")

# ---- per-source: source.tsv + wordlist.tsv + notes.tsv + annotations.tsv ----
def toks(analysis):
    for slot in (analysis or '').split(','):
        yield from slot.split('|')
seen_rn, n_ref, n_src = {}, 0, 0
srcabbrs, missing_ref, bad_token = set(), {}, {}
for srcdir in sorted(glob.glob(f"{ROOT}/sources/*")):
    n_src += 1
    sp = f"{srcdir}/source.tsv"
    if os.path.exists(sp):
        rows = list(read_tsv(sp, COLS['source']))
        if len(rows) != 1: err(f"{rel(sp)}: expected exactly 1 row, got {len(rows)}")
        for s in rows:
            if s['srcabbr'] == '': err(f"{rel(sp)}: blank srcabbr")
            elif s['srcabbr'] in srcabbrs: err(f"{rel(sp)}: duplicate srcabbr {s['srcabbr']}")
            else: srcabbrs.add(s['srcabbr'])
    wlp = f"{srcdir}/wordlist.tsv"
    for row in (read_tsv(wlp, COLS['wordlist']) if os.path.exists(wlp) else []):
        n_ref += 1
        rn = row['rn']
        if not isint(rn): err(f"{rel(srcdir)}/wordlist.tsv: non-numeric rn {rn!r}"); continue
        rn = int(rn)
        if rn in seen_rn: err(f"{rel(srcdir)}/wordlist.tsv: duplicate rn {rn} (also in {seen_rn[rn]})")
        else: seen_rn[rn] = rel(srcdir)
        if row['lgid']:
            if not isint(row['lgid']):       err(f"{rel(srcdir)} rn {rn}: non-numeric lgid {row['lgid']!r}")
            elif int(row['lgid']) not in lgids: warn(f"{rel(srcdir)} rn {rn}: lgid {row['lgid']} not in languages")
            else:
                exp = lgname.get(int(row['lgid']))
                if row['language'] and exp and row['language'] != exp:
                    warn(f"{rel(srcdir)} rn {rn}: language col {row['language']!r} != lgid ({exp!r}); 'language' is derived")
        if row['src_set_rn'] and not isint(row['src_set_rn']):
            err(f"{rel(srcdir)} rn {rn}: non-numeric src_set_rn {row['src_set_rn']!r}")
        if row['semkey'] and row['semkey'] not in semkeys:
            warn(f"{rel(srcdir)} rn {rn}: semkey {row['semkey']!r} not in thesaurus")
        for tok in toks(row['analysis']):
            m = re.match(r'\d+', tok)
            if m:
                if int(m.group()) not in etyma_tags: missing_ref.setdefault(int(m.group()), f"{rel(srcdir)} rn {rn}")
            elif re.search(r'\d', tok) and not re.match(r'^[A-Za-z?]', tok):
                bad_token.setdefault(tok, f"{rel(srcdir)} rn {rn}")
    for ln in read_tsv(f"{srcdir}/notes.tsv", COLS['notes']) if os.path.exists(f"{srcdir}/notes.tsv") else []:
        if not isint(ln['rn']): err(f"{rel(srcdir)}/notes.tsv: non-numeric rn {ln['rn']!r}")
    if os.path.exists(f"{srcdir}/annotations.tsv"):
        list(read_tsv(f"{srcdir}/annotations.tsv", COLS['annotations']))
print(f"  sources: {n_src} folders ({len(srcabbrs)} with source.tsv), {n_ref} reflexes")

for t, where in sorted(missing_ref.items()):
    err(f"analysis references etymon #{t} with no etyma.tsv row (e.g. {where})")
for tok, where in sorted(bad_token.items()):
    warn(f"analysis token {tok!r} has digits but no leading digit/marker — possible mis-encoded cognate ({where})")

# ---- glosswords: gloss->rn index; many rns predate the digitized wordlists (aggregate warning) ----
g_miss = 0
for r in read_tsv(f"{ROOT}/glosswords.tsv", COLS['glosswords']):
    if r['rn'] and not isint(r['rn']): err(f"glosswords.tsv: non-numeric rn {r['rn']!r}")
    elif r['rn'] and int(r['rn']) not in seen_rn: g_miss += 1
if g_miss: warn(f"glosswords.tsv: {g_miss} entries reference an rn not in any wordlist")

for h in read_tsv(f"{ROOT}/hptb.tsv", COLS['hptb']):
    for tok in (h['etyma_links'] or '').split(','):
        if tok and isint(tok) and int(tok) not in etyma_tags:
            warn(f"hptb.tsv hptbid {h['hptbid']}: links to missing etymon #{tok}")

if os.path.exists(f"{ROOT}/orphan_reflex_notes.tsv"):
    n_on = sum(1 for r in read_tsv(f"{ROOT}/orphan_reflex_notes.tsv", COLS['orphan_reflex_notes'])
               if r['rn'] and (not isint(r['rn']) or int(r['rn']) not in seen_rn))
    if n_on: warn(f"orphan_reflex_notes.tsv: {n_on} note(s) reference an rn not in any wordlist (expected: orphans)")
for row in read_tsv(f"{ROOT}/orphan_links.tsv", COLS['orphan_links']):
    if row['rn'] and not isint(row['rn']):  err(f"orphan_links.tsv: non-numeric rn {row['rn']!r}")
    if row['ind'] and not isint(row['ind']): err(f"orphan_links.tsv: non-numeric ind {row['ind']!r}")
    m = re.match(r'\d+', row['tag_str'] or '')
    if m and int(m.group()) not in etyma_tags: warn(f"orphan_links.tsv: tag {m.group()} not in etyma")

print(f"  reference: {len(grpids)} groups, {len(lgids)} languages, {len(semkeys)} thesaurus nodes, "
      f"{len(srcabbrs)} sources")

# ---- report ----
def show(label, items, cap=25):
    print(f"\n{label}: {len(items)}")
    for m in items[:cap]: print(f"  - {m}")
    if len(items) > cap: print(f"  … and {len(items)-cap} more")
show("WARNINGS", warns)
show("ERRORS", errors)
print()
if errors:
    print(f"FAILED — {len(errors)} error(s)."); sys.exit(1)
print(f"OK — integrity checks passed ({len(warns)} warning(s)).")
