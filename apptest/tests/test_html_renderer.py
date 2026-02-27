"""Tests for html_renderer module."""

import json

from apptest.reporter.html_renderer import render_index, render_report
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


def _make_report(**overrides) -> ReportData:
    defaults = dict(
        report_id="test-report-001",
        generated_at="2026-02-27T10:00:00",
        app_name="TestApp",
        version_info="abc1234 (2026-02-27)",
        trigger=TriggerInfo(mode="manual", commit_range="a..b", description="Test run"),
        pr_summaries=[
            PRSummary(
                ref="abc1234", title="Fix search bug", author="alice",
                date="2026-02-27", files_changed=3, insertions=10, deletions=5,
                change_categories={"ui": 1, "logic": 2},
            ),
        ],
        analyzer_results=[
            AnalyzerSummary(
                pr_ref="abc1234", total_files=3, ui_count=1, logic_count=2,
                test_count=0, infra_count=0,
                affected_screens=["SearchFragment.kt"],
                change_natures={"bug_fix": 1},
                trace_confidences={"high": 1},
                dependency_chains=[["Repo.kt", "ViewModel.kt", "Screen.kt"]],
            ),
        ],
        generated_tests=[
            GeneratedTest(
                test_id="test_abc_Search_1", screen="SearchFragment.kt",
                test_name="Test Search flow", description="Verify search",
                priority="high", pr_ref="abc1234",
                steps=[
                    GeneratedTestStep(order=1, action="navigate", target="Search", value="", expected="Opens"),
                    GeneratedTestStep(order=2, action="tap", target="btn", value="", expected="Clicked"),
                ],
            ),
        ],
        execution_results=[
            TestExecutionResult(
                test_id="test_abc_Search_1", status="passed",
                duration_ms=5000, failure_reason="",
                steps_completed=2, steps_total=2,
            ),
        ],
        metrics=AggregateMetrics(
            total_prs=1, total_files_changed=3,
            changes_by_category={"ui": 1, "logic": 2},
            screens_affected=1, tests_generated=1,
            tests_passed=1, tests_failed=0, tests_skipped=0,
            pass_rate=100.0,
        ),
    )
    defaults.update(overrides)
    return ReportData(**defaults)


class TestRenderReport:
    def test_valid_html_structure(self):
        html = render_report(_make_report())
        assert html.startswith("<!DOCTYPE html>")
        assert "<html" in html
        assert "</html>" in html
        assert "<head>" in html
        assert "</head>" in html
        assert "<body>" in html
        assert "</body>" in html

    def test_self_contained_no_external_urls(self):
        html = render_report(_make_report())
        # Should not contain external stylesheet or script URLs
        assert "http://" not in html
        assert "https://" not in html

    def test_contains_inline_css(self):
        html = render_report(_make_report())
        assert "<style>" in html
        assert "var(--bg)" in html

    def test_contains_inline_js(self):
        html = render_report(_make_report())
        assert "<script>" in html
        assert "collapsible" in html

    def test_contains_header_section(self):
        html = render_report(_make_report())
        assert "TestApp" in html
        assert "test-report-001" in html
        assert "abc1234" in html

    def test_contains_metrics_section(self):
        html = render_report(_make_report())
        assert "PRs Analyzed" in html
        assert "Files Changed" in html
        assert "Screens Affected" in html
        assert "Tests Generated" in html
        assert "Pass Rate" in html
        assert "100.0%" in html

    def test_contains_pr_table(self):
        html = render_report(_make_report())
        assert "PR Summary" in html
        assert "Fix search bug" in html
        assert "alice" in html

    def test_contains_analyzer_details(self):
        html = render_report(_make_report())
        assert "Analyzer Details" in html
        assert "SearchFragment.kt" in html
        assert "bug_fix" in html

    def test_contains_test_generation(self):
        html = render_report(_make_report())
        assert "Generated Tests" in html
        assert "Test Search flow" in html
        assert "navigate" in html

    def test_contains_execution_results(self):
        html = render_report(_make_report())
        assert "Test Execution" in html
        assert "passed" in html
        assert "5000ms" in html

    def test_contains_date_filter(self):
        html = render_report(_make_report())
        assert 'id="filter-from"' in html
        assert 'id="filter-to"' in html
        assert 'id="filter-reset"' in html
        assert "date-filter" in html

    def test_filterable_elements_have_data_attributes(self):
        html = render_report(_make_report())
        assert 'data-pr-ref="abc1234"' in html
        assert 'data-exec-pr="abc1234"' in html

    def test_embedded_json(self):
        html = render_report(_make_report())
        assert 'id="report-data"' in html
        assert 'application/json' in html
        # Extract and parse the embedded JSON
        start = html.index('id="report-data">') + len('id="report-data">')
        end = html.index("</script>", start)
        embedded = html[start:end].strip()
        data = json.loads(embedded)
        assert data["report_id"] == "test-report-001"
        assert data["app_name"] == "TestApp"

    def test_html_escaping(self):
        report = _make_report(app_name="App <script>alert('xss')</script>")
        html = render_report(report)
        # The title and header should use escaped HTML
        assert "&lt;script&gt;" in html
        # The embedded JSON should escape </script> to prevent tag injection
        assert "</script>alert" not in html

    def test_empty_report(self):
        report = _make_report(
            pr_summaries=[], analyzer_results=[],
            generated_tests=[], execution_results=[],
        )
        html = render_report(report)
        assert "No PRs analyzed" in html
        assert "No analysis results" in html
        assert "No tests generated" in html
        assert "No execution results" in html


class TestRenderIndex:
    def test_valid_html(self):
        entries = [
            ReportIndexEntry(
                report_id="r1", generated_at="2026-02-27",
                total_prs=3, screens_affected=2, tests_generated=5,
                pass_rate=80.0, report_path="r1/report.html", json_path="r1/report.json",
            ),
        ]
        html = render_index(entries, "TestApp")
        assert "<!DOCTYPE html>" in html
        assert "Report History" in html
        assert "r1" in html
        assert "80.0%" in html

    def test_empty_index(self):
        html = render_index([], "TestApp")
        assert "Report History" in html

    def test_self_contained(self):
        html = render_index([], "TestApp")
        assert "http://" not in html
        assert "https://" not in html
