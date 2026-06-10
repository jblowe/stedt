"""Content hash for cache-busting a derived DB (search.sqlite3 / legacy.sqlite3).

The client (web/src/search.js, legacy shim) fetches the DB once per ?v= key and NEVER revalidates
a cache hit, so the key must change whenever the DB's BYTES can change — and those bytes are a
function of data/ plus the code that bakes content into the DB: the builder itself and the
render_note() pipeline (note HTML — xref hrefs, escaping, visibility predicates — is stored
pre-rendered in both DBs). Hashing this dependency closure rather than the 40+ MB artifact avoids
cache churn from run-to-run nondeterminism while still busting on any real content change.
Paths are relativized to the repo root so the hash is location-stable.
"""

import glob
import hashlib
import os

from stedt.paths import DATA, ROOT

# render_note()'s import closure: notes.py and what it draws on (db: valid tags/xref labels +
# LEX_VISIBLE; shell: etymon_href baked into xref links; text: esc/alt). A change to any of these
# changes stored note HTML / row filtering in BOTH derived DBs.
_RENDER_DEPS = ("notes.py", "db.py", "shell.py", "text.py")


def data_version(builder_file):
    """16-hex content key: data/** + the given builder file + the shared render dependencies."""
    render_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "render")
    h = hashlib.sha256()
    paths = sorted(glob.glob(os.path.join(DATA, "**", "*"), recursive=True))
    paths.append(builder_file)
    paths += [os.path.join(render_dir, f) for f in _RENDER_DEPS]
    for p in paths:
        if os.path.isfile(p):
            h.update(os.path.relpath(p, ROOT).encode("utf-8"))
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
    return h.hexdigest()[:16]
