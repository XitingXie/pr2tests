"""Data structures for test runner results."""

from dataclasses import dataclass, field
from enum import Enum

from ..reporter.report_schema import TestExecutionResult


class ActionType(str, Enum):
    TAP = "tap"
    TYPE = "type"
    SWIPE_UP = "swipe_up"
    SWIPE_DOWN = "swipe_down"
    BACK = "back"
    HOME = "home"
    ENTER = "enter"
    LAUNCH = "launch"
    WAIT = "wait"
    DONE = "done"
    ASSERT_PASS = "assert_pass"
    ASSERT_FAIL = "assert_fail"


@dataclass
class Action:
    action_type: ActionType
    x: int = 0
    y: int = 0
    text: str = ""
    reasoning: str = ""
    duration_ms: int = 0


@dataclass
class StepResult:
    step_index: int
    step_text: str
    status: str  # "passed" | "failed" | "error"
    actions: list[Action] = field(default_factory=list)
    failure_reason: str = ""
    duration_ms: int = 0


@dataclass
class TestRunResult:
    __test__ = False  # prevent pytest collection
    test_id: str
    status: str  # "passed" | "failed" | "skipped" | "error"
    steps: list[StepResult] = field(default_factory=list)
    total_duration_ms: int = 0
    failure_reason: str = ""


@dataclass
class RunSummary:
    started_at: str
    completed_at: str
    device_serial: str
    app_package: str
    total_tests: int
    passed: int
    failed: int
    skipped: int
    errored: int
    results: list[TestRunResult] = field(default_factory=list)


def to_execution_results(summary: RunSummary) -> list[TestExecutionResult]:
    """Convert RunSummary to report-compatible TestExecutionResult list."""
    out: list[TestExecutionResult] = []
    for r in summary.results:
        completed = sum(1 for s in r.steps if s.status == "passed")
        out.append(TestExecutionResult(
            test_id=r.test_id,
            status=r.status,
            duration_ms=r.total_duration_ms,
            failure_reason=r.failure_reason,
            steps_completed=completed,
            steps_total=len(r.steps),
        ))
    return out
