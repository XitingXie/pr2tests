"""Tests for report_index module."""

import json
from pathlib import Path

from apptest.reporter.report_index import (
    add_to_index,
    apply_retention,
    load_index,
    write_index,
)
from apptest.reporter.report_schema import (
    AggregateMetrics,
    ReportData,
    ReportIndexEntry,
    TriggerInfo,
)


def _make_entry(report_id: str, generated_at: str = "2026-02-27") -> ReportIndexEntry:
    return ReportIndexEntry(
        report_id=report_id,
        generated_at=generated_at,
        total_prs=1,
        screens_affected=2,
        tests_generated=3,
        pass_rate=80.0,
        report_path=f"{report_id}/report.html",
        json_path=f"{report_id}/report.json",
    )


def _make_report(report_id: str = "r1") -> ReportData:
    return ReportData(
        report_id=report_id,
        generated_at="2026-02-27T10:00:00",
        app_name="TestApp",
        version_info="abc (2026-02-27)",
        trigger=TriggerInfo(mode="manual", commit_range="a..b", description="test"),
        metrics=AggregateMetrics(
            total_prs=1, total_files_changed=3,
            screens_affected=2, tests_generated=3,
            pass_rate=80.0,
        ),
    )


class TestLoadIndex:
    def test_load_missing(self, tmp_path):
        entries = load_index(tmp_path)
        assert entries == []

    def test_load_existing(self, tmp_path):
        data = [
            {
                "report_id": "r1", "generated_at": "2026-02-27",
                "total_prs": 1, "screens_affected": 2, "tests_generated": 3,
                "pass_rate": 80.0, "report_path": "r1/report.html", "json_path": "r1/report.json",
            },
        ]
        (tmp_path / "index.json").write_text(json.dumps(data))
        entries = load_index(tmp_path)
        assert len(entries) == 1
        assert entries[0].report_id == "r1"


class TestApplyRetention:
    def test_under_limit(self):
        entries = [_make_entry("r1"), _make_entry("r2")]
        result = apply_retention(entries, 5)
        assert len(result) == 2

    def test_at_limit(self):
        entries = [_make_entry("r1"), _make_entry("r2")]
        result = apply_retention(entries, 2)
        assert len(result) == 2

    def test_over_limit_removes_oldest(self):
        entries = [
            _make_entry("r1", "2026-02-25"),
            _make_entry("r2", "2026-02-26"),
            _make_entry("r3", "2026-02-27"),
        ]
        result = apply_retention(entries, 2)
        assert len(result) == 2
        assert result[0].report_id == "r2"
        assert result[1].report_id == "r3"

    def test_deletes_old_directories(self, tmp_path):
        # Create a directory for old report
        (tmp_path / "r1").mkdir()
        (tmp_path / "r1" / "report.html").write_text("old")

        entries = [
            _make_entry("r1", "2026-02-25"),
            _make_entry("r2", "2026-02-27"),
        ]
        result = apply_retention(entries, 1, output_dir=tmp_path)
        assert len(result) == 1
        assert result[0].report_id == "r2"
        assert not (tmp_path / "r1").exists()


class TestWriteIndex:
    def test_writes_json_and_html(self, tmp_path):
        entries = [_make_entry("r1")]
        write_index(tmp_path, entries, "TestApp")

        assert (tmp_path / "index.json").exists()
        assert (tmp_path / "index.html").exists()

        # Verify JSON
        data = json.loads((tmp_path / "index.json").read_text())
        assert len(data) == 1
        assert data[0]["report_id"] == "r1"

        # Verify HTML
        html = (tmp_path / "index.html").read_text()
        assert "TestApp" in html
        assert "r1" in html


class TestAddToIndex:
    def test_adds_new_entry(self, tmp_path):
        report = _make_report("r1")
        entries = add_to_index(
            tmp_path, report, "r1/report.html", "r1/report.json",
            max_reports=10, app_name="TestApp",
        )
        assert len(entries) == 1
        assert entries[0].report_id == "r1"
        assert (tmp_path / "index.json").exists()
        assert (tmp_path / "index.html").exists()

    def test_appends_to_existing(self, tmp_path):
        add_to_index(tmp_path, _make_report("r1"), "r1/report.html", "r1/report.json", app_name="App")
        entries = add_to_index(tmp_path, _make_report("r2"), "r2/report.html", "r2/report.json", app_name="App")
        assert len(entries) == 2

    def test_applies_retention(self, tmp_path):
        add_to_index(tmp_path, _make_report("r1"), "r1/report.html", "r1/report.json", max_reports=1, app_name="App")
        entries = add_to_index(tmp_path, _make_report("r2"), "r2/report.html", "r2/report.json", max_reports=1, app_name="App")
        assert len(entries) == 1
        assert entries[0].report_id == "r2"
