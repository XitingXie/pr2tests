"""CLI entry point for apptest."""

from pathlib import Path

import click

from .analyzer.context_builder import build_context, write_analysis
from .analyzer.diff_parser import parse_diff
from .analyzer.manifest_parser import parse_manifest
from .analyzer.profile_updater import update_profile_from_analysis
from .config import load_config
from .scanner.profile_manager import load_effective_profile, save_profile
from .scanner.project_scanner import scan_project


@click.group()
def main():
    """AppTest — AI-powered test generation from PR diffs."""
    pass


@main.command()
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
    type=click.Path(),
    default=None,
    help="Path to apptest.yml config file (optional for init).",
)
def init(repo_path: str, config_path: str | None):
    """Scan the codebase and generate an app profile."""
    repo = Path(repo_path).resolve()
    click.echo(f"Scanning project at {repo}")

    # Build config dict from apptest.yml if provided
    scanner_config: dict | None = None
    if config_path:
        try:
            config = load_config(config_path)
            scanner_config = {
                "source_root": config.source.root,
                "exclude_dirs": config.source.exclude_dirs,
            }
        except FileNotFoundError:
            click.echo(f"  Warning: Config file not found at {config_path}, using auto-detection")

    # Run the scan
    click.echo("[1/2] Scanning source tree...")
    auto = scan_project(repo, scanner_config)

    click.echo("[2/2] Saving profile...")
    profile = {"auto": auto}
    out_path = save_profile(repo, profile)

    # Summary
    project = auto.get("project", {})
    screens = auto.get("screens", [])
    chains = auto.get("chains", [])

    click.echo(f"\nProfile written to {out_path}")
    click.echo(f"  Modules:      {', '.join(project.get('modules', []))}")
    click.echo(f"  Architecture: {project.get('architecture', 'unknown')}")
    click.echo(f"  DI framework: {project.get('di_framework', 'none')}")
    click.echo(f"  Screens:      {len(screens)}")
    click.echo(f"  Chains:       {len(chains)}")

    if screens:
        click.echo("  Screen list:")
        for s in screens:
            click.echo(f"    - {s['name']} ({s['type']})")


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
    """Analyze a PR diff and classify all changes."""
    repo = Path(repo_path).resolve()
    config = load_config(config_path)

    click.echo(f"Analyzing {config.app.name} ({config.app.package})")
    click.echo(f"Diff: {diff_ref}")
    click.echo(f"Repo: {repo}")

    # Load profile if it exists
    profile = load_effective_profile(repo)
    if profile is not None:
        click.echo("  Using app profile for fast lookups")

    # Step 1: Parse the diff — include ALL files (classifier handles filtering)
    click.echo("\n[1/3] Parsing diff...")
    changed_files = parse_diff(repo, diff_ref, filter_relevant=False)
    click.echo(f"  Found {len(changed_files)} changed files")

    if not changed_files:
        click.echo("No changed files. Nothing to analyze.")
        return

    # Step 2: Parse the manifest
    click.echo("[2/3] Parsing manifest...")
    manifest_path = repo / config.source.manifest
    if not manifest_path.exists():
        click.echo(f"  Warning: Manifest not found at {manifest_path}")
        activities = []
    else:
        activities = parse_manifest(manifest_path, namespace=config.app.package)
        click.echo(f"  Found {len(activities)} activities")

    # Step 3: Classify, trace, and build context
    click.echo("[3/3] Classifying changes and tracing dependencies...")
    result = build_context(
        changed_files=changed_files,
        activities=activities,
        repo_path=repo,
        source_root=config.source.root,
        layouts_dir=config.source.layouts_dir,
        strings_file=config.source.strings_file,
        exclude_dirs=config.source.exclude_dirs,
        app_name=config.app.name,
        app_package=config.app.package,
        diff_ref=diff_ref,
        profile=profile,
    )

    # Write output
    out_path = write_analysis(result, Path(output_dir))

    # Auto-update profile if it exists
    if profile is not None:
        changed_paths = [cf.path for cf in changed_files]
        update_profile_from_analysis(
            repo, changed_paths, repo,
            config.source.root, config.source.exclude_dirs,
        )
        click.echo("  Profile auto-updated")

    # Summary
    click.echo(f"\nAnalysis written to {out_path}")
    click.echo(f"  {result.total_changed_files} total changed files")
    click.echo(f"  {len(result.ui_changes)} UI changes")
    click.echo(f"  {len(result.logic_changes)} logic changes")
    click.echo(f"  {len(result.test_changes)} test changes")
    click.echo(f"  {len(result.infra_changes)} infra changes")

    if result.logic_changes:
        screens_found = set()
        for lc in result.logic_changes:
            screens_found.update(lc.affected_screens)
        if screens_found:
            click.echo(f"  {len(screens_found)} affected screen(s):")
            for s in sorted(screens_found):
                click.echo(f"    - {Path(s).stem}")
