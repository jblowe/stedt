"""Render-invariant checks: structural guarantees over a fixed sample of rendered pages.

Renders a deterministic, edge-biased sample of real pages in-process (no site/ build
needed, just stedt.sqlite) and asserts properties every page must hold regardless of
data vintage. Each check exists because its violation already shipped once, or nearly
did, during the 2026-06 review rounds:

  form-empty     every .form span shows text — the thesaurus ind-0 bug rendered rows
                 whose entire form vanished into an empty syllable
  syl-pop-only   every syllable link has visible text besides its .sylpop preview —
                 a popover-only link is invisible yet focusable
  double-star    no '**' in visible text — star logic re-added a star that was
                 already literal in the data
  anchor         every same-page href="#x" / aria-describedby="x" has its id="x"
  entity-links   every /etymon/N, /language/N, /source/A, /thesaurus/K, /group/G
                 href resolves to a live entity (language links must be canonical —
                 a non-canonical lgid works via redirect but must not be emitted)
  leak           no markup-pipeline internals in visible text ('<unicode>', the
                 U+27E6/U+27E7 note shields)

The sample is fixed by construction (top-N + known edge classes, no RNG), so failures
reproduce. Called by stedt.validate when stedt.sqlite exists; standalone:
python -m stedt.dev.invariants
"""

import html.parser
import re
import sqlite3
import sys

from stedt.paths import DB

LEX_VISIBLE = "coalesce(upper(l.status),'') NOT IN ('HIDE','DELETED')"


class Scanner(html.parser.HTMLParser):
    """One pass over a rendered page, collecting everything the invariants need."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.local_refs = []        # (#fragment, kind) needing a same-page id
        self.entity_hrefs = []      # (kind, key)
        self.forms = []             # text of each .form, popover/gloss/pos excluded
        self.syls = []              # text of each a.syl, .sylpop excluded
        self.text = []              # all visible text
        self._stack = []            # [(tag, classset)]
        self._forms_open = []       # indices into self.forms for open .form spans
        self._syls_open = []        # indices into self.syls for open a.syl

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = set((a.get("class") or "").split())
        self._stack.append((tag, cls))
        if a.get("id"):
            self.ids.add(a["id"])
        if a.get("aria-describedby"):
            self.local_refs.append((a["aria-describedby"], "aria-describedby"))
        href = a.get("href") or ""
        if href.startswith("#") and len(href) > 1:
            self.local_refs.append((href[1:], "href"))
        m = re.match(r"/(etymon|language|source|thesaurus|group)/([^/#?]+)(?:[#?].*)?$", href)
        if m:
            self.entity_hrefs.append((m.group(1), m.group(2)))
        if "form" in cls:
            self._forms_open.append(len(self.forms))
            self.forms.append("")
        if tag == "a" and "syl" in cls:
            self._syls_open.append(len(self.syls))
            self.syls.append("")

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                for t, cls in self._stack[i:]:
                    if "form" in cls and self._forms_open:
                        self._forms_open.pop()
                    if t == "a" and "syl" in cls and self._syls_open:
                        self._syls_open.pop()
                del self._stack[i:]
                return

    def handle_data(self, data):
        self.text.append(data)
        if any({"sylpop", "notepop"} & c for _, c in self._stack):
            return  # popover content is not the row's own text
        in_gp = any({"g", "pos"} & c for _, c in self._stack)
        for i in self._forms_open:
            if not in_gp:  # gloss/POS sit inside .form but aren't form text
                self.forms[i] += data
        for i in self._syls_open:
            self.syls[i] += data


def sample(db):
    """Deterministic, edge-biased page sample. Top-N keeps it stable as data evolves;
    the fixed tags pin known past regressions (syllable links, footnotes, mesoroots)."""
    one = lambda q: [r[0] for r in db.execute(q)]
    tags = set(one(f"""
        SELECT h.tag FROM lx_et_hash h JOIN lexicon l ON l.rn=h.rn
        WHERE {LEX_VISIBLE} GROUP BY h.tag ORDER BY count(*) DESC LIMIT 12"""))
    tags.update(one("""SELECT tag FROM etyma WHERE status != 'DELETE'
        AND coalesce(allofams,'') != '' ORDER BY tag LIMIT 6"""))
    tags.update(one("SELECT DISTINCT tag FROM mesoroots ORDER BY tag LIMIT 6"))
    tags.update(one("""SELECT tag FROM etyma WHERE status != 'DELETE' AND public=0
        ORDER BY tag LIMIT 4"""))
    tags.update(one("""SELECT tag FROM etyma WHERE status != 'DELETE'
        ORDER BY length(coalesce(notes,'')) DESC LIMIT 6"""))
    tags.update({512, 695})  # the sylLink text-loss neighbourhood + a dense polymorphemic etymon
    live = set(one("SELECT tag FROM etyma WHERE status != 'DELETE'"))
    tags &= live

    lgids = one(f"""
        SELECT l.lgid FROM lexicon l WHERE {LEX_VISIBLE}
        GROUP BY l.lgid ORDER BY count(*) DESC LIMIT 8""")
    lgids += one("""SELECT lgid FROM languagenames WHERE language LIKE '"%' LIMIT 2""")
    srcs = one("""SELECT n.srcabbr FROM lexicon l JOIN languagenames n ON n.lgid=l.lgid
        GROUP BY n.srcabbr ORDER BY count(*) DESC LIMIT 5""")
    semks = [k for (k,) in db.execute(
        "SELECT semkey FROM chapters WHERE semkey IN ('1.2.3','1.5.1','2.1.1','8.1') OR length(semkey) > 11 LIMIT 8")]
    grps = one("SELECT grpid FROM languagegroups WHERE plg != '' ORDER BY grpid LIMIT 3")
    return sorted(tags), lgids, srcs, semks, grps


def run(err):
    """Render the sample and report invariant violations through err(msg)."""
    from stedt import render  # deferred: needs stedt.sqlite, validate may run without it

    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    tags, lgids, srcs, semks, grps = sample(db)

    live_tags = {str(t) for (t,) in db.execute("SELECT tag FROM etyma WHERE status != 'DELETE'")}
    all_lgids = {str(g) for (g,) in db.execute("SELECT lgid FROM languagenames")}
    # language links must target the canonical lect page (most visible forms, tie → lowest)
    canon = set()
    by_lect = {}
    for lgid, language, grpid, n in db.execute(f"""
            SELECT ln.lgid, ln.language, ln.grpid, count(l.rn)
            FROM languagenames ln LEFT JOIN lexicon l ON l.lgid=ln.lgid AND {LEX_VISIBLE}
            GROUP BY ln.lgid"""):
        by_lect.setdefault((language, grpid), []).append((lgid, n or 0))
    for lst in by_lect.values():
        canon.add(str(max(lst, key=lambda t: (t[1], -t[0]))[0]))
    all_srcs = {s for (s,) in db.execute("SELECT srcabbr FROM srcbib")}
    all_semks = {k for (k,) in db.execute("SELECT semkey FROM chapters WHERE semkey IS NOT NULL")}
    # the build also emits top-level volume pages ('1.0' → /thesaurus/1); mirror static.py's rule
    all_semks |= {k.split(".")[0] for (k,) in db.execute(
        "SELECT semkey FROM chapters WHERE semkey LIKE '%.0'"
        " AND (length(semkey)-length(replace(semkey,'.','')))=1")}
    all_grps = {str(g) for (g,) in db.execute("SELECT grpid FROM languagegroups")}

    pages = [(f"etymon/{t}", lambda t=t: render.etymon(t)) for t in tags]
    pages += [(f"language/{g}", lambda g=g: render.language(g)) for g in lgids]
    pages += [(f"source/{s}", lambda s=s: render.source(s)) for s in srcs]
    pages += [(f"thesaurus/{k}", lambda k=k: render.thesaurus(k)) for k in semks]
    pages += [(f"group/{g}", lambda g=g: render.group(g)) for g in grps]
    pages += [("thesaurus", lambda: render.thesaurus(None)), ("search", lambda: render.search_page(""))]

    npages = 0
    for path, fn in pages:
        try:
            page = fn()
        except Exception as e:  # a sample page failing to render at all is itself a failure
            err(f"render {path}: raised {type(e).__name__}: {e}")
            continue
        npages += 1
        s = Scanner()
        s.feed(str(page))
        for i, f in enumerate(s.forms):
            if not f.strip():
                err(f"render {path}: .form #{i} has no visible text (popover-only/empty row)")
        for i, t in enumerate(s.syls):
            if not t.strip():
                err(f"render {path}: syllable link #{i} has no visible text outside its popover")
        text = "".join(s.text)
        if "**" in text:
            i = text.find("**")
            err(f"render {path}: '**' in visible text: …{text[max(0, i - 40):i + 10]!r}…")
        for marker, what in (("<unicode", "literal <unicode> tag"), ("⟦", "U+27E6 note shield"), ("⟧", "U+27E7 note shield")):
            if marker in text:
                err(f"render {path}: {what} leaked into visible text")
        for frag, kind in s.local_refs:
            if frag not in s.ids:
                err(f"render {path}: {kind} '#{frag}' has no matching id on the page")
        for kind, key in s.entity_hrefs:
            ok = {
                "etymon": lambda: key in live_tags,
                "language": lambda: key in canon,
                "source": lambda: key in all_srcs,
                "thesaurus": lambda: key in all_semks,
                "group": lambda: key in all_grps,
            }[kind]()
            if not ok:
                detail = "non-canonical lgid (redirect hop)" if kind == "language" and key in all_lgids else "no such entity"
                err(f"render {path}: link /{kind}/{key} — {detail}")
    print(f"  render invariants: {npages} sample pages clean" if npages else "  render invariants: nothing rendered?!")


if __name__ == "__main__":
    bad = []
    run(bad.append)
    for m in bad:
        print("ERROR:", m)
    sys.exit(1 if bad else 0)
