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
        elif tag is not None:
            info = pf.get(tag)
            out += f'<a class="syl" href="{etymon_href(tag)}">{base}{syl_pop(info) if info else ""}</a>'
        else:
            out += base
        d = dl[i] if i < len(dl) else ""
        out += esc(d).replace("◦", '<span class="br">◦</span>')
    return out


def lgab_span(lgabbr):
    """The language-abbreviation chip (leading space + <span class="lgab">), or "" when absent."""
    return f' <span class="lgab">{esc(lgabbr)}</span>' if lgabbr else ""
