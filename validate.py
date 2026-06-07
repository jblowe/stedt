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

# ---- reference tables ----
groups = loadyaml(f"{ROOT}/reference/languagegroups.yaml") or []
langs  = loadyaml(f"{ROOT}/reference/languages.yaml") or []
thes   = loadyaml(f"{ROOT}/reference/thesaurus.yaml") or []
bib    = loadyaml(f"{ROOT}/reference/bibliography.yaml") or []
grpids   = {g['grpid'] for g in groups if 'grpid' in g}
lgids    = {l['lgid'] for l in langs if 'lgid' in l}
semkeys  = {t['semkey'] for t in thes if 'semkey' in t}
srcabbrs = {b['srcabbr'] for b in bib if 'srcabbr' in b}

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
    fn_tag = int(base) if base.isdigit() else None
    tag = d.get('tag')
    if tag is None:                err(f"{rel(p)}: missing 'tag'")
    elif tag != fn_tag:            err(f"{rel(p)}: tag {tag} does not match filename ({fn_tag})")
    if tag is not None: etyma_tags.add(tag)
    if 'status' not in d:                                warn(f"{rel(p)}: no 'status' recorded")
    elif (d.get('status') or '').upper() not in VALID_STATUS: warn(f"{rel(p)}: unknown status {d.get('status')!r}")
    if d.get('grpid') is not None and d['grpid'] not in grpids:
        warn(f"{rel(p)}: grpid {d['grpid']} not in languagegroups")
    sk = d.get('semkey')
    if sk and sk not in semkeys:   warn(f"{rel(p)}: semkey {sk!r} not in thesaurus")
    for m in d.get('mesoroots') or []:
        if m.get('grpid') is not None and m['grpid'] not in grpids:
            warn(f"{rel(p)}: mesoroot grpid {m['grpid']} not in languagegroups")
print(f"  etyma: {n_ety} files, {len(etyma_tags)} tags")

# ---- wordlists ----
EXPECT = ['rn', 'lgid', 'language', 'reflex', 'originalreflex', 'gloss', 'originalgloss',
          'gfn', 'originalgfn', 'semkey', 'srcid', 'src_set_rn', 'maintainer', 'status', 'analysis']
TAGRE = re.compile(r'\d+')
seen_rn, n_ref = {}, 0
missing_ref = {}   # missing etymon tag -> example "file rn"
for p in sorted(glob.glob(f"{ROOT}/wordlists/*.tsv")):
    with open(p, encoding='utf-8', newline='') as f:
        rdr = csv.DictReader(f, delimiter='\t')
        if rdr.fieldnames != EXPECT:
            err(f"{rel(p)}: unexpected columns {rdr.fieldnames}")
            continue
        for row in rdr:
            n_ref += 1
            rn = row['rn']
            if not rn or not rn.isdigit():
                err(f"{rel(p)}: non-numeric rn {rn!r}"); continue
            rn = int(rn)
            if rn in seen_rn: err(f"{rel(p)}: duplicate rn {rn} (also in {seen_rn[rn]})")
            else: seen_rn[rn] = rel(p)
            lg = row['lgid']
            if lg and lg.isdigit() and int(lg) not in lgids:
                warn(f"{rel(p)} rn {rn}: lgid {lg} not in languages")
            for tok in (row['analysis'] or '').split(','):
                m = TAGRE.match(tok)
                if m:
                    t = int(m.group())
                    if t not in etyma_tags:
                        missing_ref.setdefault(t, f"{rel(p)} rn {rn}")
print(f"  wordlists: {len(glob.glob(f'{ROOT}/wordlists/*.tsv'))} files, {n_ref} reflexes")

for t, where in sorted(missing_ref.items()):
    err(f"analysis references etymon #{t} which has no data/etyma/{t}.yaml (e.g. {where})")

# ---- reflex notes ----
rnotes = loadyaml(f"{ROOT}/reference/reflex-notes.yaml") or []
orphan_notes = sum(1 for n in rnotes if n.get('rn') not in seen_rn)
if orphan_notes:
    warn(f"reflex-notes.yaml: {orphan_notes} note(s) reference an rn not present in any wordlist")

# ---- HPTB links + glosswords references ----
for h in (loadyaml(f"{ROOT}/reference/hptb.yaml") or []):
    for tg in h.get('etyma') or []:
        if tg not in etyma_tags:   # pre-existing dangling links inherited from the dump
            warn(f"hptb.yaml hptbid {h.get('hptbid')}: links to missing etymon #{tg}")
gw_path = f"{ROOT}/reference/glosswords.tsv"
if os.path.exists(gw_path):
    gw_missing = 0
    with open(gw_path, encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f, delimiter='\t'):
            if row['rn'] and row['rn'].isdigit() and int(row['rn']) not in seen_rn:
                gw_missing += 1
    if gw_missing:
        warn(f"glosswords.tsv: {gw_missing} entries reference an rn not in any wordlist")
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
