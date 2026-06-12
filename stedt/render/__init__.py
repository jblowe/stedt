"""STEDT page renderer — the build-time library that turns the compiled stedt.sqlite into
static HTML. No server: the deployed site is static files; search runs client-side (WASM
SQLite over search.sqlite3).

Split into focused modules (config, db, text, notes, shell, rows, the per-entity pages
etymon/language/source/group, indexes); this package re-exports their public names, so
callers do ``from stedt import render`` then ``render.<fn>``.
"""

from .config import *  # noqa: F401,F403
from .db import *  # noqa: F401,F403
from .text import *  # noqa: F401,F403
from .notes import *  # noqa: F401,F403
from .shell import *  # noqa: F401,F403
from .rows import *  # noqa: F401,F403
from .etymon import *  # noqa: F401,F403
from .language import *  # noqa: F401,F403
from .source import *  # noqa: F401,F403
from .group import *  # noqa: F401,F403
from .indexes import *  # noqa: F401,F403
from .devpages import *  # noqa: F401,F403
