"""Tests for apptest.run_manager."""

import re
from pathlib import Path

import pytest

from apptest.run_manager import _slugify, build_run_id, create_run_dir, get_latest_run


class TestSlugify:
    def test_lowercase(self):
        assert _slugify("Wikipedia") == "wikipedia"

    def test_spaces_to_hyphens(self):
        assert _slugify("My Cool App") == "my-cool-app"

    def test_special_chars(self):
        assert _slugify("app@v2.0!") == "app-v2-0"

    def test_strips_leading_trailing(self):
        assert _slugify("  hello  ") == "hello"


class TestBuildRunId:
    def test_format(self):
        rid = build_run_id("Wikipedia")
        # e.g. wikipedia_20260227-100500
        assert re.match(r"^wikipedia_\d{8}-\d{6}$", rid)

    def test_spaces_in_name(self):
        rid = build_run_id("My App")
        assert rid.startswith("my-app_")


class TestCreateRunDir:
    def test_creates_dir_and_pointer(self, tmp_path):
        base = tmp_path / "runs"
        run_dir = create_run_dir("Wikipedia", base=base)

        assert run_dir.is_dir()
        assert run_dir.parent == base

        pointer = base.parent / "latest-run"
        assert pointer.exists()
        assert pointer.read_text() == run_dir.name

    def test_successive_runs_update_pointer(self, tmp_path, monkeypatch):
        """Two runs with different timestamps produce different dirs; pointer updates."""
        import apptest.run_manager as rm

        call_count = 0
        original = rm.datetime

        class FakeDatetime:
            @staticmethod
            def now():
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return original(2026, 2, 27, 10, 5, 0)
                return original(2026, 2, 27, 14, 30, 22)

        monkeypatch.setattr(rm, "datetime", FakeDatetime)

        base = tmp_path / "runs"
        run1 = create_run_dir("App", base=base)
        run2 = create_run_dir("App", base=base)

        assert run1 != run2
        pointer = base.parent / "latest-run"
        assert pointer.read_text() == run2.name


class TestGetLatestRun:
    def test_returns_none_when_no_pointer(self, tmp_path):
        assert get_latest_run(base=tmp_path) is None

    def test_returns_none_when_pointer_empty(self, tmp_path):
        (tmp_path / "latest-run").write_text("")
        assert get_latest_run(base=tmp_path) is None

    def test_returns_none_when_dir_missing(self, tmp_path):
        (tmp_path / "latest-run").write_text("nonexistent_run")
        assert get_latest_run(base=tmp_path) is None

    def test_returns_run_dir(self, tmp_path):
        run_id = "wikipedia_20260227-100500"
        run_dir = tmp_path / "runs" / run_id
        run_dir.mkdir(parents=True)
        (tmp_path / "latest-run").write_text(run_id)

        result = get_latest_run(base=tmp_path)
        assert result == run_dir

    def test_roundtrip_with_create(self, tmp_path):
        base = tmp_path / "runs"
        created = create_run_dir("Wikipedia", base=base)
        found = get_latest_run(base=tmp_path)
        assert found == created
