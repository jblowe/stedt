"""Small formatting + URL helpers: HTML escaping, proto-form stars, ISO/citation links."""

import html
import re
import unicodedata


def sortkey(s):
    """Case- and accent-insensitive collation key (close to the MySQL utf8_general_ci order the
    original sorted with — binary order exiled 'van Breugel' past 'Zhao' and 'kûi' past 'kuiy'):
    NFD, strip combining marks, casefold. Shared by the SQL 'unaccent' collation (db.con) and
    every Python-side listing sort, so the two can't order differently."""
    s = unicodedata.normalize("NFD", s or "")
    return "".join(ch for ch in s if not unicodedata.combining(ch)).casefold()


def natkey(s):
    out = []
    for p in (s or "").split("."):
        out.append((0, int(p), "") if p.isdigit() else (1, 0, p))
    return out


def esc(s):
    return html.escape(str(s)) if s is not None else ""


def alt(s):
    """SYNC(protoform-fmt) ↔ web/src/rows.js altstar() — same normalisation in both runtimes, keep identical.
    Star every ⪤-joined alternant of a proto-form. The *leading* asterisk is supplied by CSS
    (.pf/.pf2/.recon ::before) or a literal '*' prefix (cite/title), so strip any leading '*' the
    data itself carries (only etymon 463 does) to avoid a doubled '**', then add the post-⪤ stars."""
    if not s:
        return s or ""
    s = re.sub(r"^\s*\*\s*", "", s)  # drop a stray leading star baked into the data
    # \*? consumes an asterisk the data already carries on the alternant, so a meaningful
    # double-star (e.g. **d-k-wiy) isn't bumped to *** by adding another.
    return re.sub(r"⪤\s*\*?", "⪤ *", s)


def iso_link(code):
    """An ISO 639-3 code linked to its Glottolog languoid page (the original's Ethnologue
    show_language.asp links are long dead)."""
    code = (code or "").strip()
    if not code:
        return ""
    return (
        f'<a href="https://glottolog.org/resource/languoid/iso/{esc(code)}"'
        f' rel="noopener" target="_blank">{esc(code)}</a>'
    )


def rfx_noun(n):
    """'reflex' / 'reflexes' — every count label shares it so '1 reflexes' can't recur."""
    return "reflex" if n == 1 else "reflexes"


def rcount_txt(n):
    """' · 12 reflexes' / ' · 1 reflex' / '' for an etymon's reflex count."""
    if not n:
        return ""
    return f" · {n:,} {rfx_noun(n)}"
