"""STEDT page renderer — build-time library of render functions, imported by build_static.py
(and build_legacy.py / legacy_render.py) to prerender every page to static HTML. No server:
the deployed site is static files on GitHub Pages; search runs client-side (WASM SQLite over
search.sqlite3). Reads the compiled stedt.sqlite.

Split into focused modules; this package re-exports their public names so the historical
`import render; render.<fn>` API is unchanged for all callers.
"""
from .config import *    # noqa: F401,F403
from .db import *        # noqa: F401,F403
from .text import *      # noqa: F401,F403
from .notes import *     # noqa: F401,F403
from .shell import *     # noqa: F401,F403
from .entities import *  # noqa: F401,F403
from .indexes import *   # noqa: F401,F403
