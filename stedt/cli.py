"""The ``stedt`` command — a thin dispatcher over the build/dev modules.

Each subcommand runs its module in a fresh process (``python -m stedt.…``) and exits with
its return code. That isolation is deliberate: the modules read sys.argv/env at import time
(the legacy renderer even needs its base set *before* it is imported), so a subprocess
reproduces their behavior exactly and keeps every module runnable on its own.
"""

import os
import subprocess
import sys

import typer

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Build tooling for the STEDT static site.")
legacy_app = typer.Typer(no_args_is_help=True, help="Build the /_legacy/ rootcanal clone.")
snapshot_app = typer.Typer(no_args_is_help=True, help="Golden-output harness for verifying refactors.")
app.add_typer(legacy_app, name="legacy")
app.add_typer(snapshot_app, name="snapshot")


def _run(module, *args, env=None):
    """Run a module with ``python -m`` and exit with its return code."""
    full_env = {**os.environ, **(env or {})}
    code = subprocess.run([sys.executable, "-m", module, *args], env=full_env).returncode
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


@app.command()
def build():
    """Compile data/ into stedt.sqlite (the canonical DB)."""
    _run("stedt.build.from_tsv")


@app.command(name="search-db")
def search_db():
    """Build the lean WASM search index (search.sqlite3) from stedt.sqlite."""
    _run("stedt.build.search_db")


@app.command()
def render(
    base: str = typer.Option(None, help="URL subpath prefix (STEDT_BASE; '' for an apex domain)."),
    out: str = typer.Option(None, help="Output directory (STEDT_OUT; default site/)."),
    limit: int = typer.Option(0, help="Cap entities per kind for a quick local build."),
):
    """Prerender the static site into site/."""
    _run("stedt.build.static", env=_site_env(base, out, limit))


@app.command()
def validate():
    """Check data/ for referential integrity (non-zero exit on errors)."""
    _run("stedt.validate")


@app.command()
def export(dest: str = typer.Argument(None, help="Destination directory (default data/).")):
    """Export stedt.sqlite back to the all-TSV source in data/."""
    _run("stedt.dev.export_tsv", *([dest] if dest else []))


@app.command(name="import-dump")
def import_dump(dump: str = typer.Argument(None, help="Path to the MySQL dump (default stedtdb_v1.0/…).")):
    """One-time: build stedt.sqlite from the original MySQL dump."""
    _run("stedt.dev.build_db", *([dump] if dump else []))


@app.command()
def roundtrip(
    baseline: str = typer.Argument(..., help="Baseline sqlite."),
    rebuilt: str = typer.Argument(..., help="Rebuilt sqlite."),
):
    """Assert two sqlite DBs are semantically identical (the TSV round-trip gate)."""
    _run("stedt.dev.gate_roundtrip", baseline, rebuilt)


@legacy_app.command(name="search-db")
def legacy_search_db():
    """Build legacy.sqlite3 (the rootcanal WASM search DB)."""
    _run("stedt.legacy.search_db")


@legacy_app.command(name="render")
def legacy_render(
    base: str = typer.Option(None, help="URL subpath prefix (STEDT_BASE)."),
    out: str = typer.Option(None, help="Output directory (STEDT_OUT; default site/)."),
    limit: int = typer.Option(0, help="Cap etyma pages for a quick local build."),
):
    """Prerender the /_legacy/ clone into site/_legacy/ (run after `stedt render`)."""
    _run("stedt.legacy.build_site", env=_site_env(base, out, limit))


@snapshot_app.command(name="build")
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


@snapshot_app.command(name="compare")
def snapshot_compare(
    before: str = typer.Argument(..., help="Baseline snapshot directory."),
    after: str = typer.Argument(..., help="Snapshot to compare against the baseline."),
    max_list: int = typer.Option(40, help="Max paths to list per category."),
):
    """Diff two snapshot manifests; non-zero exit if they differ."""
    _run("stedt.dev.snapshot", "compare", before, after, "--max-list", str(max_list))


if __name__ == "__main__":
    app()
