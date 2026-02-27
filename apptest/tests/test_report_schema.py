"""Tests for report_schema module."""

from dataclasses import asdict

from apptest.reporter.report_schema import (
    AggregateMetrics,
    AnalyzerSummary,
    GeneratedTest,
    GeneratedTestStep,
    PRSummary,
    ReportData,
    ReportIndexEntry,
    TestExecutionResult,
    TriggerInfo,
)


class TestSerialization:
    """Verify round-trip serialization via asdict()."""

    def test_trigger_info(self):
        t = TriggerInfo(mode="manual", commit_range="abc..def", description="test")
        d = asdict(t)
        assert d["mode"] == "manual"
        assert d["commit_range"] == "abc..def"

    def test_pr_summary(self):
        pr = PRSummary(
            ref="abc1234", title="Fix bug", author="alice",
            date="2026-02-27", files_changed=3, insertions=10, deletions=5,
            change_categories={"ui": 1, "logic": 2},
        )
        d = asdict(pr)
        assert d["ref"] == "abc1234"
        assert d["change_categories"]["logic"] == 2

    def test_analyzer_summary(self):
        s = AnalyzerSummary(
            pr_ref="abc", total_files=5, ui_count=1, logic_count=2,
            test_count=1, infra_count=1,
            affected_screens=["ScreenA.kt"],
            change_natures={"bug_fix": 1},
            trace_confidences={"high": 1},
        )
        d = asdict(s)
        assert d["affected_screens"] == ["ScreenA.kt"]
        assert d["change_natures"]["bug_fix"] == 1

    def test_generated_test_with_steps(self):
        step = GeneratedTestStep(order=1, action="tap", target="btn", value="", expected="opens")
        test = GeneratedTest(
            test_id="t1", screen="Screen.kt", test_name="Test 1",
            description="desc", priority="high", pr_ref="abc",
            steps=[step],
        )
        d = asdict(test)
        assert len(d["steps"]) == 1
        assert d["steps"][0]["action"] == "tap"

    def test_execution_result(self):
        e = TestExecutionResult(
            test_id="t1", status="passed", duration_ms=5000,
            failure_reason="", steps_completed=3, steps_total=3,
        )
        d = asdict(e)
        assert d["status"] == "passed"

    def test_aggregate_metrics(self):
        m = AggregateMetrics(total_prs=2, total_files_changed=10, pass_rate=85.0)
        d = asdict(m)
        assert d["pass_rate"] == 85.0

    def test_report_data_full(self):
        report = ReportData(
            report_id="r1",
            generated_at="2026-02-27T10:00:00",
            app_name="TestApp",
            version_info="abc (2026-02-27)",
            trigger=TriggerInfo(mode="manual", commit_range="a..b", description="test"),
        )
        d = asdict(report)
        assert d["report_id"] == "r1"
        assert d["trigger"]["mode"] == "manual"
        assert d["metrics"]["total_prs"] == 0

    def test_report_index_entry(self):
        e = ReportIndexEntry(
            report_id="r1", generated_at="2026-02-27",
            total_prs=3, screens_affected=5, tests_generated=10,
            pass_rate=80.0, report_path="r1/report.html", json_path="r1/report.json",
        )
        d = asdict(e)
        assert d["report_path"] == "r1/report.html"


class TestDefaultFactoryIsolation:
    """Verify mutable default factories create independent instances."""

    def test_pr_summary_categories_isolated(self):
        a = PRSummary(ref="a", title="", author="", date="", files_changed=0, insertions=0, deletions=0)
        b = PRSummary(ref="b", title="", author="", date="", files_changed=0, insertions=0, deletions=0)
        a.change_categories["ui"] = 5
        assert b.change_categories == {}

    def test_report_data_lists_isolated(self):
        a = ReportData(
            report_id="a", generated_at="", app_name="", version_info="",
            trigger=TriggerInfo(mode="m", commit_range="", description=""),
        )
        b = ReportData(
            report_id="b", generated_at="", app_name="", version_info="",
            trigger=TriggerInfo(mode="m", commit_range="", description=""),
        )
        a.pr_summaries.append(PRSummary(ref="x", title="", author="", date="", files_changed=0, insertions=0, deletions=0))
        assert len(b.pr_summaries) == 0

    def test_analyzer_summary_lists_isolated(self):
        a = AnalyzerSummary(pr_ref="a", total_files=0, ui_count=0, logic_count=0, test_count=0, infra_count=0)
        b = AnalyzerSummary(pr_ref="b", total_files=0, ui_count=0, logic_count=0, test_count=0, infra_count=0)
        a.affected_screens.append("Screen.kt")
        assert b.affected_screens == []
