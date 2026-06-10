"""Small formatting + URL helpers: HTML escaping, proto-form stars, ISO/citation links."""

import html
import re
import unicodedata


def sortkey(s):
    """SYNC(sortkey) ↔ web/src/search.js sortkey + rows.js norm. Case- and accent-insensitive collation key (close to the MySQL utf8_general_ci order the
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
    Star every joined alternant of a proto-form — the joiners are ⪤, OR, ~ and = (rootcanal
    etymon.tt stars all four; 15 live etyma use OR/~). The *leading* asterisk is supplied as
    literal text by every emission site (<span class="star">*</span>, or a bare '*' in cite/title
    — never CSS content, which selections wouldn't copy), so strip any leading '*' the data
    itself carries (only etymon 463 does) to avoid a doubled '**', then star the alternants."""
    if not s:
        return s or ""
    s = re.sub(r"^\s*\*\s*", "", s)  # drop a stray leading star baked into the data
    # \*? consumes an asterisk the data already carries on the alternant, so a meaningful
    # double-star (e.g. **d-k-wiy) isn't bumped to *** by adding another.
    return re.sub(r"(⪤|\bOR\b|~|=)\s*\*?", r"\1 *", s)


def iso_link(code):
    """An ISO 639-3 code linked to its Glottolog languoid page (the original's Ethnologue
    show_language.asp links are long dead)."""
    code = (code or "").strip()
    if not code:
        return ""
    # convention: external links open in the same tab, like every other link on the site
    return f'<a href="https://glottolog.org/resource/languoid/iso/{esc(code)}">{esc(code)}</a>'


def rfx_noun(n):
    """'reflex' / 'reflexes' — every count label shares it so '1 reflexes' can't recur."""
    return "reflex" if n == 1 else "reflexes"


def plural(n, noun):
    """The s-pluralizing sibling of rfx_noun: 'language' / 'languages' by count. Every count label
    goes through one of the two, so '1 languages' can't recur either."""
    return noun if n == 1 else noun + "s"


def cite_tail(url):
    """Shared terminal of every copy-citation: URL + access-date blank + period — one helper so the
    etymon and source citeboxes can't disagree on punctuation."""
    return f"{url} (accessed [ACCESSED])."


def rcount_txt(n):
    """' · 12 reflexes' / ' · 1 reflex' / '' for an etymon's reflex count."""
    if not n:
        return ""
    return f" · {n:,} {rfx_noun(n)}"
