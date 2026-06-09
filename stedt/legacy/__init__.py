"""The /_legacy/ rootcanal clone — a pixel-faithful static copy of the retired Berkeley site.

render.py mirrors rootcanal's logged-out Template-Toolkit pages; build_site.py prerenders them
and copies the verbatim front-end assets; search_db.py builds the WASM search DB the in-browser
shim (src/legacy-shim.js) queries. Kept apart from the modern site and noindex'd.
"""
