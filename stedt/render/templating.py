"""Shared Jinja2 environment for the page templates (render/templates/).

Autoescape is on, so `{{ value }}` escapes by default. HTML-producing helpers (render_note,
already-rendered page bodies, etc.) are passed as markupsafe.Markup so they are emitted verbatim
instead of double-escaped. Block tags are kept whitespace-verbatim (no trim/lstrip) so a template
can reproduce hand-written markup exactly.
"""

import os

from jinja2 import Environment, FileSystemLoader

_TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

env = Environment(
    loader=FileSystemLoader(_TEMPLATES, encoding="utf-8"),
    autoescape=True,
    trim_blocks=False,
    lstrip_blocks=False,
    keep_trailing_newline=False,
)
