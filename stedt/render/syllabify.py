"""SYNC(syllabify) ↔ web/src/rows.js syllabify/_syl1 — the SAME tokenizer in two runtimes, verified
byte-equal over 40k tagged forms; any change must stay identical (re-run that diff).

Faithful port of the original SylStation.syllabify. Splits a reflex's surface form into syllables +
the delimiters between them, so a
caller can link each syllable to its etymon (lx_et_hash.ind = syllable position). Pure string logic;
no DB, no escaping. Returns (syls, dl, prefix): dl[i] is the delimiter trailing syls[i]; prefix is
any leading delimiter run."""

import re

# Char classes are concatenated into a single [...] just like the JS source; a leading "-" in _DELIM
# keeps it literal, 0-9 / ˥-˩ are ranges, and "()" inside a class are literal parens.
_TONE = "⁰¹²³⁴⁵⁶⁷⁸0-9ˊˋ˥-˩"
_DELIM = "-=≡≣+.,;/~◦⪤()↮ "
_HIDE = re.compile("[(]([^" + _DELIM + _TONE + "]+)[)]")
_START = re.compile("^([" + _DELIM + "]+)")
_REPOST = re.compile("^([^" + _DELIM + _TONE + "]+[" + _TONE + "]+(?:[|]$)?)([" + _DELIM + "]*)")
_REPRE = re.compile("^([" + _TONE + "]{1,2}[^" + _DELIM + _TONE + "]+)([" + _DELIM + "]*)")
_REDEL = re.compile("^([^" + _DELIM + "]+)([" + _DELIM + "]*)")


def _syl1(s, rx):
    # hide parenthesised non-delimiter spans behind fullwidth parens so they don't split, then restore
    s = _HIDE.sub("（\\1）", s)
    prefix = ""
    m0 = _START.match(s)
    if m0:
        prefix = m0.group(1)
        s = s[len(prefix):]
    syls, dl = [], []
    while s:
        m = rx.match(s)
        if not m or not m.group(0):
            break
        s = s[len(m.group(0)):]
        g1 = m.group(1)
        if "|" in g1 and syls:                                  # "|" glues this piece onto the prior syllable
            syls[-1] += dl.pop()
            # JS String.replace('|','') strips only the FIRST "|"; match that, not str.replace's all
            syls[-1] += g1.replace("（", "(").replace("）", ")").replace("|", "", 1)
        else:
            syls.append(g1.replace("（", "(").replace("）", ")"))
        dl.append(m.group(2))
    if not syls:
        syls.append("")
    if s:                                                       # unparsed tail rides on the last syllable
        syls[-1] += s
    return syls, dl, prefix, (len(s) == 0)


def syllabify(s):
    syls, dl, prefix, ok = _syl1(s, _REPOST)
    if not ok:
        syls, dl, prefix, ok = _syl1(s, _REPRE)
        if not ok:
            syls, dl, prefix, _ = _syl1(s, _REDEL)
    return syls, dl, prefix
