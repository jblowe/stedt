"""The ``stedt`` command — a workflow-grouped dispatcher over the build/ingest/dev modules.

Commands are grouped by the job they belong to: ``ingest`` (a MySQL dump → the data/ TSVs),
``build`` (data/ → the deployable site/, with npm wrapped), and ``dev`` (the snapshot harness),
plus top-level ``validate``, ``serve``, and ``setup``. A bare group command runs that whole chunk —
``stedt build`` builds the entire site, ``stedt ingest`` re-derives data/ from the dump.

Each step runs its module in a fresh process (``python -m stedt.…``) so the modules' import-time
argv/env reads are preserved and every module stays runnable on its own; the JS steps shell out to
the web/ npm project so a contributor never types an npm command.
"""

import os
import subprocess
import sys

import typer

from stedt.paths import SITE, WEB

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Build tooling for the STEDT static site.")
ingest_app = typer.Typer(no_args_is_help=False, help="Ingest a MySQL dump into the data/ TSVs.")
build_app = typer.Typer(no_args_is_help=False, help="Build the deployable site from data/.")
dev_app = typer.Typer(no_args_is_help=True, help="Developer tooling.")
snapshot_app = typer.Typer(no_args_is_help=True, help="Golden-output harness for verifying refactors.")
dev_app.add_typer(snapshot_app, name="snapshot")
app.add_typer(ingest_app, name="ingest")
app.add_typer(build_app, name="build")
app.add_typer(dev_app, name="dev")


def _run(module, *args, env=None):
    """Run a module with ``python -m``; abort (exit nonzero) only if it fails, else return."""
    full_env = {**os.environ, **(env or {})}
    code = subprocess.run([sys.executable, "-m", module, *args], env=full_env).returncode
    if code != 0:
        raise typer.Exit(code)


def _npm(*args):
    """Run an npm command in the web/ project; abort if it fails."""
    code = subprocess.run(["npm", "--prefix", WEB, *args]).returncode
    if code != 0:
        raise typer.Exit(code)


def _site_env(base, out, limit):
    """Map the shared render options to the STEDT_* env vars the build modules read."""
    env = {}
    if base is not None:
        env["STEDT_BASE"] = base
    if out is not None:
        env["STEDT_OUT"] = out
    if limit:
        env["STEDT_LIMIT"] = str(limit)
    return env


def _bundle():
    _npm("run", "build:search")  # the search data layer
    _npm("run", "build:pages")  # the per-page scripts


def _legacy(base=None, out=None, limit=0):
    env = _site_env(base, out, limit)
    _run("stedt.legacy.search_db")
    _run("stedt.legacy.build_site", env=env)
    _npm("run", "build:legacy")


def _full_build(env=None):
    """The whole site pipeline: data/ → stedt.sqlite → search DB → HTML → JS bundles → /_legacy/."""
    env = env or {}
    _run("stedt.build.from_tsv")
    _run("stedt.build.search_db")
    _run("stedt.build.static", env=env)
    _bundle()
    _legacy(base=env.get("STEDT_BASE"))


# ───────────────────────────── ingest: dump → data/ TSVs ─────────────────────────────
@ingest_app.callback(invoke_without_command=True)
def ingest(ctx: typer.Context):
    """MySQL dump → data/ TSVs. With no subcommand: import-dump then export (the default dump)."""
    if ctx.invoked_subcommand is None:
        _run("stedt.dev.build_db")
        _run("stedt.dev.export_tsv")


@ingest_app.command("import-dump")
def ingest_import_dump(dump: str = typer.Argument(None, help="Path to the MySQL dump (default stedtdb_v1.0/…).")):
    """Build stedt.sqlite from the original MySQL dump."""
    _run("stedt.dev.build_db", *([dump] if dump else []))


@ingest_app.command("export")
def ingest_export(dest: str = typer.Argument(None, help="Destination directory (default data/).")):
    """Export stedt.sqlite back to the all-TSV source in data/."""
    _run("stedt.dev.export_tsv", *([dest] if dest else []))


@ingest_app.command("export-dump")
def ingest_export_dump(
    dest: str = typer.Argument(None, help="Output .sql path (default stedt_export.sql)."),
    ddl_from: str = typer.Option(None, help="Reference dump supplying the verbatim DDL."),
):
    """Export stedt.sqlite back to MySQL dump format (the inverse of import-dump) —
    for a post-revival public dump release or feeding the original rootcanal stack."""
    args = ([dest] if dest else []) + (["--ddl-from", ddl_from] if ddl_from else [])
    _run("stedt.dev.export_dump", *args)


@ingest_app.command("roundtrip")
def ingest_roundtrip(
    baseline: str = typer.Argument(..., help="Baseline sqlite."),
    rebuilt: str = typer.Argument(..., help="Rebuilt sqlite."),
):
    """Assert two sqlite DBs are semantically identical (the lossless round-trip gate)."""
    _run("stedt.dev.gate_roundtrip", baseline, rebuilt)


# ───────────────────────────── build: data/ → site/ ─────────────────────────────
@build_app.callback(invoke_without_command=True)
def build(ctx: typer.Context):
    """data/ → the full deployable site/. With no subcommand: run every step in order."""
    if ctx.invoked_subcommand is None:
        _full_build()


@build_app.command("db")
def build_db():
    """Compile data/ into stedt.sqlite (the canonical DB)."""
    _run("stedt.build.from_tsv")


@build_app.command("search-db")
def build_search_db():
    """Build the lean WASM search index (search.sqlite3) from stedt.sqlite."""
    _run("stedt.build.search_db")


@build_app.command("render")
def build_render(
    base: str = typer.Option(None, help="URL subpath prefix (STEDT_BASE; '' for an apex domain)."),
    out: str = typer.Option(None, help="Output directory (STEDT_OUT; default site/)."),
    limit: int = typer.Option(0, help="Cap entities per kind for a quick local build."),
):
    """Prerender the static HTML into site/."""
    _run("stedt.build.static", env=_site_env(base, out, limit))


@build_app.command("bundle")
def build_bundle():
    """Bundle the client JS (search data layer + page scripts) into site/assets/."""
    _bundle()


@build_app.command("legacy")
def build_legacy(
    base: str = typer.Option(None, help="URL subpath prefix (STEDT_BASE)."),
    out: str = typer.Option(None, help="Output directory (STEDT_OUT; default site/)."),
    limit: int = typer.Option(0, help="Cap etyma pages for a quick local build."),
):
    """Build the /_legacy/ rootcanal clone (search DB + pages + shim) into site/_legacy/."""
    _legacy(base, out, limit)


# ───────────────────────────── top-level ─────────────────────────────
@app.command()
def validate():
    """Check data/ for referential integrity (non-zero exit on errors)."""
    _run("stedt.validate")


@app.command()
def serve(
    port: int = typer.Option(8000, help="Port for the local preview server."),
    no_build: bool = typer.Option(False, "--no-build", help="Serve the existing site/ without rebuilding."),
):
    """Build the site root-relative (base='') and serve it locally for preview."""
    if not no_build:
        _full_build({"STEDT_BASE": ""})
    typer.echo(f"Serving {SITE} at http://localhost:{port}  (Ctrl-C to stop)")
    subprocess.run([sys.executable, "-m", "http.server", str(port), "--directory", SITE])


@app.command()
def setup():
    """Install the JS build dependencies (npm ci in web/)."""
    _npm("ci")
    typer.echo("JS deps installed. Python deps come from `pip install .` (or `-e .[dev]` for development).")


# ───────────────────────────── dev ─────────────────────────────
@dev_app.command("parity")
def dev_parity():
    """Diff the modern pages against the /_legacy/ mirror (the rendering oracle);
    non-zero exit on any divergence outside the documented whitelist."""
    _run("stedt.dev.parity")


@dev_app.command("search-battery")
def dev_search_battery():
    """Assert the documented search idioms (token match, comma-OR, field filters,
    CJK fallback, subgroup subtrees) over the built search.sqlite3."""
    _run("stedt.dev.search_battery")


@snapshot_app.command("build")
def snapshot_build(
    directory: str = typer.Argument(..., help="Snapshot output directory."),
    limit: int = typer.Option(0, help="Cap entities per kind (fast smoke run)."),
    no_legacy: bool = typer.Option(False, "--no-legacy", help="Skip the /_legacy/ clone."),
    rebuild_db: bool = typer.Option(False, "--rebuild-db", help="Rebuild stedt.sqlite + search DBs first."),
):
    """Render a byte-snapshot of the site into DIR."""
    args = [directory]
    if limit:
        args += ["--limit", str(limit)]
    if no_legacy:
        args += ["--no-legacy"]
    if rebuild_db:
        args += ["--rebuild-db"]
    _run("stedt.dev.snapshot", "build", *args)


@snapshot_app.command("compare")
def snapshot_compare(
    before: str = typer.Argument(..., help="Baseline snapshot directory."),
    after: str = typer.Argument(..., help="Snapshot to compare against the baseline."),
    max_list: int = typer.Option(40, help="Max paths to list per category."),
):
    """Diff two snapshot manifests; non-zero exit if they differ."""
    _run("stedt.dev.snapshot", "compare", before, after, "--max-list", str(max_list))


if __name__ == "__main__":
    app()
