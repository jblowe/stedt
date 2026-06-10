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
    "hanform": ('<span class="han" lang="zh">', "</span>"),  # declare CJK runs so SRs switch voice
    "gloss": ('<span class="gl">', "</span>"),
    "emph": ("<em>", "</em>"),
    "strong": ("<strong>", "</strong>"),
    # fallback only: page renderers pass a collector to render_note and get the original's
    # numbered bottom-of-page footnotes; without one (search-DB lexnote baking, note popovers —
    # contexts with no page bottom) the bracket keeps the aside from fusing into the sentence
    "footnote": (' <span class="fn">[fn: ', "]</span>"),
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


# Work-title abbreviations the original italicizes (rootcanal Notes.pm italicize_abbrevs) — cited
# monographs/journals (GSR, HPTB, LTBA…), set in italics like any work title.
_ITAL = re.compile(r"\b(GSR|GSTC|STC|HPTB|TBRS|LTSR|TSR|AHD|VSTB|TBT|HCT|LTBA|BSOAS|CSDPN|TIL|OED)\b")


def _typography(text):
    """Arrow notation + work-title italics on a TEXT chunk (no tags). The arrows arrive as
    entity-escaped ASCII ('&lt;--&gt;'); the original converts them to real arrows (Notes.pm).
    Other &lt;/&gt; stay entities — linguistic notation like '<WT' depends on it."""
    text = re.sub(r"&lt;-+&gt;", "⟷", text)
    text = re.sub(r"-+&gt;", "→", text)
    text = re.sub(r"&lt;-+", "←", text)
    return _ITAL.sub(r"<i>\1</i>", text)


def render_note(x, footnotes=None):
    if not x:
        return ""
    s = x
    # Footnote apparatus (rootcanal Notes.pm xml2html): with a page-level collector, each
    # <footnote> becomes a numbered superscript link and its body joins the page's bottom
    # footnote list (footnotes_block). Bodies are extracted BEFORE every other pass — they carry
    # the same tag vocabulary as note text (xrefs, forms, quote entities), so each is rendered
    # recursively through this whole pipeline, not patched through the outer note's passes.
    # Numbering continues across the notes of one page (n = list length so far). The marker is
    # planted as a control-char slot and substituted at the end so no pass can mangle it.
    if footnotes is not None:

        def _foot(m):
            n = len(footnotes) + 1
            footnotes.append(render_note(m.group(1)).replace('<p class="np">', "").replace("</p>", ""))
            return f"\x02{n}\x03"

        s = re.sub(r"<footnote>(.*?)</footnote>", _foot, s, flags=re.S)
    # Note text writes the asterisk literally inside <reconstruction>*li̯ək</reconstruction>
    # (all such notes, zero exceptions) — keep it as REAL text (CSS ::before doesn't copy), only
    # wrap it in .star for the accent color. Leading star only: interior stars in multi-form
    # contents ('*lək, *li̯ək' in one tag) stay plain literal text and still render right.
    s = s.replace("<reconstruction>*", '<reconstruction><span class="star">*</span>')
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
        return f'<span class="han" lang="zh">{ch}</span>'

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
                    bits.append(f'<span class="recon"><span class="star">*</span>{esc(alt(pf))}</span>')
                if pg:
                    bits.append(esc(pg))
                if bits:
                    txt = f"{txt} " + " ".join(bits)
            return f'<a class="xref" href="{etymon_href(ref)}">{txt}</a>'
        return f'<span class="xref">{txt}</span>'

    s = re.sub(r'<xref[^>]*\bref="(\d+)"[^>]*>(.*?)</xref>', _xref, s, flags=re.S)
    s = re.sub(r"</?xref[^>]*>", "", s)
    # anchors keep only their href; external links open in the same tab (convention at iso_link)
    s = re.sub(r'<a\s+href="([^"]*)"[^>]*>(.*?)</a>', r'<a href="\1">\2</a>', s, flags=re.S)
    for t, (o, c) in _PAIR.items():
        s = s.replace(f"<{t}>", o).replace(f"</{t}>", c)
    s = re.sub(r"<br\s*/?>", "<br>", s)
    s = _smart_quotes(s)
    s = s.replace("\x00", "'").replace("\x01", '"')  # shielded form-internal marks stay straight
    # typography (arrows, work-title italics) on text runs only — never inside a tag
    s = "".join(p if p.startswith("<") else _typography(p) for p in re.split(r"(<[^>]+>)", s))
    if footnotes is not None:  # slots planted above -> superscript markers (rootcanal's footlink/toof ids)
        s = re.sub(r"\x02(\d+)\x03", r'<a class="footlink" href="#foot\1" id="toof\1"><sup>\1</sup></a>', s)
    # Leave &lt;/&gt;/&amp; as entities: in note text they're literal angle brackets/ampersands
    # (linguistic notation like "<WT", "<n>", "&lt;--&gt;"). Un-escaping them to raw < > here
    # produced bogus unclosed tags. Structural markup uses literal <tag> and was handled above.
    if "<p" not in s:
        s = f'<p class="np">{s}</p>'
    return s


def footnotes_block(footnotes):
    """Bottom-of-page footnote list paired with render_note's superscript markers — ids must
    mirror the markers' (#foot{n} target, #toof{n} backlink), numbering from 1 in list order."""
    if not footnotes:
        return ""
    return (
        '<div class="footnotes">'
        + "".join(
            f'<div class="fnote" id="foot{n}"><a href="#toof{n}" class="footback">{n}</a> {body}</div>'
            for n, body in enumerate(footnotes, 1)
        )
        + "</div>"
    )
