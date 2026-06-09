"""Configuration constants + static-asset versions.

Paths resolve against the repo root (this file lives in render/, one level down).
"""
import os
import hashlib

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA = os.path.join(_ROOT, "data")

# The canonical public base URL used in citations (includes any path prefix, no trailing
# slash). Defaults to the live GitHub Pages URL so copied citations resolve today; override
# with STEDT_CITE_BASE at build time (e.g. "https://stedt.org") once a project domain is wired up.
CITE_BASE = os.environ.get("STEDT_CITE_BASE", "https://larc-iu.github.io/stedt").rstrip("/")

# Show the "preview" banner (the site is an in-progress rebuild). On by default; set
# STEDT_PREVIEW=0 to turn it off once the site is no longer a preview.
PREVIEW = os.environ.get("STEDT_PREVIEW", "1") != "0"

# Proto-language abbreviations (etyma.grpid -> languagegroups.plg) expanded for the etymon header.
PLG_FULL = {
    'PST': 'Proto-Sino-Tibetan', 'PTB': 'Proto-Tibeto-Burman', 'PLB': 'Proto-Lolo-Burmese',
    'PL': 'Proto-Loloish', 'PKC': 'Proto-Kuki-Chin', 'PCC': 'Proto-Central Chin',
    'PNC': 'Proto-Northern Chin', 'PSPC': 'Proto-Southern Plains Chin', 'PPC': 'Proto-Peripheral Chin',
    'PTani': 'Proto-Tani', 'PTk': 'Proto-Tangkhulic', 'PKar': 'Proto-Karenic',
    'PCN': 'Proto-Central Naga (Ao group)', 'PNN': 'Proto-Northern Naga / Konyakian',
    'TGTM': 'Tamang–Gurung–Thakali–Manang', 'PKir': 'Proto-Kiranti', 'PBod': 'Proto-Bodic',
    'PQ': 'Proto-Qiangic', 'PrGy': 'Proto-rGyalrongic', 'PDeng': 'Proto-Deng',
    'PTQ': 'Proto-Tangut–Qiang', 'PBm': 'Proto-Burmish', 'PNungic': 'Proto-Nungic',
    'PAsak': 'Proto-Asakian', 'NEIA': 'NE Indian Areal Group', 'IA': 'Indo-Aryan',
    'CH': 'Sinitic (Chinese)', 'DRV': 'Dravidian',
}

DB = os.path.join(_ROOT, "stedt.sqlite")

# ---------------------------------------------------------------- page shell
# CSS and the universal note-popover JS live in static/ (site.css, site.js) and are linked,
# not inlined, so the stylesheet downloads once and is cached instead of repeated on every
# page. build_static.py copies static/ into the site; the ?v= content hash busts the browser
# cache when (and only when) the file changes.
STATIC = os.path.join(_ROOT, "static")

def _asset_ver(name):
    try:
        with open(os.path.join(STATIC, name), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:8]
    except OSError:
        return "0"

_CSS_VER = _asset_ver("site.css")
_JS_VER = _asset_ver("site.js")
