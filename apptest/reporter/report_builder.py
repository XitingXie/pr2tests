"""Orchestrate report building: analyze PRs, generate mock tests, compute metrics."""

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from ..analyzer.context_builder import AnalysisResult, build_context, write_analysis
from ..analyzer.diff_parser import parse_diff
from ..analyzer.manifest_parser import parse_manifest
from ..config import Config
from ..scanner.profile_manager import load_effective_profile
from .report_schema import (
    AggregateMetrics,
    AnalyzerSummary,
    GeneratedTest,
    GeneratedTestStep,
    PRSummary,
    ReportData,
    TestExecutionResult,
    TriggerInfo,
)


def _summarize_analysis(pr_ref: str, result: AnalysisResult) -> AnalyzerSummary:
    """Compress an AnalysisResult into an AnalyzerSummary (drop large fields)."""
    # Collect all affected screens from UI + logic changes
    screens: list[str] = []
    for ui in result.ui_changes:
        for s in ui.affected_screens:
            if s not in screens:
                screens.append(s)
    for lc in result.logic_changes:
        for s in lc.affected_screens:
            if s not in screens:
                screens.append(s)

    # Count change natures
    natures: dict[str, int] = {}
    for lc in result.logic_changes:
        natures[lc.change_nature] = natures.get(lc.change_nature, 0) + 1

    # Count trace confidences
    confidences: dict[str, int] = {}
    for lc in result.logic_changes:
        confidences[lc.trace_confidence] = confidences.get(lc.trace_confidence, 0) + 1

    # Collect unique dependency chains
    chains: list[list[str]] = []
    for lc in result.logic_changes:
        if lc.dependency_chain and lc.dependency_chain not in chains:
            chains.append(lc.dependency_chain)

    return AnalyzerSummary(
        pr_ref=pr_ref,
        total_files=result.total_changed_files,
        ui_count=len(result.ui_changes),
        logic_count=len(result.logic_changes),
        test_count=len(result.test_changes),
        infra_count=len(result.infra_changes),
        affected_screens=screens,
        change_natures=natures,
        trace_confidences=confidences,
        dependency_chains=chains,
    )


def _deterministic_seed(name: str) -> int:
    """Generate a deterministic integer seed from a string."""
    return int(hashlib.md5(name.encode()).hexdigest()[:8], 16)


# --- Mock test generation (Phase 2 placeholder) ---

_MOCK_ACTIONS = [
    ("navigate", "Open {screen}", "", "Screen is displayed"),
    ("tap", "{screen}_search_button", "", "Search view opens"),
    ("type", "search_input", "test query", "Text appears in input"),
    ("tap", "submit_button", "", "Results are loaded"),
    ("assert", "results_list", "non-empty", "Results list has items"),
    ("scroll", "results_list", "down", "More items become visible"),
    ("tap", "first_result", "", "Detail view opens"),
    ("assert", "detail_title", "non-empty", "Title is displayed"),
    ("tap", "back_button", "", "Returns to previous screen"),
    ("wait", "", "1000", "Animation completes"),
]


def _tests_from_run(data: dict, pr_ref: str) -> list[GeneratedTest]:
    """Convert a GenerationResult-format dict (from tests.json) to GeneratedTest list.

    Each TestCase's description is split into lines to create GeneratedTestStep objects.
    """
    tests: list[GeneratedTest] = []
    for tc in data.get("tests", []):
        steps: list[GeneratedTestStep] = []
        description = tc.get("description", "")
        for i, line in enumerate(description.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            # Strip leading numbering like "1. " or "- "
            clean = line.lstrip("0123456789.-) ").strip()
            if not clean:
                clean = line
            steps.append(GeneratedTestStep(
                order=i,
                action="step",
                target="",
                value=clean,
                expected="",
            ))

        test_id = tc.get("id", f"test_{len(tests) + 1}")
        covers = tc.get("covers", "")
        tests.append(GeneratedTest(
            test_id=test_id,
            screen=covers,
            test_name=covers or test_id,
            description=description,
            priority=tc.get("priority", "medium"),
            pr_ref=pr_ref,
            steps=steps,
        ))
    return tests


def _executions_from_run(data: dict) -> list[TestExecutionResult]:
    """Convert a RunSummary-format dict (from results.json) to TestExecutionResult list."""
    results: list[TestExecutionResult] = []
    for r in data.get("results", []):
        step_list = r.get("steps", [])
        completed = sum(1 for s in step_list if s.get("status") == "passed")
        results.append(TestExecutionResult(
            test_id=r.get("test_id", ""),
            status=r.get("status", "error"),
            duration_ms=r.get("total_duration_ms", 0),
            failure_reason=r.get("failure_reason", ""),
            steps_completed=completed,
            steps_total=len(step_list),
        ))
    return results


def _generate_mock_tests(summary: AnalyzerSummary, pr_ref: str) -> list[GeneratedTest]:
    """Generate 1-3 mock test cases per affected screen.

    Uses deterministic seeding from screen names for reproducible output.
    TODO: Replace with real test generation in Phase 2.
    """
    tests: list[GeneratedTest] = []
    for screen in summary.affected_screens:
        seed = _deterministic_seed(screen)
        screen_name = Path(screen).stem
        num_tests = (seed % 3) + 1  # 1-3 tests per screen

        for i in range(num_tests):
            test_seed = seed + i
            num_steps = ((test_seed % 4) + 3)  # 3-6 steps
            priority = ["high", "medium", "low"][test_seed % 3]

            steps: list[GeneratedTestStep] = []
            for j in range(num_steps):
                action_idx = (test_seed + j) % len(_MOCK_ACTIONS)
                action, target, value, expected = _MOCK_ACTIONS[action_idx]
                steps.append(GeneratedTestStep(
                    order=j + 1,
                    action=action,
                    target=target.format(screen=screen_name),
                    value=value,
                    expected=expected,
                ))

            test_id = f"test_{pr_ref}_{screen_name}_{i+1}"
            tests.append(GeneratedTest(
                test_id=test_id,
                screen=screen,
                test_name=f"Test {screen_name} flow {i+1}",
                description=f"Verify {screen_name} behavior after changes in {pr_ref}",
                priority=priority,
                pr_ref=pr_ref,
                steps=steps,
            ))

    return tests


# --- Mock execution results (Phase 3 placeholder) ---

def _generate_mock_execution(tests: list[GeneratedTest]) -> list[TestExecutionResult]:
    """Generate mock execution results: ~80% pass, ~15% fail, ~5% skip.

    Uses deterministic seeding for reproducible output.
    TODO: Replace with real test execution in Phase 3.
    """
    results: list[TestExecutionResult] = []
    for test in tests:
        seed = _deterministic_seed(test.test_id)
        bucket = seed % 100

        if bucket < 80:
            status = "passed"
            failure_reason = ""
            steps_completed = len(test.steps)
        elif bucket < 95:
            status = "failed"
            fail_step = (seed % len(test.steps)) + 1 if test.steps else 1
            failure_reason = f"Assertion failed at step {fail_step}: expected element visible"
            steps_completed = fail_step
        else:
            status = "skipped"
            failure_reason = "Precondition not met: required screen not reachable"
            steps_completed = 0

        # Realistic duration: 2-15 seconds
        duration_ms = 2000 + (seed % 13000)

        results.append(TestExecutionResult(
            test_id=test.test_id,
            status=status,
            duration_ms=duration_ms,
            failure_reason=failure_reason,
            steps_completed=steps_completed,
            steps_total=len(test.steps),
        ))

    return results


def _compute_metrics(
    pr_summaries: list[PRSummary],
    analyzer_results: list[AnalyzerSummary],
    tests: list[GeneratedTest],
    executions: list[TestExecutionResult],
) -> AggregateMetrics:
    """Compute aggregate metrics across all PRs."""
    # Aggregate change categories
    categories: dict[str, int] = {}
    for summary in analyzer_results:
        if summary.ui_count:
            categories["ui"] = categories.get("ui", 0) + summary.ui_count
        if summary.logic_count:
            categories["logic"] = categories.get("logic", 0) + summary.logic_count
        if summary.test_count:
            categories["test"] = categories.get("test", 0) + summary.test_count
        if summary.infra_count:
            categories["infra"] = categories.get("infra", 0) + summary.infra_count

    # Unique screens
    all_screens: set[str] = set()
    for a in analyzer_results:
        all_screens.update(a.affected_screens)

    passed = sum(1 for e in executions if e.status == "passed")
    failed = sum(1 for e in executions if e.status == "failed")
    skipped = sum(1 for e in executions if e.status in ("skipped", "error"))
    total_exec = len(executions)
    pass_rate = (passed / total_exec * 100) if total_exec > 0 else 0.0

    return AggregateMetrics(
        total_prs=len(pr_summaries),
        total_files_changed=sum(p.files_changed for p in pr_summaries),
        changes_by_category=categories,
        screens_affected=len(all_screens),
        tests_generated=len(tests),
        tests_passed=passed,
        tests_failed=failed,
        tests_skipped=skipped,
        pass_rate=round(pass_rate, 1),
    )


def analyze_pr(
    repo: Path,
    config: Config,
    pr: PRSummary,
    profile: dict | None,
) -> AnalysisResult | None:
    """Run the analyzer on a single PR/commit.

    Returns None if analysis fails (e.g. files no longer exist).
    """
    diff_ref = f"{pr.ref}~1..{pr.ref}"
    try:
        changed_files = parse_diff(repo, diff_ref, filter_relevant=False)
    except Exception:
        return None

    if not changed_files:
        return None

    manifest_path = repo / config.source.manifest
    activities = []
    if manifest_path.exists():
        try:
            activities = parse_manifest(manifest_path, namespace=config.app.package)
        except Exception:
            pass

    try:
        return build_context(
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
    except Exception:
        return None


def build_report(
    repo: Path,
    config: Config,
    pr_summaries: list[PRSummary],
    trigger: TriggerInfo,
    version_info: str,
    run_dir: Path | None = None,
) -> ReportData:
    """Build a complete report from collected PRs.

    Args:
        repo: Path to git repository.
        config: App configuration.
        pr_summaries: Collected PR/commit summaries.
        trigger: How the report was triggered.
        version_info: Version string for HEAD.
        run_dir: Optional path to a run directory containing tests.json
                 and results.json. When provided and both files exist,
                 real data is used instead of mock generation.

    Returns:
        Complete ReportData ready for rendering.
    """
    report_id = f"report-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    profile = load_effective_profile(repo)

    analyzer_results: list[AnalyzerSummary] = []
    all_tests: list[GeneratedTest] = []
    all_executions: list[TestExecutionResult] = []
    trace_html_path = ""

    # Try to load real run data
    has_run_data = False
    if run_dir is not None:
        tests_file = run_dir / "tests.json"
        results_file = run_dir / "results.json"
        if tests_file.exists() and results_file.exists():
            tests_data = json.loads(tests_file.read_text())
            results_data = json.loads(results_file.read_text())
            pr_ref = tests_data.get("pr_ref", "unknown")
            all_tests = _tests_from_run(tests_data, pr_ref)
            all_executions = _executions_from_run(results_data)
            has_run_data = True

            # Check for trace.html
            trace_file = run_dir / "trace.html"
            if trace_file.exists():
                trace_html_path = str(trace_file)

    for pr in pr_summaries:
        result = analyze_pr(repo, config, pr, profile)
        if result is None:
            continue

        summary = _summarize_analysis(pr.ref, result)
        analyzer_results.append(summary)

        # Classify changed files into categories for the PR summary
        pr.change_categories = {
            "ui": summary.ui_count,
            "logic": summary.logic_count,
            "test": summary.test_count,
            "infra": summary.infra_count,
        }

        # Fall back to mock generation when no real run data is available
        if not has_run_data and config.report.include_mock_tests:
            tests = _generate_mock_tests(summary, pr.ref)
            executions = _generate_mock_execution(tests)
            all_tests.extend(tests)
            all_executions.extend(executions)

    metrics = _compute_metrics(pr_summaries, analyzer_results, all_tests, all_executions)

    return ReportData(
        report_id=report_id,
        generated_at=datetime.now().isoformat(),
        app_name=config.app.name,
        version_info=version_info,
        trigger=trigger,
        pr_summaries=pr_summaries,
        analyzer_results=analyzer_results,
        generated_tests=all_tests,
        execution_results=all_executions,
        trace_html_path=trace_html_path,
        metrics=metrics,
    )


def write_report_json(report: ReportData, output_dir: Path) -> Path:
    """Write report data as JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "report.json"
    path.write_text(json.dumps(asdict(report), indent=2))
    return path
