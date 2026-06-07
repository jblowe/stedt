#!/usr/bin/env python3
"""Validate the STEDT flat-file source in data/ for referential integrity.

Exit code 1 if any ERRORs (integrity violations that must block a merge);
WARNINGs (data-quality issues) are reported but do not fail. Run: python3 validate.py
"""
import yaml, csv, glob, os, re, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
csv.field_size_limit(10**7)
rel = lambda p: os.path.relpath(p, ROOT)
errors, warns = [], []
def err(m): errors.append(m)
def warn(m): warns.append(m)

def loadyaml(p):
    try:
        return yaml.safe_load(open(p, encoding='utf-8'))
    except Exception as e:
        err(f"{rel(p)}: YAML parse error: {e}"); return None

def refset(items, key, label):
    """Build a key set; ERROR on entries missing the key or duplicating it."""
    s = set()
    for it in (items or []):
        if not isinstance(it, dict) or key not in it:
            err(f"reference/{label}: entry missing required '{key}': {str(it)[:80]}"); continue
        v = it[key]
        if v in s: err(f"reference/{label}: duplicate {key} {v!r}")
        else: s.add(v)
    return s

# ---- reference tables (missing-key and duplicate-key are ERRORs) ----
groups = loadyaml(f"{ROOT}/reference/languagegroups.yaml") or []
langs  = loadyaml(f"{ROOT}/reference/languages.yaml") or []
thes   = loadyaml(f"{ROOT}/reference/thesaurus.yaml") or []
bib    = loadyaml(f"{ROOT}/reference/bibliography.yaml") or []
hptb   = loadyaml(f"{ROOT}/reference/hptb.yaml") or []
grpids   = refset(groups, 'grpid', 'languagegroups.yaml')
lgids    = refset(langs,  'lgid',  'languages.yaml')
semkeys  = refset(thes,   'semkey', 'thesaurus.yaml')
srcabbrs = refset(bib,    'srcabbr', 'bibliography.yaml')
refset(hptb, 'hptbid', 'hptb.yaml')
lgname = {l['lgid']: (l.get('name') or '') for l in langs if isinstance(l, dict) and 'lgid' in l}

# ---- etyma ----
etyma_tags = set()
VALID_STATUS = {'KEEP', 'DELETE', ''}
n_ety = 0
for p in sorted(glob.glob(f"{ROOT}/etyma/*.yaml")):
    d = loadyaml(p)
    if d is None: continue
    if not isinstance(d, dict):
        err(f"{rel(p)}: top-level YAML is not a mapping"); continue
    n_ety += 1
    base = os.path.basename(p)[:-5]
    if not base.isdigit():
        err(f"{rel(p)}: non-numeric etymon filename"); fn_tag = None
    elif base != str(int(base)):
        err(f"{rel(p)}: non-canonical filename (leading zeros)"); fn_tag = int(base)
    else:
        fn_tag = int(base)
    tag = d.get('tag')
    try: tag_int = int(tag) if tag is not None else None
    except (TypeError, ValueError): tag_int = None; err(f"{rel(p)}: non-integer tag {tag!r}")
    if tag is None:                              err(f"{rel(p)}: missing 'tag'")
    elif fn_tag is not None and tag_int != fn_tag: err(f"{rel(p)}: tag {tag} does not match filename ({fn_tag})")
    if tag_int is not None:
        if tag_int in etyma_tags: err(f"{rel(p)}: duplicate etymon tag {tag_int}")
        etyma_tags.add(tag_int)
    if 'status' not in d:                                     warn(f"{rel(p)}: no 'status' recorded")
    elif (d.get('status') or '').upper() not in VALID_STATUS: warn(f"{rel(p)}: unknown status {d.get('status')!r}")
    if d.get('grpid') is not None and d['grpid'] not in grpids:
        warn(f"{rel(p)}: grpid {d['grpid']} not in languagegroups")
    sk = d.get('semkey')
    if sk and sk not in semkeys: err(f"{rel(p)}: semkey {sk!r} not in thesaurus")
    ms = d.get('mesoroots')
    if ms is not None and not isinstance(ms, list):
        err(f"{rel(p)}: 'mesoroots' must be a list")
    else:
        for m in (ms or []):
            if not isinstance(m, dict): err(f"{rel(p)}: mesoroot entry is not a mapping"); continue
            if m.get('grpid') is not None and m['grpid'] not in grpids:
                warn(f"{rel(p)}: mesoroot grpid {m['grpid']} not in languagegroups")
    nt = d.get('notes')
    if nt is not None and not isinstance(nt, list):
        err(f"{rel(p)}: 'notes' must be a list")
print(f"  etyma: {n_ety} files, {len(etyma_tags)} tags")

# ---- wordlists ----
EXPECT = ['rn', 'lgid', 'language', 'reflex', 'originalreflex', 'gloss', 'originalgloss',
          'gfn', 'originalgfn', 'semkey', 'srcid', 'src_set_rn', 'maintainer', 'status', 'analysis']
def toks(analysis):
    for slot in (analysis or '').split(','):
        for t in slot.split('|'):
            yield t
seen_rn, n_ref = {}, 0
missing_ref, bad_token = {}, {}
for p in sorted(glob.glob(f"{ROOT}/wordlists/*.tsv")):
    with open(p, encoding='utf-8', newline='') as f:
        rdr = csv.DictReader(f, delimiter='\t')
        if rdr.fieldnames != EXPECT:
            err(f"{rel(p)}: unexpected columns {rdr.fieldnames}"); continue
        for row in rdr:
            n_ref += 1
            rn = row['rn']
            if not rn or not rn.isdigit():
                err(f"{rel(p)}: non-numeric rn {rn!r}"); continue
            rn = int(rn)
            if rn in seen_rn: err(f"{rel(p)}: duplicate rn {rn} (also in {seen_rn[rn]})")
            else: seen_rn[rn] = rel(p)
            lg = row['lgid']
            if lg:
                if not lg.isdigit():            err(f"{rel(p)} rn {rn}: non-numeric lgid {lg!r}")
                elif int(lg) not in lgids:      warn(f"{rel(p)} rn {rn}: lgid {lg} not in languages")
                else:
                    exp = lgname.get(int(lg))
                    if row['language'] and exp and row['language'] != exp:
                        warn(f"{rel(p)} rn {rn}: language col {row['language']!r} != lgid {lg} ({exp!r}); 'language' is derived/read-only")
            if row['src_set_rn'] and not row['src_set_rn'].isdigit():
                err(f"{rel(p)} rn {rn}: non-numeric src_set_rn {row['src_set_rn']!r}")
            if row['semkey'] and row['semkey'] not in semkeys:
                warn(f"{rel(p)} rn {rn}: semkey {row['semkey']!r} not in thesaurus")
            for tok in toks(row['analysis']):
                m = re.match(r'\d+', tok)
                if m:
                    t = int(m.group())
                    if t not in etyma_tags: missing_ref.setdefault(t, f"{rel(p)} rn {rn}")
                elif re.search(r'\d', tok) and not re.match(r'^[A-Za-z?]', tok):
                    bad_token.setdefault(tok, f"{rel(p)} rn {rn}")   # leading junk before digits -> likely typo'd cognate
print(f"  wordlists: {len(glob.glob(f'{ROOT}/wordlists/*.tsv'))} files, {n_ref} reflexes")

for t, where in sorted(missing_ref.items()):
    err(f"analysis references etymon #{t} which has no data/etyma/{t}.yaml (e.g. {where})")
for tok, where in sorted(bad_token.items()):
    warn(f"analysis token {tok!r} has digits but no leading digit/marker — possible mis-encoded cognate ({where})")

# ---- reflex notes, glosswords, orphan links ----
rnotes = loadyaml(f"{ROOT}/reference/reflex-notes.yaml") or []
orphan_notes = sum(1 for n in rnotes if n.get('rn') not in seen_rn)
if orphan_notes:
    warn(f"reflex-notes.yaml: {orphan_notes} note(s) reference an rn not present in any wordlist")
for h in hptb:
    for tg in h.get('etyma') or []:
        if tg not in etyma_tags:   # inherited dangling HPTB links from the dump
            warn(f"hptb.yaml hptbid {h.get('hptbid')}: links to missing etymon #{tg}")

def tsv_rn_check(path, label):
    if not os.path.exists(path): return
    miss = 0
    with open(path, encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f, delimiter='\t'):
            rn = row.get('rn')
            if rn and not rn.isdigit(): err(f"{label}: non-numeric rn {rn!r}")
            elif rn and int(rn) not in seen_rn: miss += 1
    if miss: warn(f"{label}: {miss} entries reference an rn not in any wordlist")
tsv_rn_check(f"{ROOT}/reference/glosswords.tsv", "glosswords.tsv")

opath = f"{ROOT}/reference/orphan-links.tsv"
if os.path.exists(opath):
    with open(opath, encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f, delimiter='\t'):
            m = re.match(r'\d+', row.get('tag_str') or '')
            if m and int(m.group()) not in etyma_tags:
                warn(f"orphan-links.tsv: tag {m.group()} not in etyma")

print(f"  reference: {len(grpids)} groups, {len(lgids)} languages, {len(semkeys)} thesaurus nodes, "
      f"{len(srcabbrs)} sources, {len(rnotes)} reflex-notes")

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
