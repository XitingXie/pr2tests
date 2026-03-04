"""CLI entry point for apptest."""

from datetime import datetime
from pathlib import Path

import click

from .analyzer.context_builder import build_context, write_analysis
from .analyzer.diff_parser import parse_diff
from .analyzer.manifest_parser import parse_manifest
from .analyzer.profile_updater import update_profile_from_analysis
from .config import load_config
from .generator.test_generator import GenerationResult, generate_tests, write_tests
from .reporter.html_renderer import write_report_html
from .reporter.report_builder import build_report, write_report_json
from .reporter.report_collector import (
    collect_prs_last_n,
    collect_prs_manual,
    collect_prs_since,
    get_version_info,
    update_state,
)
from .reporter.report_index import add_to_index
from .reporter.report_schema import TriggerInfo
from .comparator import format_summary, run_comparison, write_comparison
from .quickstart import run_quickstart
from .run_manager import create_run_dir, get_latest_run
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
    help="Path to the repository root.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(),
    default="apptest.yml",
    help="Config output path.",
)
@click.option("--force", is_flag=True, help="Overwrite existing config.")
def quickstart(repo_path: str, config_path: str, force: bool):
    """Detect project structure and generate config + profile in one step."""
    repo = Path(repo_path).resolve()
    cfg = Path(config_path) if config_path != "apptest.yml" else None
    run_quickstart(repo, config_path=cfg, force=force)


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
@click.option("--pr-number", "pr_number", type=int, default=None, help="PR number for metadata.")
@click.option("--pr-title", "pr_title", default=None, help="PR title for metadata.")
@click.option("--pr-url", "pr_url", default=None, help="PR URL for metadata.")
def analyze(diff_ref: str, repo_path: str, config_path: str, output_dir: str,
            pr_number: int | None, pr_title: str | None, pr_url: str | None):
    """Analyze a PR diff and classify all changes."""
    repo = Path(repo_path).resolve()
    config = load_config(config_path)

    click.echo(f"Analyzing {config.app.name} ({config.app.package})")
    click.echo(f"Diff: {diff_ref}")
    click.echo(f"Repo: {repo}")

    # Load profile, auto-init if missing
    profile = load_effective_profile(repo)
    if profile is None:
        click.echo("  No profile found — running init automatically...")
        scanner_config = {
            "source_root": config.source.root,
            "exclude_dirs": config.source.exclude_dirs,
        }
        auto = scan_project(repo, scanner_config)
        profile_data = {"auto": auto}
        save_profile(repo, profile_data)
        profile = load_effective_profile(repo)
        click.echo(f"  Profile created ({len(auto.get('screens', []))} screens)")
    else:
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
        pr_number=pr_number,
        pr_title=pr_title,
        pr_url=pr_url,
    )

    # Write output — auto-create run dir when using default output
    if output_dir == ".apptest":
        run_dir = create_run_dir(config.app.name)
        out_path = write_analysis(result, run_dir)
        click.echo(f"Run: {run_dir.name}")
    else:
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


@main.command()
@click.option(
    "--mode",
    type=click.Choice(["manual", "daily", "count"]),
    default=None,
    help="Collection mode (overrides config).",
)
@click.option(
    "--range",
    "commit_range",
    default=None,
    help="Commit range for manual mode (e.g. abc123..def456).",
)
@click.option(
    "--since",
    "since_date",
    default=None,
    help="Date for daily mode (e.g. 2026-02-26). Defaults to yesterday.",
)
@click.option(
    "--count",
    "pr_count",
    type=int,
    default=None,
    help="Number of PRs for count mode (overrides config).",
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
    default=None,
    help="Output directory for reports (overrides config).",
)
@click.option(
    "--run",
    "run_path",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="Path to a run directory (auto-discovers latest if not given).",
)
def report(
    mode: str | None,
    commit_range: str | None,
    since_date: str | None,
    pr_count: int | None,
    repo_path: str,
    config_path: str,
    output_dir: str | None,
    run_path: str | None,
):
    """Generate an HTML dashboard report from PR analysis."""
    repo = Path(repo_path).resolve()
    config = load_config(config_path)

    # CLI flags override config
    effective_mode = mode or config.report.trigger_mode
    effective_output = Path(output_dir) if output_dir else Path(config.report.output_dir)
    effective_count = pr_count or config.report.trigger_count

    click.echo(f"Generating report for {config.app.name}")
    click.echo(f"Mode: {effective_mode}")

    # Step 1: Collect PRs
    click.echo("\n[1/4] Collecting PRs...")
    if effective_mode == "manual":
        if not commit_range:
            click.echo("Error: --range is required for manual mode.", err=True)
            raise SystemExit(1)
        pr_summaries = collect_prs_manual(repo, commit_range)
        trigger_desc = f"Manual analysis of range {commit_range}"
        range_str = commit_range
    elif effective_mode == "daily":
        if not since_date:
            from datetime import timedelta
            since_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        pr_summaries = collect_prs_since(repo, since_date)
        trigger_desc = f"Daily report since {since_date}"
        range_str = f"since {since_date}"
    elif effective_mode == "count":
        pr_summaries = collect_prs_last_n(repo, effective_count)
        trigger_desc = f"Last {effective_count} PRs/commits"
        range_str = f"last {effective_count}"
    else:
        click.echo(f"Error: unknown mode '{effective_mode}'.", err=True)
        raise SystemExit(1)

    click.echo(f"  Found {len(pr_summaries)} PR(s)/commit(s)")
    if not pr_summaries:
        click.echo("No PRs found. Nothing to report.")
        return

    trigger = TriggerInfo(
        mode=effective_mode,
        commit_range=range_str,
        description=trigger_desc,
    )

    # Step 2: Get version info
    click.echo("[2/4] Getting version info...")
    version_info = get_version_info(repo)

    # Resolve run directory
    run_dir = None
    if run_path:
        run_dir = Path(run_path).resolve()
    else:
        run_dir = get_latest_run()
    if run_dir is not None:
        click.echo(f"Using run: {run_dir.name}")

    # Step 3: Build report (analyze each PR, generate mock tests, compute metrics)
    click.echo("[3/4] Analyzing PRs and building report...")
    report_data = build_report(repo, config, pr_summaries, trigger, version_info, run_dir=run_dir)

    # Step 4: Render and save
    click.echo("[4/4] Rendering HTML dashboard...")
    report_dir = effective_output / report_data.report_id
    html_path = write_report_html(report_data, report_dir)
    json_path = write_report_json(report_data, report_dir)

    # Update index
    add_to_index(
        output_dir=effective_output,
        report=report_data,
        report_html_path=f"{report_data.report_id}/report.html",
        report_json_path=f"{report_data.report_id}/report.json",
        max_reports=config.report.retention,
        app_name=config.app.name,
    )

    # Update state
    update_state(repo)

    # Summary
    m = report_data.metrics
    click.echo(f"\nReport written to {html_path}")
    click.echo(f"  Report ID:       {report_data.report_id}")
    click.echo(f"  PRs analyzed:    {m.total_prs}")
    click.echo(f"  Files changed:   {m.total_files_changed}")
    click.echo(f"  Screens affected: {m.screens_affected}")
    click.echo(f"  Tests generated: {m.tests_generated}")
    click.echo(f"  Pass rate:       {m.pass_rate}%")
    click.echo(f"\nIndex: {effective_output / 'index.html'}")


@main.command()
@click.option(
    "--analysis",
    "analysis_path",
    type=click.Path(exists=True),
    default=".apptest/analysis.json",
    help="Path to analysis.json from the analyze step.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(),
    default=".apptest/tests.json",
    help="Output path for generated tests.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True),
    default="apptest.yml",
    help="Path to apptest.yml config file.",
)
@click.option(
    "-v", "--verbose",
    is_flag=True,
    default=False,
    help="Print LLM request/response timing to console.",
)
def generate(analysis_path: str, output_path: str, config_path: str, verbose: bool):
    """Generate test steps from PR analysis using an LLM."""
    import json

    config = load_config(config_path)

    # Auto-discover latest run when using defaults
    run_dir = None
    if analysis_path == ".apptest/analysis.json" and output_path == ".apptest/tests.json":
        run_dir = get_latest_run()
        if run_dir is not None:
            analysis_path = str(run_dir / "analysis.json")
            output_path = str(run_dir / "tests.json")
            click.echo(f"Using run: {run_dir.name}")

    click.echo(f"Generating tests for {config.app.name}")
    click.echo(f"Analysis: {analysis_path}")
    click.echo(f"LLM: {config.llm.provider}/{config.llm.model}")

    # Load analysis
    click.echo("\n[1/3] Loading analysis...")
    with open(analysis_path) as f:
        analysis = json.load(f)

    ui_count = len(analysis.get("ui_changes", []))
    logic_count = len(analysis.get("logic_changes", []))
    click.echo(f"  {ui_count} UI changes, {logic_count} logic changes")

    if ui_count == 0 and logic_count == 0:
        click.echo("No UI or logic changes to generate tests for.")
        return

    # Generate tests
    click.echo("[2/3] Calling LLM to generate test steps...")
    result = generate_tests(analysis, config.llm, verbose=verbose, build_config=config.build)

    # Write output
    click.echo("[3/3] Writing results...")
    out = write_tests(result, Path(output_path))

    click.echo(f"\nTests written to {out}")
    click.echo(f"  Generated at: {result.generated_at}")
    click.echo(f"  PR ref:       {result.pr_ref}")
    click.echo(f"  Tests:        {len(result.tests)}")
    for tc in result.tests:
        click.echo(f"    [{tc.priority}] {tc.id}: {tc.covers}")


@main.command()
@click.option(
    "--tests",
    "tests_path",
    type=click.Path(exists=True),
    default=".apptest/tests.json",
    help="Path to tests.json from the generate step.",
)
@click.option(
    "--output",
    "output_dir",
    type=click.Path(),
    default=".apptest/results",
    help="Output directory for results and screenshots.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True),
    default="apptest.yml",
    help="Path to apptest.yml config file.",
)
@click.option(
    "--device",
    "device_serial",
    default="emulator-5554",
    help="ADB device serial (default: emulator-5554).",
)
@click.option(
    "--package",
    "package_override",
    default=None,
    help="Override app package name from config.",
)
@click.option(
    "--apk",
    "apk_path",
    type=click.Path(exists=True),
    default=None,
    help="Path to APK file to install before running tests.",
)
@click.option(
    "--clear-data",
    "clear_data",
    is_flag=True,
    default=False,
    help="Clear app data before running (triggers onboarding).",
)
@click.option(
    "--model",
    "model_override",
    default=None,
    help="Override LLM model (e.g. kimi-k2.5, gemini-2.0-flash, gpt-4o).",
)
@click.option(
    "--provider",
    "provider_override",
    default=None,
    help="Override LLM provider (moonshot, google, or openai).",
)
@click.option(
    "-v", "--verbose",
    is_flag=True,
    default=False,
    help="Print real-time events (LLM calls, screenshots, actions) to console.",
)
def run(
    tests_path: str,
    output_dir: str,
    config_path: str,
    device_serial: str,
    package_override: str | None,
    apk_path: str | None,
    clear_data: bool,
    model_override: str | None,
    provider_override: str | None,
    verbose: bool,
):
    """Run generated tests on an Android device/emulator."""
    from .runner.executor import run_all_tests
    from .runner.schemas import to_execution_results

    config = load_config(config_path)
    app_package = package_override or config.app.package

    if model_override:
        config.llm.model = model_override
    if provider_override:
        config.llm.provider = provider_override

    # Auto-discover latest run when using defaults
    run_dir = None
    if tests_path == ".apptest/tests.json" and output_dir == ".apptest/results":
        run_dir = get_latest_run()
        if run_dir is not None:
            tests_path = str(run_dir / "tests.json")
            output_dir = str(run_dir)
            click.echo(f"Using run: {run_dir.name}")

    click.echo(f"Running tests for {config.app.name} ({app_package})")
    click.echo(f"Tests:  {tests_path}")
    click.echo(f"Device: {device_serial}")
    click.echo(f"Output: {output_dir}")
    click.echo(f"LLM:    {config.llm.provider}/{config.llm.model}")

    click.echo("\n[1/1] Executing tests...")
    try:
        summary = run_all_tests(
            tests_path=tests_path,
            config=config.llm,
            app_package=app_package,
            device_serial=device_serial,
            output_dir=output_dir,
            apk_path=apk_path,
            clear_data=clear_data,
            verbose=verbose,
        )
    except RuntimeError as e:
        click.echo(f"\nError: {e}", err=True)
        raise SystemExit(1)
    except ValueError as e:
        click.echo(f"\nError: {e}", err=True)
        raise SystemExit(1)

    # Summary
    click.echo(f"\nResults written to {output_dir}/results.json")
    click.echo(f"  Total:   {summary.total_tests}")
    click.echo(f"  Passed:  {summary.passed}")
    click.echo(f"  Failed:  {summary.failed}")
    click.echo(f"  Skipped: {summary.skipped}")
    click.echo(f"  Errors:  {summary.errored}")

    for r in summary.results:
        icon = "PASS" if r.status == "passed" else "FAIL"
        click.echo(f"  [{icon}] {r.test_id}")
        if r.failure_reason:
            click.echo(f"         {r.failure_reason}")


def _fetch_pr_metadata(pr_url: str) -> dict:
    """Fetch PR metadata from GitHub using `gh` CLI or URL parsing.

    Returns dict with keys: number, title, head_sha, base_sha, repo_url, diff_ref.
    """
    import subprocess

    meta: dict = {"pr_url": pr_url}

    # Parse owner/repo/number from URL
    # Format: https://github.com/{owner}/{repo}/pull/{number}
    parts = pr_url.rstrip("/").split("/")
    pull_idx = next((i for i, p in enumerate(parts) if p == "pull"), -1)
    if pull_idx < 3 or pull_idx + 1 >= len(parts):
        raise click.BadParameter(f"Cannot parse PR URL: {pr_url}")

    owner_repo = "/".join(parts[pull_idx - 2 : pull_idx])
    pr_number = int(parts[pull_idx + 1])
    repo_url = "/".join(parts[: pull_idx]) + ".git"

    meta["number"] = pr_number
    meta["repo_url"] = repo_url

    # Try gh CLI for rich metadata (title, commits)
    try:
        gh_out = subprocess.run(
            ["gh", "pr", "view", str(pr_number),
             "--repo", owner_repo,
             "--json", "title,headRefOid,baseRefOid,mergeCommit"],
            capture_output=True, text=True, timeout=15,
        )
        if gh_out.returncode == 0:
            import json as _json
            data = _json.loads(gh_out.stdout)
            meta["title"] = data.get("title", "")
            head = data.get("headRefOid", "")
            base = data.get("baseRefOid", "")
            if head:
                meta["head_sha"] = head
                short = head[:7]
                meta["diff_ref"] = f"{short}^..{short}" if not base else f"{base[:7]}..{short}"
            if base:
                meta["base_sha"] = base
        return meta
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: just use the PR number as diff ref placeholder
    meta["title"] = ""
    meta["diff_ref"] = f"PR #{pr_number}"
    return meta


def _has_commit(repo: Path, sha: str) -> bool:
    """Check if a commit SHA exists in the local repo."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "cat-file", "-e", sha],
            cwd=repo,
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _ensure_local_repo(
    repo_url: str,
    head_sha: str,
    base_sha: str | None = None,
) -> Path:
    """Clone or update a cached copy of the remote repo.

    Returns the path to the local clone with *head_sha* checked out.
    Cache location: .apptest/repos/<owner>/<repo>/
    """
    import subprocess

    # Parse owner/repo from URL like https://github.com/owner/repo.git
    clean = repo_url.rstrip("/").removesuffix(".git")
    parts = clean.split("/")
    owner = parts[-2]
    repo_name = parts[-1]

    cache_dir = Path(".apptest") / "repos" / owner / repo_name
    clone_exists = (cache_dir / ".git").exists()

    if clone_exists:
        click.echo(f"  Reusing cached clone at {cache_dir}")
        subprocess.run(
            ["git", "fetch", "--depth", "500", "origin"],
            cwd=cache_dir,
            check=True,
            timeout=300,
        )
    else:
        click.echo(f"  Cloning {repo_url} → {cache_dir}")
        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        # Use https URL without .git suffix for broader compatibility
        clone_url = clean if not repo_url.endswith(".git") else repo_url
        subprocess.run(
            ["git", "clone", "--depth", "500", clone_url, str(cache_dir)],
            check=True,
            timeout=300,
        )

    # Ensure both SHAs are reachable (shallow clones may miss them)
    for sha in filter(None, [head_sha, base_sha]):
        if not _has_commit(cache_dir, sha):
            click.echo(f"  Fetching commit {sha[:7]}...")
            subprocess.run(
                ["git", "fetch", "--depth", "500", "origin", sha],
                cwd=cache_dir,
                capture_output=True,
                timeout=120,
            )

    # Checkout head SHA so the source tree matches the PR state
    click.echo(f"  Checking out {head_sha[:7]}...")
    subprocess.run(
        ["git", "checkout", head_sha],
        cwd=cache_dir,
        capture_output=True,
        check=True,
        timeout=30,
    )

    return cache_dir.resolve()


@main.command()
@click.option(
    "--pr",
    "pr_input",
    default=None,
    help="GitHub PR URL (e.g. https://github.com/owner/repo/pull/123). "
         "Auto-detects diff, title, repo URL.",
)
@click.option(
    "--diff",
    "diff_ref",
    default=None,
    help="Git diff reference (e.g. HEAD~1..HEAD). Overrides --pr auto-detection.",
)
@click.option(
    "--repo",
    "repo_path",
    type=click.Path(file_okay=False),
    default=None,
    help="Path to the git repository (auto-cloned when using --pr).",
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
    default=None,
    help="Output directory (default: auto-created under .apptest/runs/).",
)
@click.option(
    "--device",
    "device_serial",
    default="emulator-5554",
    help="ADB device serial (default: emulator-5554).",
)
@click.option(
    "--package",
    "package_override",
    default=None,
    help="Override app package name from config.",
)
@click.option(
    "--apk",
    "apk_path",
    type=click.Path(exists=True),
    default=None,
    help="Path to pre-built APK (skips build agent).",
)
@click.option(
    "--skip-run",
    is_flag=True,
    default=False,
    help="Skip test execution (only analyze + generate).",
)
@click.option(
    "--skip-report",
    is_flag=True,
    default=False,
    help="Skip report generation.",
)
@click.option(
    "-v", "--verbose",
    is_flag=True,
    default=False,
    help="Verbose output for all steps.",
)
def pipeline(
    pr_input: str | None,
    diff_ref: str | None,
    repo_path: str | None,
    config_path: str,
    output_dir: str | None,
    device_serial: str,
    package_override: str | None,
    apk_path: str | None,
    skip_run: bool,
    skip_report: bool,
    verbose: bool,
):
    """Run the full pipeline: analyze → generate → run → report.

    \b
    Examples:
      # From a GitHub PR URL (auto-detects everything):
      apptest pipeline --pr https://github.com/owner/repo/pull/123 -v

      # From a local diff:
      apptest pipeline --diff "HEAD~1..HEAD" -v

      # With pre-built APK (skips build agent):
      apptest pipeline --pr https://github.com/owner/repo/pull/123 --apk ./app.apk -v

      # Only analyze + generate (no device needed):
      apptest pipeline --pr https://github.com/owner/repo/pull/123 --skip-run --skip-report -v
    """
    import json

    user_specified_repo = repo_path is not None
    repo = Path(repo_path).resolve() if repo_path else Path(".").resolve()
    config = load_config(config_path)
    app_package = package_override or config.build.test_package or config.app.package

    # Resolve PR metadata
    pr_number = None
    pr_title = None
    pr_url = None

    if pr_input:
        click.echo(f"Fetching PR metadata from {pr_input}...")
        try:
            meta = _fetch_pr_metadata(pr_input)
        except Exception as e:
            click.echo(f"Error fetching PR metadata: {e}", err=True)
            raise SystemExit(1)

        pr_number = meta.get("number")
        pr_title = meta.get("title", "")
        pr_url = meta.get("pr_url", pr_input)
        if not diff_ref:
            diff_ref = meta.get("diff_ref", "HEAD~1..HEAD")
        click.echo(f"  PR #{pr_number}: {pr_title}")
        click.echo(f"  Diff: {diff_ref}")
        click.echo(f"  Repo: {meta.get('repo_url', '')}")

        # Auto-clone remote repo when commits aren't available locally
        if not user_specified_repo and meta.get("repo_url"):
            head_sha = meta.get("head_sha", "")
            if head_sha and not _has_commit(repo, head_sha):
                click.echo(f"  Commits not found locally — auto-cloning remote repo...")
                repo = _ensure_local_repo(
                    repo_url=meta["repo_url"],
                    head_sha=head_sha,
                    base_sha=meta.get("base_sha"),
                )

    if not diff_ref:
        diff_ref = "HEAD~1..HEAD"

    # Determine output directory
    if output_dir:
        out_dir = Path(output_dir)
    else:
        out_dir = create_run_dir(config.app.name)

    out_dir.mkdir(parents=True, exist_ok=True)
    analysis_path = out_dir / "analysis.json"
    tests_path = out_dir / "tests.json"

    click.echo(f"{'=' * 60}")
    click.echo(f"  AppTest Pipeline — {config.app.name}")
    click.echo(f"{'=' * 60}")
    click.echo(f"  Diff:    {diff_ref}")
    click.echo(f"  Repo:    {repo}")
    click.echo(f"  Output:  {out_dir}")
    click.echo(f"  LLM:     {config.llm.provider}/{config.llm.model}")
    click.echo(f"  Device:  {device_serial}")
    if pr_number:
        click.echo(f"  PR:      #{pr_number} {pr_title or ''}")
    click.echo()

    # ── Step 1: Analyze ──────────────────────────────────────────
    click.echo(f"[1/4] Analyzing PR diff...")

    profile = load_effective_profile(repo)
    if profile is None:
        click.echo("  No profile found — running init automatically...")
        scanner_config = {
            "source_root": config.source.root,
            "exclude_dirs": config.source.exclude_dirs,
        }
        auto = scan_project(repo, scanner_config)
        save_profile(repo, {"auto": auto})
        profile = load_effective_profile(repo)

    changed_files = parse_diff(repo, diff_ref, filter_relevant=False)
    click.echo(f"  Found {len(changed_files)} changed files")

    if not changed_files:
        click.echo("No changed files. Nothing to do.")
        return

    manifest_path = repo / config.source.manifest
    activities = []
    if manifest_path.exists():
        activities = parse_manifest(manifest_path, namespace=config.app.package)

    analysis_result = build_context(
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
        pr_number=pr_number,
        pr_title=pr_title,
        pr_url=pr_url,
    )

    write_analysis(analysis_result, out_dir)
    click.echo(f"  {len(analysis_result.ui_changes)} UI, "
               f"{len(analysis_result.logic_changes)} logic, "
               f"{len(analysis_result.test_changes)} test, "
               f"{len(analysis_result.infra_changes)} infra changes")

    # ── Step 1.5: Navigation graph ────────────────────────────────
    nav_data: dict = {}
    if config.nav_graph_path:
        click.echo(f"\n  Generating navigation graph...")
        from .nav_graph import generate_nav_graph

        changed_paths = [cf.path for cf in changed_files]
        nav_data = generate_nav_graph(repo, config.nav_graph_path, changed_paths)
        if nav_data:
            nav_graph_path = out_dir / "nav_graph.json"
            with open(nav_graph_path, "w") as f:
                json.dump(nav_data, f, indent=2)
            click.echo(f"  Nav graph saved ({len(nav_data)} keys)")
        else:
            click.echo(f"  Nav graph generation returned no data (non-blocking)")

    # ── Step 2: Generate tests ───────────────────────────────────
    click.echo(f"\n[2/4] Generating test steps via {config.llm.provider}/{config.llm.model}...")

    with open(analysis_path) as f:
        analysis_data = json.load(f)

    gen_result = generate_tests(
        analysis_data, config.llm, verbose=verbose, build_config=config.build,
        nav_data=nav_data if nav_data else None,
    )
    write_tests(gen_result, tests_path)
    click.echo(f"  Generated {len(gen_result.tests)} test(s)")
    for tc in gen_result.tests:
        click.echo(f"    [{tc.priority}] {tc.id}: {tc.covers}")

    if not gen_result.tests:
        click.echo("No tests generated. Stopping pipeline.")
        return

    # ── Step 3: Run tests ────────────────────────────────────────
    if skip_run:
        click.echo(f"\n[3/4] Skipping test execution (--skip-run)")
    else:
        click.echo(f"\n[3/4] Running tests on {device_serial}...")
        from .runner.executor import run_all_tests

        try:
            summary = run_all_tests(
                tests_path=str(tests_path),
                config=config.llm,
                app_package=app_package,
                device_serial=device_serial,
                output_dir=str(out_dir),
                apk_path=apk_path,
                clear_data=False,
                verbose=verbose,
                build_config=config.build,
            )
        except (RuntimeError, ValueError) as e:
            click.echo(f"  Error during test execution: {e}", err=True)
            click.echo("  Continuing to report step...")
            summary = None

        if summary:
            click.echo(f"  Passed: {summary.passed}/{summary.total_tests}")
            for r in summary.results:
                icon = "PASS" if r.status == "passed" else "FAIL"
                click.echo(f"    [{icon}] {r.test_id}")
                if r.failure_reason:
                    click.echo(f"           {r.failure_reason}")

    # ── Step 4: Report ───────────────────────────────────────────
    if skip_report:
        click.echo(f"\n[4/4] Skipping report generation (--skip-report)")
    else:
        click.echo(f"\n[4/4] Generating report...")
        try:
            pr_summaries = collect_prs_manual(repo, diff_ref)
            trigger = TriggerInfo(
                mode="manual",
                commit_range=diff_ref,
                description=f"Pipeline run for {diff_ref}",
            )
            version_info = get_version_info(repo)
            report_data = build_report(
                repo, config, pr_summaries, trigger, version_info, run_dir=out_dir,
            )
            report_dir = Path(config.report.output_dir) / report_data.report_id
            html_path = write_report_html(report_data, report_dir)
            write_report_json(report_data, report_dir)
            add_to_index(
                output_dir=Path(config.report.output_dir),
                report=report_data,
                report_html_path=f"{report_data.report_id}/report.html",
                report_json_path=f"{report_data.report_id}/report.json",
                max_reports=config.report.retention,
                app_name=config.app.name,
            )
            click.echo(f"  Report: {html_path}")
        except Exception as e:
            click.echo(f"  Report generation failed: {e}", err=True)

    # ── Summary ──────────────────────────────────────────────────
    click.echo(f"\n{'=' * 60}")
    click.echo(f"  Pipeline complete")
    click.echo(f"  Output: {out_dir}")
    click.echo(f"{'=' * 60}")


@main.command()
@click.option("--before", required=False, help="Git ref for before state.")
@click.option("--after", required=False, help="Git ref for after state.")
@click.option(
    "--pr",
    required=False,
    help="PR commit ref (shorthand for --before ref~1 --after ref).",
)
@click.option(
    "--config",
    "config_path",
    required=True,
    help="Path to apptest.yml config file.",
)
@click.option(
    "--generate",
    is_flag=True,
    help="Also generate and compare tests (requires LLM access).",
)
@click.option(
    "--output",
    default=None,
    help="Output path for comparison JSON.",
)
@click.option(
    "--repo",
    "repo_path",
    type=click.Path(exists=True, file_okay=False),
    default=".",
    help="Path to the git repository.",
)
def compare(
    before: str | None,
    after: str | None,
    pr: str | None,
    config_path: str,
    generate: bool,
    output: str | None,
    repo_path: str,
):
    """Compare analysis/tests between two git refs."""
    repo = Path(repo_path).resolve()

    # Handle --pr shorthand
    if pr:
        if before or after:
            click.echo("Error: --pr cannot be used with --before/--after.", err=True)
            raise SystemExit(1)
        before = f"{pr}~1"
        after = pr
    elif not before or not after:
        click.echo("Error: either --pr or both --before and --after are required.", err=True)
        raise SystemExit(1)

    click.echo(f"Comparing {before} -> {after}")
    click.echo(f"Repo: {repo}")
    if generate:
        click.echo("Test generation: enabled")

    click.echo("\nRunning comparison...")
    try:
        result = run_comparison(
            repo=repo,
            before_ref=before,
            after_ref=after,
            config_path=Path(config_path),
            generate=generate,
        )
    except Exception as e:
        click.echo(f"\nError during comparison: {e}", err=True)
        raise SystemExit(1)

    # Print summary
    click.echo(f"\n{result.summary}")

    # Write output if requested
    if output:
        out_path = write_comparison(result, Path(output))
        click.echo(f"\nComparison written to {out_path}")
