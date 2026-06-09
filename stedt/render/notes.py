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
    s = x
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
    # Leave &lt;/&gt;/&amp; as entities: in note text they're literal angle brackets/ampersands
    # (linguistic notation like "<WT", "<n>", "&lt;--&gt;"). Un-escaping them to raw < > here
    # produced bogus unclosed tags. Structural markup uses literal <tag> and was handled above.
    if "<p" not in s:
        s = f'<p class="np">{s}</p>'
    return s
