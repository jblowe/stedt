"""Shared row fragments used by more than one entity page — the server-side counterpart of
web/src/rows.js (the client renders the same row shapes)."""

from .shell import etymon_href
from .syllabify import syllabify
from .text import esc, alt


def syl_pop(info):
    """SYNC(syllable-links) ↔ web/src/rows.js sylLink popover. The hover/focus popover for a linked
    syllable: its etymon's *protoform 'gloss'. info: (pf, pg)."""
    pfx, pgl = info
    g = f" ‘{esc(pgl)}’" if pgl else ""
    return f'<span class="sylpop">*{esc(alt(pfx))}{g}</span>'


def syl_form(reflex, syn, pf=None, self_tag=None):
    """SYNC(syllable-links) ↔ web/src/rows.js sylLink — keep the markup identical.
    Reflex surface form as HTML with each tagged syllable linked to its own etymon, each carrying a
    hover/focus popover previewing that etymon (*protoform 'gloss'). On an etymon page, pass self_tag =
    that etymon: the syllable that IS this etymon is marked but not linked (you're already here).
    Returns None to fall back to the plain form + trailing chips. pf: tag -> (protoform, protogloss)."""
    if not syn:
        return None
    syls, dl, prefix = syllabify(reflex or "")
    if any(k >= len(syls) for k in syn):       # a tag must land on a real syllable
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
            info = pf[tag]
            out += f'<a class="syl" href="{etymon_href(tag)}">{base}{syl_pop(info) if info else ""}</a>'
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
