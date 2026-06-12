"""/_dev/parity/ — bare side-by-side viewer: the original interface next to this site.

For showing old STEDT users what views correspond to what. Deliberately NOT a themed
site page: a standalone document (its own minimal styling, no masthead), modeled on the
dev review harness. Left pane is /_legacy/ — the static, working rootcanal clone, so the
exhibit outlives the original server; right pane is the modern view.

TO RETIRE: build with STEDT_DEV_PARITY=0, or delete this module, its template
(dev_parity.html), and the gated write() in stedt/build/static.py. Nothing else
references it (it carries its own styles).
"""

from .templating import env

_DEV_PARITY = env.get_template("dev_parity.html")

# (label, legacy path, modern path, retired live-server path (unused), what to notice)
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


def dev_parity():
    return _DEV_PARITY.render(
        cases=[{"label": l, "legacy": a, "modern": b, "orig": o, "note": n} for l, a, b, o, n in CASES],
    )
