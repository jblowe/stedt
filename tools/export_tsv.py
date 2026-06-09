#!/usr/bin/env python3
"""Export the normalized stedt.sqlite -> the all-TSV flat-file source of truth.

Hybrid layout (see data/FORMAT.md):

  data/sources/<srcabbr>/source.tsv      one-row bibliography entry (the source's home)
  data/sources/<srcabbr>/wordlist.tsv    reflexes from this source; morpheme tagging in 'analysis'
  data/sources/<srcabbr>/notes.tsv       reflex notes (keyed by rn) for this source's reflexes
  data/sources/<srcabbr>/annotations.tsv source-level bibliographic annotations
  data/etyma.tsv  mesoroots.tsv  etymon_notes.tsv     cognate sets + their children
  data/<reference>.tsv                   languages, languagegroups, thesaurus, chapter_notes,
                                         hptb, majorcats, otherchapters, pi, glosswords
  data/orphan_links.tsv  orphan_reflex_notes.tsv      rows whose rn is absent from any wordlist

Inverse of build_from_tsv.py. One-to-many collections (notes, mesoroots, annotations)
become their own tables rather than nested records; everything is written through the csv
module (delimiter='\t', QUOTE_MINIMAL) so any cell may hold tab/quote/newline-bearing prose
losslessly. The build_from_tsv → export_tsv round-trip is asserted lossless by
tools/gate_tsv_roundtrip.py. Drops the same non-curated columns documented in BUILD.md.

Usage:  python3 tools/export_tsv.py [DEST_DIR]   (default: repo data/)
"""
import sqlite3, os, csv, re, sys
from itertools import groupby

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # tools/ -> repo root
DEST = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_ROOT, "data")
DB = sys.argv[2] if len(sys.argv) > 2 else os.path.join(_ROOT, "stedt.sqlite")

def clean(s):  return '' if s is None else str(s)
def safe(name): return re.sub(r'[^A-Za-z0-9._-]', '_', name) or '_blank'

def write_tsv(path, header, rows):
    """Write one TSV through the csv module: QUOTE_MINIMAL quotes any cell bearing a
    tab, quote, or newline, so prose round-trips losslessly. The bulk prose-note files
    are newline-free by construction; only a few metadata cells use quoted multilines."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline='', encoding='utf-8') as f:
        w = csv.writer(f, delimiter='\t', quoting=csv.QUOTE_MINIMAL, lineterminator='\n')
        w.writerow(header)
        w.writerows(rows)


def main():
    db = sqlite3.connect(DB); db.row_factory = sqlite3.Row; c = db.cursor()
    grp = {r['grpid']: r for r in c.execute("SELECT * FROM languagegroups")}
    lang = {r['lgid']: r for r in c.execute("SELECT * FROM languagenames")}

    # ---- notes, partitioned by the entity they annotate (E->tag C->semkey S->srcabbr L->rn) ----
    enotes, cnotes, snotes, lnotes = [], [], [], []
    for r in c.execute("SELECT spec,rn,tag,id,notetype,xmlnote,ord,noteid FROM notes ORDER BY ord, noteid"):
        if not clean(r['xmlnote']): continue
        t = r['notetype'] or 'T'
        if r['spec'] == 'E':   enotes.append((r['tag'], t, r['xmlnote']))
        elif r['spec'] == 'C': cnotes.append((clean(r['id']), t, r['xmlnote']))
        elif r['spec'] == 'S': snotes.append((clean(r['id']), t, r['xmlnote']))
        elif r['spec'] == 'L': lnotes.append((r['rn'], t, r['xmlnote']))

    # ================= etyma + children =================
    PHON = ['handle', 'prefix', 'initial', 'medial', 'rhyme', 'tone', 'suffix', 'initcover', 'rhymecover']
    ETY_COLS = ['tag', 'grpid', 'protoform', 'gloss', 'semkey', 'chapter', 'sequence',
                'status', 'public', 'exemplary', 'xrefs', 'allofams', 'possallo', 'references'] + PHON
    ety_rows = []
    for r in c.execute("SELECT * FROM etyma ORDER BY tag"):
        status = {'DELETE': 'DELETE', 'KEEP': 'KEEP'}.get((r['status'] or '').upper(), r['status'] or '')
        chapter = clean(r['chapter']) if clean(r['chapter']) and r['chapter'] != (r['semkey'] or '') else ''
        seq = '' if r['sequence'] is None else repr(float(r['sequence']))
        row = [clean(r['tag']), clean(r['grpid']), clean(r['protoform']), clean(r['protogloss']),
               clean(r['semkey']), chapter, seq, status,
               '1' if r['public'] else '0', 'x' if r['exemplary'] == 'x' else '',
               clean(r['xrefs']), clean(r['allofams']), clean(r['possallo']), clean(r['notes'])]
        row += [clean(r[k]) for k in PHON]
        ety_rows.append(row)
    write_tsv(f"{DEST}/etyma.tsv", ETY_COLS, ety_rows)

    meso_rows = []
    for r in c.execute("SELECT * FROM mesoroots ORDER BY tag, id"):
        meso_rows.append([clean(r['tag']), clean(r['grpid']), clean(r['form']), clean(r['gloss']),
                          clean(r['variant']), (clean(r['old_tag']) if r['old_tag'] else ''),
                          clean(r['old_note'])])
    write_tsv(f"{DEST}/mesoroots.tsv", ['tag', 'grpid', 'form', 'gloss', 'variant', 'old_tag', 'source'], meso_rows)

    write_tsv(f"{DEST}/etymon_notes.tsv", ['tag', 'type', 'text'],
              [[clean(tag), t, x] for tag, t, x in enotes])

    # ================= reference tables =================
    write_tsv(f"{DEST}/thesaurus.tsv", ['semkey', 'title', 'semcat', 'old_chapter', 'old_subchapter'],
              [[clean(r['semkey']), clean(r['chaptertitle']), clean(r['semcat']),
                clean(r['old_chapter']), clean(r['old_subchapter'])]
               for r in c.execute("SELECT * FROM chapters ORDER BY id") if r['semkey']])
    write_tsv(f"{DEST}/chapter_notes.tsv", ['semkey', 'type', 'text'],
              [[clean(k), t, x] for k, t, x in cnotes])

    write_tsv(f"{DEST}/languages.tsv",
              ['lgid', 'name', 'abbr', 'grpid', 'source', 'iso', 'lgcode', 'sort',
               'srcofdata', 'picode', 'pinotes', 'pi_page', 'notes'],
              [[clean(r['lgid']), clean(r['language']), clean(r['lgabbr']), clean(r['grpid']),
                clean(r['srcabbr']), clean(r['silcode']), clean(r['lgcode']), clean(r['lgsort']),
                clean(r['srcofdata']), clean(r['picode']), clean(r['pinotes']),
                (clean(r['pi_page']) if r['pi_page'] else ''), clean(r['notes'])]
               for r in c.execute("SELECT * FROM languagenames ORDER BY lgid")])

    write_tsv(f"{DEST}/languagegroups.tsv",
              ['grpid', 'grpno', 'abbr', 'name', 'proto_language', 'genetic',
               'grp0', 'grp1', 'grp2', 'grp3', 'grp4'],
              [[clean(r['grpid']), clean(r['grpno']), clean(r['groupabbr']), clean(r['grp']),
                clean(r['plg']), ('1' if r['genetic'] else '0'),
                clean(r['grp0']), clean(r['grp1']), clean(r['grp2']), clean(r['grp3']), clean(r['grp4'])]
               for r in c.execute("SELECT * FROM languagegroups ORDER BY grpid")])

    # hptb: keep the raw 'tags' string AND the resolved etyma-link list (union of et_hptb_hash + tags)
    hlinks = {}
    for r in c.execute("SELECT tag,hptbid,ord FROM et_hptb_hash ORDER BY hptbid, ord"):
        hlinks.setdefault(r['hptbid'], []).append(r['tag'])
    hptb_rows = []
    for r in c.execute("SELECT * FROM hptb ORDER BY hptbid"):
        links = list(hlinks.get(r['hptbid'], []))
        for tok in clean(r['tags']).split(','):
            m = re.match(r'\d+', tok.strip())
            if m and int(m.group()) not in links:
                links.append(int(m.group()))
        hptb_rows.append([clean(r['hptbid']), clean(r['plg']), clean(r['protoform']), clean(r['protogloss']),
                          clean(r['pages']), clean(r['mainpage']), clean(r['init']), clean(r['bare']),
                          clean(r['semclass1']), clean(r['semclass2']), clean(r['tags']),
                          ','.join(str(x) for x in links)])
    write_tsv(f"{DEST}/hptb.tsv",
              ['hptbid', 'plg', 'protoform', 'gloss', 'pages', 'mainpage', 'init', 'allofams',
               'semclass', 'semclass2', 'tags', 'etyma_links'], hptb_rows)

    write_tsv(f"{DEST}/majorcats.tsv",
              ['chapter', 'subchapter', 'semcat', 'heading', 'frqdb', 'frqsubcats'],
              [[clean(r['chapter']), clean(r['subchapter']), clean(r['semcat']), clean(r['heading']),
                clean(r['frqdb']), clean(r['frqsubcats'])]
               for r in c.execute("SELECT * FROM majorcats ORDER BY id")])
    write_tsv(f"{DEST}/otherchapters.tsv",
              ['chapter', 'heading', 'semcat', 'subcat', 'cf', 'n'],
              [[clean(r['chapter']), clean(r['heading']), clean(r['semcat']), clean(r['subcat']),
                clean(r['cf']), clean(r['n'])]
               for r in c.execute("SELECT * FROM otherchapters ORDER BY id")])
    write_tsv(f"{DEST}/pi.tsv", ['lgid', 'page'],
              [[clean(r['lgid']), clean(r['page'])] for r in c.execute("SELECT lgid,page FROM pi ORDER BY lgid, page")])
    write_tsv(f"{DEST}/glosswords.tsv", ['word', 'rn', 'semcat', 'subcat', 'semkey'],
              [[clean(r['word']), clean(r['rn']), clean(r['semcat']), clean(r['subcat']), clean(r['semkey'])]
               for r in c.execute("SELECT word,rn,semcat,subcat,semkey FROM glosswords ORDER BY id")])

    # ================= per-source folders =================
    # analysis (morpheme slots ',' ; same-ind tags '|') reconstructed from lx_et_hash
    analysis = {}
    hashrows = c.execute("SELECT rn, ind, tag_str FROM lx_et_hash ORDER BY rn, ind, tag_str").fetchall()
    for rn, grp_rows in groupby(hashrows, key=lambda r: r['rn']):
        slots = ['|'.join(clean(x['tag_str']) for x in srows)
                 for _, srows in groupby(grp_rows, key=lambda r: r['ind'])]
        analysis[rn] = ','.join(slots)
    lex_rns = {row[0] for row in c.execute("SELECT rn FROM lexicon")}

    # reflexes -> wordlist bucket per source (source = languagenames[lgid].srcabbr, else _orphan)
    WL_COLS = ['rn', 'lgid', 'language', 'reflex', 'originalreflex', 'gloss', 'originalgloss',
               'gfn', 'originalgfn', 'semkey', 'srcid', 'src_set_rn', 'maintainer', 'status', 'analysis']
    rn_src = {}                # rn -> source bucket, to route reflex notes
    wl = {}
    for r in c.execute("SELECT * FROM lexicon"):
        ln = lang.get(r['lgid'])
        src = ln['srcabbr'] if ln and clean(ln['srcabbr']) else '_orphan'
        rn_src[r['rn']] = src
        wl.setdefault(src, []).append(
            [clean(r['rn']), clean(r['lgid']), (ln['language'] if ln else ''), clean(r['reflex']),
             clean(r['originalreflex']), clean(r['gloss']), clean(r['originalgloss']), clean(r['gfn']),
             clean(r['originalgfn']), clean(r['semkey']), clean(r['srcid']), clean(r['src_set_rn']),
             clean(r['maintainer']), clean(r['status']), clean(analysis.get(r['rn'], ''))])

    # source.tsv (one row each) for every bibliography entry
    SRC_COLS = ['srcabbr', 'citation', 'author', 'year', 'imprint', 'title', 'location', 'status',
                'dataformat', 'format', 'callnumber', 'scope', 'totalnum', 'refonly', 'citechk', 'pi',
                'infascicle', 'haveit', 'todo', 'proofer', 'inputter', 'dbprep', 'dbload', 'dbcheck', 'notes']
    src_rows = {r['srcabbr']: [clean(r[k]) for k in SRC_COLS] for r in c.execute("SELECT * FROM srcbib")}

    # reflex notes -> source bucket (orphans, rn absent from lexicon, spill to a global file)
    src_lnotes, orphan_lnotes = {}, []
    for rn, t, x in lnotes:
        if rn in rn_src: src_lnotes.setdefault(rn_src[rn], []).append([clean(rn), t, x])
        else: orphan_lnotes.append([clean(rn), t, x])
    # source annotations -> source bucket
    src_anno = {}
    for srcabbr, t, x in snotes:
        src_anno.setdefault(srcabbr, []).append([t, x])

    # union of every source that needs a folder
    all_srcs = set(wl) | set(src_rows) | set(src_lnotes) | set(src_anno)
    seen_fn = {}
    for s in all_srcs:                                   # safe() folder name must be injective
        fn = safe(s)
        if fn in seen_fn:
            raise ValueError(f"source folder collision: {s!r} and {seen_fn[fn]!r} both -> {fn}")
        seen_fn[fn] = s
    for s in sorted(all_srcs):
        d = f"{DEST}/sources/{safe(s)}"
        if s in src_rows:   write_tsv(f"{d}/source.tsv", SRC_COLS, [src_rows[s]])
        if s in wl:
            wl[s].sort(key=lambda x: int(x[0]))
            write_tsv(f"{d}/wordlist.tsv", WL_COLS, wl[s])
        if s in src_lnotes:
            src_lnotes[s].sort(key=lambda x: int(x[0]))
            write_tsv(f"{d}/notes.tsv", ['rn', 'type', 'text'], src_lnotes[s])
        if s in src_anno:   write_tsv(f"{d}/annotations.tsv", ['type', 'text'], src_anno[s])

    # ---- orphan cross-cutting rows ----
    orphan_lnotes.sort(key=lambda x: int(x[0]))
    write_tsv(f"{DEST}/orphan_reflex_notes.tsv", ['rn', 'type', 'text'], orphan_lnotes)
    orphan_links = [[clean(r['rn']), clean(r['ind']), clean(r['tag_str'])]
                    for r in c.execute("SELECT rn, ind, tag_str FROM lx_et_hash ORDER BY rn, ind")
                    if r['rn'] not in lex_rns]
    write_tsv(f"{DEST}/orphan_links.tsv", ['rn', 'ind', 'tag_str'], orphan_links)

    db.close()
    print(f"  etyma {len(ety_rows)}  mesoroots {len(meso_rows)}  etymon_notes {len(enotes)}")
    print(f"  sources {len(all_srcs)} ({sum(1 for s in all_srcs if s in wl)} with wordlists)  "
          f"reflexes {sum(len(v) for v in wl.values())}")
    print(f"  reflex_notes {sum(len(v) for v in src_lnotes.values())} (+{len(orphan_lnotes)} orphan)  "
          f"annotations {sum(len(v) for v in src_anno.values())}  orphan_links {len(orphan_links)}")


if __name__ == "__main__":
    main()
