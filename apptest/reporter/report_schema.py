"""Data structures for apptest reports.

All types are plain dataclasses, serializable via ``dataclasses.asdict()``.
"""

from dataclasses import dataclass, field


@dataclass
class TriggerInfo:
    """How this report was triggered."""
    mode: str               # "manual", "daily", "count"
    commit_range: str       # e.g. "abc123..def456"
    description: str        # Human-readable trigger summary


@dataclass
class PRSummary:
    """One commit/PR included in the report."""
    ref: str                # Short commit hash
    title: str              # First line of commit message
    author: str
    date: str               # ISO-format date string
    files_changed: int
    insertions: int
    deletions: int
    change_categories: dict[str, int] = field(default_factory=dict)  # e.g. {"ui": 2, "logic": 3}


@dataclass
class AnalyzerSummary:
    """Compressed view of an AnalysisResult for one PR."""
    pr_ref: str
    total_files: int
    ui_count: int
    logic_count: int
    test_count: int
    infra_count: int
    affected_screens: list[str] = field(default_factory=list)
    change_natures: dict[str, int] = field(default_factory=dict)    # e.g. {"bug_fix": 2, "new_feature": 1}
    trace_confidences: dict[str, int] = field(default_factory=dict) # e.g. {"high": 3, "medium": 1}
    dependency_chains: list[list[str]] = field(default_factory=list)


@dataclass
class GeneratedTestStep:
    """A single step in a generated test case."""
    order: int
    action: str         # "tap", "type", "scroll", "assert", "navigate", "wait"
    target: str         # Element or screen identifier
    value: str          # Input value or expected text
    expected: str       # Expected outcome description


@dataclass
class GeneratedTest:
    """A generated test case for a screen."""
    test_id: str
    screen: str
    test_name: str
    description: str
    priority: str       # "high", "medium", "low"
    pr_ref: str
    steps: list[GeneratedTestStep] = field(default_factory=list)


@dataclass
class TestExecutionResult:
    """Execution result for a single test."""
    test_id: str
    status: str             # "passed", "failed", "skipped", "error"
    duration_ms: int
    failure_reason: str     # Empty string if passed
    steps_completed: int
    steps_total: int


@dataclass
class AggregateMetrics:
    """Roll-up metrics across all PRs in a report."""
    total_prs: int
    total_files_changed: int
    changes_by_category: dict[str, int] = field(default_factory=dict)
    screens_affected: int = 0
    tests_generated: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    tests_skipped: int = 0
    pass_rate: float = 0.0


@dataclass
class ReportData:
    """Top-level container for a complete report."""
    report_id: str
    generated_at: str       # ISO-format timestamp
    app_name: str
    version_info: str       # e.g. "abc1234 (2026-02-27 10:00:00 -0700)"
    trigger: TriggerInfo
    pr_summaries: list[PRSummary] = field(default_factory=list)
    analyzer_results: list[AnalyzerSummary] = field(default_factory=list)
    generated_tests: list[GeneratedTest] = field(default_factory=list)
    execution_results: list[TestExecutionResult] = field(default_factory=list)
    trace_html_path: str = ""  # Path to trace.html from the run dir (if available)
    metrics: AggregateMetrics = field(default_factory=lambda: AggregateMetrics(
        total_prs=0, total_files_changed=0,
    ))


@dataclass
class ReportIndexEntry:
    """One row in the historical report index."""
    report_id: str
    generated_at: str
    total_prs: int
    screens_affected: int
    tests_generated: int
    pass_rate: float
    report_path: str        # Relative path to report.html
    json_path: str          # Relative path to report.json
