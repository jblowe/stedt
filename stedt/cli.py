"""The ``stedt`` command — a workflow-grouped dispatcher over the build/dump/dev modules.

Commands are grouped by the job they belong to: ``build`` (data/ → the deployable site/, with npm
wrapped), ``dump`` (two-way interchange with the legacy MySQL ``.sql`` dump), and ``check`` (the
verification harness), plus top-level ``validate``, ``serve``, ``new-source``, and ``setup``. A bare
group command runs that whole chunk where there's an obvious default — ``stedt build`` builds the
entire site.

Each step runs its module in a fresh process (``python -m stedt.…``) so the modules' import-time
argv/env reads are preserved and every module stays runnable on its own; the JS steps shell out to
the web/ npm project so a contributor never types an npm command.
"""

import os
import subprocess
import sys

import typer

from stedt.new_source import HELP as NEW_SOURCE_HELP
from stedt.paths import SITE, WEB

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Build tooling for the STEDT static site.")
build_app = typer.Typer(no_args_is_help=False, help="Build the deployable site from data/.")
dump_app = typer.Typer(no_args_is_help=True, help="Interchange with the legacy MySQL .sql dump (import/export).")
check_app = typer.Typer(no_args_is_help=True, help="Verify the build: parity, search, snapshots, round-trip.")
snapshot_app = typer.Typer(no_args_is_help=True, help="Golden-output harness for verifying refactors.")
check_app.add_typer(snapshot_app, name="snapshot")
app.add_typer(build_app, name="build")
app.add_typer(dump_app, name="dump")
app.add_typer(check_app, name="check")


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


# ───────────────────────────── dump: MySQL .sql ⇄ data/ ─────────────────────────────
@dump_app.command("import")
def dump_import(dump: str = typer.Argument(None, help="Path to the MySQL dump (default stedtdb_v1.0/…).")):
    """Import a MySQL dump into data/: dump → stedt.sqlite → the all-TSV source in data/.
    Rarely needed — data/ is the source of truth; this re-derives it from an archived dump."""
    _run("stedt.dev.build_db", *([dump] if dump else []))
    _run("stedt.dev.export_tsv")


@dump_app.command("export")
def dump_export(
    dest: str = typer.Argument(None, help="Output .sql path (default stedt_export.sql)."),
    ddl_from: str = typer.Option(None, help="Reference dump supplying the verbatim DDL."),
):
    """Export data/ to a MySQL dump (the inverse of import): data/ → stedt.sqlite → .sql —
    for a public dump release or feeding the original rootcanal stack. Compiles stedt.sqlite from
    data/ first, so it works from a clean checkout."""
    _run("stedt.build.from_tsv")
    args = ([dest] if dest else []) + (["--ddl-from", ddl_from] if ddl_from else [])
    _run("stedt.dev.export_dump", *args)


# ───────────────────────────── top-level ─────────────────────────────
@app.command("new-source", help=NEW_SOURCE_HELP, short_help="Onboard a new source from a contributor wordlist.")
def new_source(
    wordlist: str = typer.Argument(None, help="Contributor wordlist (.tsv/.csv/.xlsx)."),
    template: bool = typer.Option(False, "--template", help="Write the contributor template files and exit."),
    out: str = typer.Option(".", help="Directory for --template output."),
    srcabbr: str = typer.Option(None, help="Source abbreviation (folder name); prompted if omitted."),
    citation: str = typer.Option(None, help="Short citation (e.g. 'Abbi 85'); prompted if omitted."),
    author: str = typer.Option(None, help="Author(s); prompted if omitted."),
    year: str = typer.Option(None, help="Year; prompted if omitted."),
    title: str = typer.Option(None, help="Title; prompted if omitted."),
    imprint: str = typer.Option(None, help="Imprint (publisher/journal); prompted if omitted."),
    language: str = typer.Option(None, help="Language of the whole list (when it has no language column)."),
    grpid: str = typer.Option(None, help="Subgroup id for any language entry this run creates."),
    force: bool = typer.Option(False, "--force", help="Regenerate an existing source folder without asking."),
    no_validate: bool = typer.Option(False, "--no-validate", help="Skip the validate run at the end."),
):
    args = ["--template", "--out", out] if template else []
    if wordlist:
        args.append(wordlist)
    opts = [
        ("--srcabbr", srcabbr),
        ("--citation", citation),
        ("--author", author),
        ("--year", year),
        ("--title", title),
        ("--imprint", imprint),
        ("--language", language),
        ("--grpid", grpid),
    ]
    for flag, val in opts:
        if val is not None:
            args += [flag, val]
    if force:
        args.append("--force")
    if no_validate:
        args.append("--no-validate")
    _run("stedt.new_source", *args)


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


# ───────────────────────────── check: verification harness ─────────────────────────────
@check_app.command("parity")
def check_parity():
    """Diff the modern pages against the /_legacy/ mirror (the rendering oracle);
    non-zero exit on any divergence outside the documented whitelist."""
    _run("stedt.dev.parity")


@check_app.command("search")
def check_search():
    """Assert the documented search idioms (token match, comma-OR, field filters,
    CJK fallback, subgroup subtrees) over the built search.sqlite3."""
    _run("stedt.dev.search_battery")


@check_app.command("roundtrip")
def check_roundtrip(
    baseline: str = typer.Argument(..., help="Baseline sqlite."),
    rebuilt: str = typer.Argument(..., help="Rebuilt sqlite."),
):
    """Assert two sqlite DBs are semantically identical (the lossless round-trip gate)."""
    _run("stedt.dev.gate_roundtrip", baseline, rebuilt)


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
