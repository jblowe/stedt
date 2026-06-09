"""Small formatting + URL helpers: HTML escaping, proto-form stars, ISO/citation links."""
import html
import re

def natkey(s):
    out = []
    for p in (s or '').split('.'):
        out.append((0, int(p), '') if p.isdigit() else (1, 0, p))
    return out

def esc(s): return html.escape(str(s)) if s is not None else ""

def alt(s):
    """Star every ⪤-joined alternant of a proto-form. The *leading* asterisk is supplied by CSS
    (.pf/.pf2/.recon ::before) or a literal '*' prefix (cite/title), so strip any leading '*' the
    data itself carries (only etymon 463 does) to avoid a doubled '**', then add the post-⪤ stars."""
    if not s: return s or ""
    s = re.sub(r'^\s*\*\s*', '', s)        # drop a stray leading star baked into the data
    # \*? consumes an asterisk the data already carries on the alternant, so a meaningful
    # double-star (e.g. **d-k-wiy) isn't bumped to *** by adding another.
    return re.sub(r'⪤\s*\*?', '⪤ *', s)

def iso_link(code):
    """An ISO 639-3 code linked to its Glottolog languoid page (the original's Ethnologue
    show_language.asp links are long dead)."""
    code = (code or "").strip()
    if not code: return ""
    return (f'<a href="https://glottolog.org/resource/languoid/iso/{esc(code)}"'
            f' rel="noopener" target="_blank">{esc(code)}</a>')

def rcount_txt(n):
    """' · 12 reflexes' / ' · 1 reflex' / '' for an etymon's reflex count."""
    if not n: return ''
    return f' · {n:,} ' + ('reflex' if n == 1 else 'reflexes')
