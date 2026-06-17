"""Shared row fragments used by more than one entity page — the server-side counterpart of
web/src/rows.js (the client renders the same row shapes)."""

from .notes import note_span
from .shell import etymon_href, source_href
from .syllabify import syllabify
from .text import esc, alt, morph_label, seq_label


def syl_pop(tag, info):
    """SYNC(syllable-links) ↔ web/src/rows.js sylPop. The hover/focus popover for a linked
    syllable — the original's elink popup (rootcanal tt/et_info.tt), all three parts:
    - header "#tag PLG *protoform ‘gloss’", linked to the etymon page (the original's '#232:');
    - the etymon's mesoroots ("PLG *form ‘gloss’", Stammbaum-ordered), each PLG linked to its
      row on the etymon page (#ms-{grpno} — the original linked /etymon/tag#grpno);
    - the computed allofam family ("1a #34 PLG *form ‘gloss’"), members linked, the popover's
      own etymon bold and unlinked, exactly the original's list. The original's tab SWITCHER
      is the one omission (tabs can't operate in a hover card): both sections show, labeled.
    The card sits NEXT TO the trigger link (inside .syl-w), not inside it, so its links are
    real. info: (pf, pg, plg, mesoroots, family)."""
    pfx, pgl, plg, meso, fam = info
    g = f" ‘{esc(pgl)}’" if pgl else ""
    head = (f'<a class="sp-h" href="{etymon_href(tag)}">#{tag}{" " + esc(plg) if plg else ""}'
            f' *{esc(alt(pfx))}{g}</a>')
    out = head
    if meso:
        if fam:
            out += '<span class="sp-sec">Mesoroots</span>'
        out += "".join(
            f'<a class="sp-m" href="{etymon_href(tag)}#ms-{esc(str(no or ""))}">'
            f'<span class="sp-plg">{esc(mp or "")}</span> *{esc(alt(mf))}{f" ‘{esc(mg)}’" if mg else ""}</a>'
            for mp, mf, mg, no in meso
        )
    if fam:
        out += '<span class="sp-sec">Allofams</span>'
        for seq, t2, plg2, pf2, pg2 in fam:
            lab = (f'{esc(seq_label(seq))} #{t2}{" " + esc(plg2) if plg2 else ""} *{esc(alt(pf2))}'
                   f'{f" ‘{esc(pg2)}’" if pg2 else ""}')
            out += (f'<span class="sp-m"><b>{lab}</b></span>' if t2 == tag
                    else f'<a class="sp-m" href="{etymon_href(t2)}">{lab}</a>')
    return f'<span class="sylpop">{out}</span>'


def morph_mark(code, base):
    """SYNC(morph-codes) ↔ web/src/rows.js morphMark — a coded (non-cognate) morpheme: the syllable
    text marked (.morph; borrowings add .morph-b to stand out a touch more) with a hover/focus
    popover naming the analysis (text.morph_label). The popover sits BESIDE the mark inside .morph-w,
    mirroring the cognate links' .syl-w, so the two annotation kinds lay out the same. base is already
    escaped."""
    cls = "morph morph-b" if code[:1] == "b" else "morph"
    return f'<span class="morph-w"><span class="{cls}" tabindex="0">{base}</span><span class="mpop">{esc(morph_label(code))}</span></span>'


def morph_chip(codes):
    """SYNC(reflex-row) ↔ web/src/rows.js morphChip — the fallback trailing summary of a reflex's
    morpheme codes (' · prefix · Indic loanword'), used when the form can't be syllabified so the
    marks can't sit on the morphemes themselves. codes: {position: code}, rendered in order."""
    if not codes:
        return ""
    labs = " · ".join(esc(morph_label(codes[i])) for i in sorted(codes))
    return f'<span class="anl">{labs}</span>'


def syl_form(reflex, syn, pf=None, self_tag=None, codes=None):
    """SYNC(syllable-links) ↔ web/src/rows.js sylLink — keep the markup identical.
    Reflex surface form as HTML with each tagged syllable linked to its own etymon (cognate links,
    each carrying a *protoform 'gloss' popover) and each coded morpheme marked (morph_mark). On an
    etymon page, pass self_tag = that etymon: the syllable that IS this etymon is marked but not
    linked (you're already here). Returns None to fall back to the plain form + trailing chips
    (morph_chip carries the codes there). pf: tag -> (protoform, protogloss); codes: {position: code}."""
    syn = syn or {}
    codes = codes or {}
    if not syn and not codes:
        return None
    syls, dl, prefix = syllabify(reflex or "")
    if any(k >= len(syls) for k in syn) or any(k >= len(syls) for k in codes):   # a tag/code must land on a real syllable
        return None
    pf = pf or {}
    out = esc(prefix)
    for i, syl in enumerate(syls):
        tag = syn.get(i)
        base = esc(syl)
        if tag is not None and tag == self_tag:
            out += f'<span class="syl-self">{base}</span>'   # this etymon's own reflex syllable
        elif tag is not None and tag in pf:
            # pf membership gates the link: pf comes from proto_labels(), which is restricted to
            # non-DELETE etyma — the only ones with a built page. A tag outside pf (withdrawn
            # etymon) renders as plain text, matching the client, whose DELETE-filtered join never
            # sees such tags at all.
            # the popover sits BESIDE the link inside a .syl-w wrapper (hover/focus-within on the
            # wrapper reveals it): nested <a> is invalid HTML, and the card now carries links
            info = pf[tag]
            pop = syl_pop(tag, info) if info else ""
            link = f'<a class="syl" href="{etymon_href(tag)}">{base}</a>'
            out += f'<span class="syl-w">{link}{pop}</span>' if pop else link
        elif i in codes:
            out += morph_mark(codes[i], base)
        else:
            out += base
        d = dl[i] if i < len(dl) else ""
        out += esc(d).replace("◦", '<span class="br">◦</span>')
    return out


def disp_form(s):
    """SYNC(display-form) ↔ web/src/rows.js dispForm — the plain (unlinked) rendering of a stored
    form. The '|' in a stored form is STEDT's internal analysis-override delimiter, never part of
    the citation form: the original stripped it from every displayed form, and our syllable-linked
    path does too (syllabify glues 'g-|lak' → 'g-lak'). Route piped forms through the same
    syllabify+rejoin; unpiped forms pass straight through. Escapes, and mutes the ◦ morpheme
    separator like the linked path."""
    s = s or ""
    if "|" not in s:
        return esc(s).replace("◦", '<span class="br">◦</span>')
    syls, dl, prefix = syllabify(s)
    out = esc(prefix)
    for i, syl in enumerate(syls):
        out += esc(syl)
        out += esc(dl[i] if i < len(dl) else "").replace("◦", '<span class="br">◦</span>')
    return out


def lgab_span(lgabbr):
    """The language-abbreviation chip (leading space + <span class="lgab">), or "" when absent."""
    return f' <span class="lgab">{esc(lgabbr)}</span>' if lgabbr else ""


def as_abbr(lgabbr, name):
    """The "as SHORTNAME" connective — a muted .asab span around the .lgab chip — for the lead of
    an entity row's metadata (.subg) column. Empty when the abbr is absent or merely echoes the lect
    name (no point printing "Khaling as Khaling"). SYNC: source.py langinfo ↔ language.py variants
    both lead .subg with this, so a source's short name for a lect reads the same from either end."""
    ab = (lgabbr or "").strip()
    if not ab or ab.casefold() == (name or "").strip().casefold():
        return ""
    return f'<span class="asab">as <span class="lgab">{esc(ab)}</span></span>'


def etymon_flags(exemplary, public, prov_title=None):
    """SYNC(etymon-row) ↔ web/src/rows.js etymonRow — the ' · exemplary' / ' · provisional'
    chips trailing an etymon's tag line, identical wherever an etymon row renders. prov_title:
    the etymon page's own header explains the provisional mark with a tooltip; rows don't."""
    out = ' · <span class="exm">exemplary</span>' if (exemplary or "") == "x" else ""
    if not public:
        t = f' title="{esc(prov_title)}"' if prov_title else ""
        out += f' · <span class="prov"{t}>provisional</span>'
    return out


def noted_gloss(rn, gloss, notes):
    """SYNC(reflex-row) ↔ web/src/rows.js reflexRow — the gloss cell when the reflex carries
    lexical notes: the note popover rides on the gloss behind a circled-i. The popover lives
    INSIDE the inline gloss <span>, so each note renders as an inline note_span (a block <p>
    here would be invalid markup); aria-describedby ties the notes to the gloss for AT.
    notes: [(notetype, xmlnote), …] as lexical_notes() returns them."""
    pop = "".join(note_span(nt, x) for nt, x in notes)
    return (
        f'<span class="g noted" tabindex="0" aria-describedby="np{rn}">{esc(gloss)}'
        f'<span class="notepop" role="note" id="np{rn}">{pop}</span></span>'
    )


def src_cell(srcabbr, citation, srcid):
    """SYNC(reflex-row) ↔ web/src/rows.js reflexRow — the source cell: the work the form is
    attested in (citation linked to its source page) + ': locus' (page/entry/note) within it;
    a record with no source keeps its citation text as a plain span."""
    loc = f": {esc(srcid)}" if srcid else ""
    if srcabbr:
        return f'<a class="src" href="{source_href(srcabbr)}">{esc(citation or srcabbr)}{loc}</a>'
    return f'<span class="src">{esc(citation or "")}{loc}</span>'
