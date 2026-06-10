"""Read-only SQLite connection + cached cross-page lookups (loaded once per process)."""

import sqlite3

from .config import DB
from .text import sortkey


def _unaccent(a, b):
    ka, kb = sortkey(a), sortkey(b)
    return -1 if ka < kb else (1 if ka > kb else 0)


def con():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    # ORDER BY … COLLATE unaccent = case/accent-insensitive listings (see text.sortkey)
    conn.create_collation("unaccent", _unaccent)
    return conn


# --- the visibility/filing vocabulary: every query spells these rules ONE way ---------------
# DELETE-status etyma have no built pages and appear nowhere (alias the table as `e`).
ETY_LIVE = "coalesce(upper(e.status),'')!='DELETE'"

# Legacy files an etymon under its (more specific) `chapter`; `semkey` is only a fallback for
# the lone live etymon whose chapter doesn't resolve. Used for thesaurus placement + counts.
ECAT = "coalesce(nullif(e.chapter,''),e.semkey)"

# The original site never shows HIDE/DELETED lexicon rows (placeholder '*' forms and withdrawn
# records — ~10k rows). Every lexicon read (render queries AND the search-DB build) must apply
# this, with the table aliased as `l`, or listings and counts disagree with the data the site
# stands behind. Other statuses (D0/D1/…) stay visible, matching the original.
LEX_VISIBLE = "coalesce(upper(l.status),'') NOT IN ('HIDE','DELETED')"


_VALID_TAGS = None
_SEMKEY_COUNTS = None
_XREF_LABELS = None


def valid_etymon_tags():
    """Cached frozenset of etymon tags that have a built page (non-DELETE). Used to gate
    xref links so notes never point at an unbuilt (404) etymon. Loaded once per process."""
    global _VALID_TAGS
    if _VALID_TAGS is None:
        conn = con()
        _VALID_TAGS = frozenset(
            r[0] for r in conn.execute(f"SELECT tag FROM etyma e WHERE {ETY_LIVE}")
        )
        conn.close()
    return _VALID_TAGS


def xref_labels():
    """Cached {tag: (plg, protoform, protogloss)} for non-DELETE etyma, so note cross-references
    can be annotated inline (e.g. '#206 PTB *(k/g)um BACK / BODY' instead of a bare '#206').
    Loaded once per process; render_note() takes no connection, so it must self-fetch."""
    global _XREF_LABELS
    if _XREF_LABELS is None:
        conn = con()
        _XREF_LABELS = {
            r[0]: (r[1], r[2], r[3])
            for r in conn.execute(
                "SELECT e.tag, g.plg, e.protoform, e.protogloss FROM etyma e "
                "LEFT JOIN languagegroups g ON g.grpid=e.grpid "
                f"WHERE {ETY_LIVE}"
            )
        }
        conn.close()
    return _XREF_LABELS


def reflex_semkey_counts():
    """Cached {lexicon.semkey: reflex count}. Each reflex carries its own gloss-level semkey
    (independent of any etymon); this powers the 'Attested forms here' count on thesaurus
    pages. One GROUP BY pass, loaded once per process."""
    global _SEMKEY_COUNTS
    if _SEMKEY_COUNTS is None:
        conn = con()
        # Exclude proto-language stand-ins (language LIKE '*%') — those are reconstructions, not
        # attested forms (they surface as etyma under "Reconstructions here"), and the languages
        # index hides them too. Must match the client query's filter so count == list length.
        _SEMKEY_COUNTS = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT l.semkey, count(*) FROM lexicon l JOIN languagenames ln ON ln.lgid=l.lgid "
                f"WHERE coalesce(l.semkey,'')!='' AND ln.language NOT LIKE '*%' AND {LEX_VISIBLE} "
                "GROUP BY l.semkey"
            )
        }
        conn.close()
    return _SEMKEY_COUNTS
