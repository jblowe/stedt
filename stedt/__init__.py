"""Build tooling and page renderer for the STEDT static site.

Subpackages: ``render`` (the HTML page library), ``build`` (data/ → stedt.sqlite →
site/), ``legacy`` (the buried /_legacy/ rootcanal clone), ``dev`` (snapshot, export,
and dump-import helpers). The ``stedt`` console command (``stedt.cli``) drives them all.
"""

__version__ = "0.1.0"
