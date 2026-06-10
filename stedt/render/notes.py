"""STEDT note-XML -> HTML (bounded ~15-tag vocab); cross-refs linked to built etymon pages."""

import re

from .db import valid_etymon_tags, xref_labels
from .text import esc, alt
from .shell import etymon_href

# ---------------------------------------------------------------- note XML -> HTML
_ENT = {"&quot;": '"', "&apos;": "’", "&amp;": "&", "&lt;": "<", "&gt;": ">"}
_PAIR = {
    "par": ('<p class="np">', "</p>"),
    "reconstruction": ('<span class="recon">', "</span>"),
    "latinform": ('<span class="lat">', "</span>"),
    "plainlatinform": ('<span class="lat">', "</span>"),
    "hanform": ('<span class="han">', "</span>"),
    "gloss": ('<span class="gl">', "</span>"),
    "emph": ("<em>", "</em>"),
    "strong": ("<strong>", "</strong>"),
    "footnote": ('<span class="fn">', "</span>"),
    "unicode": ("<span>", "</span>"),
    "sup": ("<sup>", "</sup>"),
    "sub": ("<sub>", "</sub>"),
}


def note_label(notetype):
    """Provenance prefix for a reflex-level note: notetype 'O' notes are quoted from the cited
    source, not STEDT commentary — the original labels them '[Source note]' so readers can tell
    the dictionary's own annotation from an editor's (rootcanal Notes.pm does the same; 'I'
    internal notes are excluded upstream, and no other public type carries a label)."""
    return "[Source note] " if (notetype or "").upper() == "O" else ""


def _smart_quotes(s):
    """Turn the &quot;/&apos; entities found in note *text* (tag attributes use literal
    quotes, so they stay untouched) into directional quotation marks, by context."""

    def repl(m):
        i = m.start()
        prev = s[i - 1] if i > 0 else ""
        opening = prev == "" or prev.isspace() or prev in "([{<>“‘—–-/"
        if m.group(0) == "&quot;":
            return "“" if opening else "”"
        return "‘" if opening else "’"

    return re.sub(r"&quot;|&apos;", repl, s)


def render_note(x):
    if not x:
        return ""
    # Note text writes the asterisk literally inside <reconstruction>*li̯ək</reconstruction>
    # (all 512 such notes, zero exceptions), but CSS .recon::before injects one too — strip the
    # literal one so note recons show '*li̯ək', not '**li̯ək' ('**' marks a rejected form to
    # historical linguists). Leading star only: ::before fires once per span, so interior stars
    # in multi-form contents ('*lək, *li̯ək' in one tag) stay literal and still render right.
    s = x.replace("<reconstruction>*", "<reconstruction>")
    # Shield quote entities inside form tags from _smart_quotes: a form-initial apostrophe is a
    # tone/register letter, not punctuation — educating it to ‘ makes it read as an opening quote
    # (rootcanal Notes.pm _qtd shields forms the same way). Placeholders survive the passes below
    # and are restored as straight marks after the quote pass.
    s = re.sub(
        r"<(latinform|plainlatinform|reconstruction|hanform)>(.*?)</\1>",
        lambda m: m.group(0).replace("&apos;", "\x00").replace("&quot;", "\x01"),
        s,
        flags=re.S,
    )
    # <unicode>HEX</unicode> names a codepoint (Han characters beyond the fonts of the era) — emit
    # the character itself, not the hex digits (rootcanal Notes.pm emits &#xHEX;).
    def _uni(m):
        try:
            ch = chr(int(m.group(1), 16))
        except (ValueError, OverflowError):
            return esc(m.group(1))
        return f'<span class="han">{ch}</span>'

    s = re.sub(r"<unicode>\s*([0-9A-Fa-f]{1,6})\s*</unicode>", _uni, s)
    valid = valid_etymon_tags()
    labels = xref_labels()

    def _xref(m):  # only link xrefs to a built (non-DELETE) etymon; else keep the label, drop the link
        ref, txt = m.group(1), m.group(2)
        rid = int(ref)
        if rid in valid:
            lab = labels.get(rid)
            # annotate only a bare "#N" reference; leave an author-written label (the rare xref whose
            # text already spells out a gloss) untouched, so the gloss isn't printed twice.
            if lab and re.fullmatch(r"\s*#?\d+\s*", txt):
                plg, pf, pg = lab
                bits = []
                if plg:
                    bits.append(esc(plg))
                if pf:
                    bits.append(f'<span class="recon">{esc(alt(pf))}</span>')  # CSS .recon::before adds the *
                if pg:
                    bits.append(esc(pg))
                if bits:
                    txt = f"{txt} " + " ".join(bits)
            return f'<a class="xref" href="{etymon_href(ref)}">{txt}</a>'
        return f'<span class="xref">{txt}</span>'

    s = re.sub(r'<xref[^>]*\bref="(\d+)"[^>]*>(.*?)</xref>', _xref, s, flags=re.S)
    s = re.sub(r"</?xref[^>]*>", "", s)
    s = re.sub(
        r'<a\s+href="([^"]*)"[^>]*>(.*?)</a>', r'<a href="\1" rel="noopener" target="_blank">\2</a>', s, flags=re.S
    )
    for t, (o, c) in _PAIR.items():
        s = s.replace(f"<{t}>", o).replace(f"</{t}>", c)
    s = re.sub(r"<br\s*/?>", "<br>", s)
    s = _smart_quotes(s)
    s = s.replace("\x00", "'").replace("\x01", '"')  # shielded form-internal marks stay straight
    # Leave &lt;/&gt;/&amp; as entities: in note text they're literal angle brackets/ampersands
    # (linguistic notation like "<WT", "<n>", "&lt;--&gt;"). Un-escaping them to raw < > here
    # produced bogus unclosed tags. Structural markup uses literal <tag> and was handled above.
    if "<p" not in s:
        s = f'<p class="np">{s}</p>'
    return s
