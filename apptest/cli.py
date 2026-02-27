"""CLI entry point for apptest."""

from pathlib import Path

import click

from .analyzer.context_builder import build_context, write_analysis
from .analyzer.diff_parser import parse_diff
from .analyzer.manifest_parser import parse_manifest
from .analyzer.screen_mapper import map_changed_files
from .config import load_config


@click.group()
def main():
    """AppTest — AI-powered test generation from PR diffs."""
    pass


@main.command()
@click.option(
    "--diff",
    "diff_ref",
    default="HEAD~1..HEAD",
    help="Git diff reference (e.g. HEAD~1..HEAD or a commit range).",
)
@click.option(
    "--repo",
    "repo_path",
    type=click.Path(exists=True, file_okay=False),
    default=".",
    help="Path to the git repository.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True),
    default="apptest.yml",
    help="Path to apptest.yml config file.",
)
@click.option(
    "--output",
    "output_dir",
    type=click.Path(),
    default=".apptest",
    help="Output directory for analysis results.",
)
def analyze(diff_ref: str, repo_path: str, config_path: str, output_dir: str):
    """Analyze a PR diff and identify affected screens."""
    repo = Path(repo_path).resolve()
    config = load_config(config_path)

    click.echo(f"Analyzing {config.app.name} ({config.app.package})")
    click.echo(f"Diff: {diff_ref}")
    click.echo(f"Repo: {repo}")

    # Step 1: Parse the diff
    click.echo("\n[1/4] Parsing diff...")
    changed_files = parse_diff(repo, diff_ref)
    click.echo(f"  Found {len(changed_files)} relevant changed files")

    if not changed_files:
        click.echo("No relevant files changed. Nothing to analyze.")
        return

    # Step 2: Parse the manifest
    click.echo("[2/4] Parsing manifest...")
    manifest_path = repo / config.source.manifest
    if not manifest_path.exists():
        click.echo(f"  Warning: Manifest not found at {manifest_path}")
        activities = []
    else:
        activities = parse_manifest(manifest_path, namespace=config.app.package)
        click.echo(f"  Found {len(activities)} activities")

    # Step 3: Map changed files to screens
    click.echo("[3/4] Mapping files to screens...")
    screens = map_changed_files(
        changed_files,
        activities,
        config.source.root,
        config.source.layouts_dir,
    )
    click.echo(f"  Identified {len(screens)} affected screen(s):")
    for screen in screens:
        host = f" (host: {screen.host_activity})" if screen.host_activity else ""
        click.echo(f"    - {screen.qualified_name}{host}")

    if not screens:
        click.echo("No affected screens identified.")
        return

    # Step 4: Build context for each screen
    click.echo("[4/4] Building screen context...")
    result = build_context(
        screens=screens,
        changed_files=changed_files,
        repo_path=repo,
        layouts_dir=config.source.layouts_dir,
        strings_file=config.source.strings_file,
        app_name=config.app.name,
        app_package=config.app.package,
        diff_ref=diff_ref,
    )

    # Write output
    out_path = write_analysis(result, Path(output_dir))
    click.echo(f"\nAnalysis written to {out_path}")
    click.echo(f"  {result.total_changed_files} changed files")
    click.echo(f"  {len(result.affected_screens)} affected screens")
