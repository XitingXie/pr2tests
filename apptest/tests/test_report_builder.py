"""Tests for report_builder module."""

from apptest.analyzer.context_builder import (
    AnalysisResult,
    LogicChangeContext,
    TestChangeContext,
    UIChangeContext,
)
from apptest.reporter.report_builder import (
    _compute_metrics,
    _executions_from_run,
    _generate_mock_execution,
    _generate_mock_tests,
    _summarize_analysis,
    _tests_from_run,
)
from apptest.reporter.report_schema import (
    AnalyzerSummary,
    PRSummary,
)


def _make_analysis_result(**kwargs) -> AnalysisResult:
    defaults = dict(
        app_name="Test", app_package="com.test", diff_ref="abc..def",
        total_changed_files=3,
    )
    defaults.update(kwargs)
    return AnalysisResult(**defaults)


class TestSummarizeAnalysis:
    def test_basic_counts(self):
        result = _make_analysis_result(
            ui_changes=[
                UIChangeContext(file="a.xml", diff="", type="ui_layout", content="",
                                affected_screens=["Screen.kt"]),
            ],
            logic_changes=[
                LogicChangeContext(
                    file="b.kt", diff="", full_source="", type="logic_viewmodel",
                    change_nature="bug_fix", dependency_chain=["b.kt", "Screen.kt"],
                    affected_screens=["Screen.kt"], trace_confidence="high",
                    screen_context=[],
                ),
            ],
            test_changes=[TestChangeContext(file="c.kt", diff="", note="test")],
        )
        summary = _summarize_analysis("abc", result)
        assert summary.pr_ref == "abc"
        assert summary.ui_count == 1
        assert summary.logic_count == 1
        assert summary.test_count == 1
        assert summary.infra_count == 0
        assert "Screen.kt" in summary.affected_screens
        assert summary.change_natures == {"bug_fix": 1}
        assert summary.trace_confidences == {"high": 1}

    def test_deduplicates_screens(self):
        result = _make_analysis_result(
            ui_changes=[
                UIChangeContext(file="a.xml", diff="", type="ui_layout", content="",
                                affected_screens=["Screen.kt"]),
            ],
            logic_changes=[
                LogicChangeContext(
                    file="b.kt", diff="", full_source="", type="logic_viewmodel",
                    change_nature="modification", dependency_chain=[],
                    affected_screens=["Screen.kt"], trace_confidence="medium",
                    screen_context=[],
                ),
            ],
        )
        summary = _summarize_analysis("abc", result)
        assert summary.affected_screens.count("Screen.kt") == 1

    def test_empty_result(self):
        result = _make_analysis_result()
        summary = _summarize_analysis("abc", result)
        assert summary.ui_count == 0
        assert summary.affected_screens == []


class TestMockTestGeneration:
    def test_generates_tests_for_screens(self):
        summary = AnalyzerSummary(
            pr_ref="abc", total_files=3, ui_count=1, logic_count=1,
            test_count=0, infra_count=0,
            affected_screens=["path/to/SearchFragment.kt", "path/to/HomeActivity.kt"],
        )
        tests = _generate_mock_tests(summary, "abc")
        assert len(tests) >= 2  # At least 1 per screen
        for t in tests:
            assert t.test_id.startswith("test_abc_")
            assert t.pr_ref == "abc"
            assert len(t.steps) >= 3
            assert t.priority in ("high", "medium", "low")

    def test_no_screens_no_tests(self):
        summary = AnalyzerSummary(
            pr_ref="abc", total_files=1, ui_count=0, logic_count=0,
            test_count=0, infra_count=0,
        )
        tests = _generate_mock_tests(summary, "abc")
        assert tests == []

    def test_deterministic(self):
        summary = AnalyzerSummary(
            pr_ref="abc", total_files=1, ui_count=1, logic_count=0,
            test_count=0, infra_count=0,
            affected_screens=["Screen.kt"],
        )
        a = _generate_mock_tests(summary, "abc")
        b = _generate_mock_tests(summary, "abc")
        assert len(a) == len(b)
        for ta, tb in zip(a, b):
            assert ta.test_id == tb.test_id
            assert len(ta.steps) == len(tb.steps)


class TestMockExecution:
    def test_generates_results_for_all_tests(self):
        summary = AnalyzerSummary(
            pr_ref="abc", total_files=3, ui_count=1, logic_count=1,
            test_count=0, infra_count=0,
            affected_screens=["Screen.kt", "Other.kt"],
        )
        tests = _generate_mock_tests(summary, "abc")
        executions = _generate_mock_execution(tests)
        assert len(executions) == len(tests)
        for e in executions:
            assert e.status in ("passed", "failed", "skipped", "error")
            assert e.duration_ms >= 2000
            assert e.steps_total >= 0

    def test_deterministic(self):
        summary = AnalyzerSummary(
            pr_ref="abc", total_files=1, ui_count=0, logic_count=0,
            test_count=0, infra_count=0,
            affected_screens=["Screen.kt"],
        )
        tests = _generate_mock_tests(summary, "abc")
        a = _generate_mock_execution(tests)
        b = _generate_mock_execution(tests)
        for ea, eb in zip(a, b):
            assert ea.status == eb.status
            assert ea.duration_ms == eb.duration_ms


class TestComputeMetrics:
    def test_full_metrics(self):
        prs = [
            PRSummary(ref="a", title="", author="", date="", files_changed=3, insertions=10, deletions=2),
            PRSummary(ref="b", title="", author="", date="", files_changed=2, insertions=5, deletions=1),
        ]
        summaries = [
            AnalyzerSummary(
                pr_ref="a", total_files=3, ui_count=1, logic_count=2,
                test_count=0, infra_count=0,
                affected_screens=["Screen.kt"],
            ),
            AnalyzerSummary(
                pr_ref="b", total_files=2, ui_count=0, logic_count=1,
                test_count=1, infra_count=0,
                affected_screens=["Screen.kt", "Other.kt"],
            ),
        ]
        tests = _generate_mock_tests(summaries[0], "a") + _generate_mock_tests(summaries[1], "b")
        execs = _generate_mock_execution(tests)

        m = _compute_metrics(prs, summaries, tests, execs)
        assert m.total_prs == 2
        assert m.total_files_changed == 5
        assert m.screens_affected == 2  # Screen.kt and Other.kt
        assert m.tests_generated == len(tests)
        assert m.tests_passed + m.tests_failed + m.tests_skipped == len(execs)
        assert 0 <= m.pass_rate <= 100

    def test_empty_metrics(self):
        m = _compute_metrics([], [], [], [])
        assert m.total_prs == 0
        assert m.pass_rate == 0.0


class TestTestsFromRun:
    def test_converts_test_cases(self):
        data = {
            "pr_ref": "abc..def",
            "tests": [
                {
                    "id": "test_001",
                    "description": "1. Open the app\n2. Tap search\n3. Verify results",
                    "covers": "Search feature",
                    "priority": "high",
                },
            ],
        }
        tests = _tests_from_run(data, "abc..def")
        assert len(tests) == 1
        t = tests[0]
        assert t.test_id == "test_001"
        assert t.screen == "Search feature"
        assert t.test_name == "Search feature"
        assert t.priority == "high"
        assert t.pr_ref == "abc..def"
        assert len(t.steps) == 3

    def test_empty_tests(self):
        data = {"tests": []}
        tests = _tests_from_run(data, "ref")
        assert tests == []

    def test_missing_tests_key(self):
        tests = _tests_from_run({}, "ref")
        assert tests == []

    def test_skips_blank_lines(self):
        data = {
            "tests": [
                {
                    "id": "t1",
                    "description": "Step one\n\nStep two\n",
                    "covers": "feature",
                    "priority": "low",
                },
            ],
        }
        tests = _tests_from_run(data, "ref")
        assert len(tests[0].steps) == 2

    def test_defaults_priority(self):
        data = {"tests": [{"id": "t1", "description": "Step", "covers": "x"}]}
        tests = _tests_from_run(data, "ref")
        assert tests[0].priority == "medium"


class TestExecutionsFromRun:
    def test_converts_results(self):
        data = {
            "results": [
                {
                    "test_id": "test_001",
                    "status": "passed",
                    "total_duration_ms": 5000,
                    "failure_reason": "",
                    "steps": [
                        {"step_index": 0, "status": "passed"},
                        {"step_index": 1, "status": "passed"},
                    ],
                },
                {
                    "test_id": "test_002",
                    "status": "failed",
                    "total_duration_ms": 3000,
                    "failure_reason": "Element not found",
                    "steps": [
                        {"step_index": 0, "status": "passed"},
                        {"step_index": 1, "status": "failed"},
                    ],
                },
            ],
        }
        results = _executions_from_run(data)
        assert len(results) == 2
        assert results[0].test_id == "test_001"
        assert results[0].status == "passed"
        assert results[0].duration_ms == 5000
        assert results[0].steps_completed == 2
        assert results[0].steps_total == 2
        assert results[1].steps_completed == 1
        assert results[1].failure_reason == "Element not found"

    def test_empty_results(self):
        results = _executions_from_run({"results": []})
        assert results == []

    def test_missing_results_key(self):
        results = _executions_from_run({})
        assert results == []

    def test_defaults_status_to_error(self):
        data = {"results": [{"test_id": "t1", "steps": []}]}
        results = _executions_from_run(data)
        assert results[0].status == "error"
