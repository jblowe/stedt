"""/_dev/parity/ — the "where did everything go?" exhibit for readers of the original STEDT.

A correspondence table (every view of the original database UI → where it lives in the
remake, with what changed) plus a side-by-side viewer: the /_legacy/ mirror on the left —
our pixel-faithful, fully static rootcanal clone, so the exhibit outlives the original
server — and the modern view on the right. Each case also links the live original while
it survives.

TO RETIRE THE EXHIBIT: build with STEDT_DEV_PARITY=0, or delete this module, its
template (dev_parity.html), the `.pv-` CSS block in site.css, and the gated write()
in stedt/build/static.py. Nothing else references it.
"""

from markupsafe import Markup

from .shell import page
from .templating import env

_DEV_PARITY = env.get_template("dev_parity.html")

# (label, legacy path, modern path, original path on the live server, what to notice)
CASES = [
    ("Front page", "/_legacy/", "/",
     "/", "The splash's gloss + language boxes became one box; the same examples are runnable beneath it."),
    ("Search", "/_legacy/gnis?t=dog", "/search?q=dog",
     "/gnis?t=dog", "The two-pane etyma/lexicon combo became one federated page: Languages, Reconstructions, Reflexes."),
    ("An etymon", "/_legacy/etymon/34", "/etymon/34",
     "/etymon/34", "Same table, same leading 0.x bands. The yellow cognate highlight is now the bold syllable; dotted syllables link out."),
    ("Etymon popups", "/_legacy/etymon/512", "/etymon/512",
     "/etymon/512", "Hover a dotted syllable on the right: the old elink popup's card — header, mesoroots, allofams — every line clickable."),
    ("Chapter browser", "/_legacy/chapters", "/thesaurus",
     "/chapters", "The browser is one tree with a volumes TOC; every node is a page."),
    ("A chapter", "/_legacy/chap/1.2.3", "/thesaurus/1.2.3",
     "/chap/1.2.3", "Sequence labels read 1.2 rather than 1b; counts are shown per node."),
    ("Group browser", "/_legacy/group/2", "/group/2",
     "/group/2", "A group is a page now: its tree, subgroups, languages, and — new — the reconstructions of its proto-language."),
    ("A language", "/_legacy/group/74/1079", "/language/1079",
     "/gnis?lexicon.lgid=1079", "The original had no language page — selecting a language ran a search. Now a lect is one page across all its sources, filterable per source."),
    ("Source bibliography", "/_legacy/source", "/sources",
     "/source", "Same bibliography; sortable, with reference-only sources split out."),
    ("A source", "/_legacy/source/STC", "/source/STC",
     "/source/STC", "Reconstructions lead, as the *-names did in the original's table; languages link to their pages."),
]

# the correspondence table: original affordance -> where it lives now (one row per thing
# an old user might look for; claims follow the audited parity catalog)
TABLE = [
    ("Splash search (gloss + language boxes)",
     '<a href="/">the home page</a>',
     'One box; <code>gloss:</code> / <code>language:</code> fields replace the separate inputs, with runnable examples beneath.'),
    ("gnis results (etyma + lexicon panes, Rotate View)",
     '<a href="/search?q=dog">/search</a>',
     "One federated results page; the sort control replaces column-header sorting."),
    ("Language autosuggest (with =exact chips)",
     '<a href="/">the home box</a>',
     "Suggestions appear as you type on the home page; on /search, use <code>language:</code>."),
    ("Comma alternatives (<i>frog, snail</i>)",
     '<a href="/search?q=frog%2C%20snail">unchanged</a>',
     "The documented idiom works as before, plus quoted alternatives inside a field."),
    ("Etymon page (reflex table, analyses, footnote marks)",
     '<a href="/etymon/34">/etymon/{tag}</a>',
     "Previously-published reconstructions still lead the table. Yellow highlight → bold self-syllable; superscript tags → dotted syllable links; subgroup footnotes sit under their band header."),
    ("Etymon hover popup (mesoroots / allofams)",
     "hover any dotted syllable",
     "The card shows the etymon's headline, mesoroots, and allofam family — every line is a link now."),
    ("Chapter Browser",
     '<a href="/thesaurus">/thesaurus</a>',
     "The full tree on one page with a volumes TOC; each chapter is a page with its reconstructions and directly-filed forms."),
    ("Language Groups Browser",
     '<a href="/group/2">/group/{id}</a>',
     "Each group is a page: family tree, subgroups, languages, and its proto-language's reconstructions."),
    ("Selecting a language (its records by source)",
     '<a href="/language/1079">/language/{id}</a>',
     "A language is one page aggregating all its sources — use the <i>source</i> picker to view just one, as the old per-source rows did."),
    ("Source Bibliography",
     '<a href="/sources">/sources</a>',
     "Sortable by author, reflex count, or language count; per-source pages carry a copy-ready citation."),
    ("num. of records links",
     "row counts everywhere",
     'Counts appear on rows and headers; <code>tag:695</code> searches the records of an etymon directly.'),
    ("Phon. Inventory column / language statistics page",
     "not carried over",
     "Neither survived the move (the inventories PDF and the stats page); the data behind them is unchanged."),
    ("All Tools (guest table searches)",
     '<a href="/search">fielded search</a>',
     'The common queries live in search fields (<code>form:</code>, <code>pos:</code>, <code>source:</code>, <code>subgroup:</code>…); the specialist table UIs were not ported.'),
    ("Everything, exactly as it was",
     '<a href="/_legacy/">/_legacy/</a>',
     "A faithful working copy of the original interface — same markup, same JS, search included — built from the same data."),
]


def dev_parity():
    body = _DEV_PARITY.render(
        cases=[{"label": l, "legacy": a, "modern": b, "orig": o, "note": n} for l, a, b, o, n in CASES],
        table=[{"was": Markup(w), "now": Markup(n), "note": Markup(t)} for w, n, t in TABLE],
    )
    return page("The original STEDT and this site, side by side", body,
                desc="Where every view of the original STEDT database lives in this site, side by side.")
