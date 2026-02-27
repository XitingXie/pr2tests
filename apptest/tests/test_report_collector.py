"""Tests for report_collector module."""

import json
import subprocess
from pathlib import Path

import pytest

from apptest.reporter.report_collector import (
    collect_prs_last_n,
    collect_prs_manual,
    collect_prs_since,
    get_version_info,
    load_state,
    save_state,
    update_state,
)


def _init_repo(tmp_path: Path) -> Path:
    """Create a git repo with a few commits."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True, check=True)

    # Create commits
    for i in range(5):
        (repo / f"file{i}.txt").write_text(f"content {i}")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"Commit {i}: Add file{i}.txt"],
            cwd=repo, capture_output=True, check=True,
        )

    return repo


class TestCollectManual:
    def test_collects_commits_in_range(self, tmp_path):
        repo = _init_repo(tmp_path)
        # Get the range: all commits except the first
        log = subprocess.run(
            ["git", "log", "--oneline", "-n5"],
            cwd=repo, capture_output=True, text=True, check=True,
        )
        lines = log.stdout.strip().splitlines()
        newest = lines[0].split()[0]
        oldest = lines[-1].split()[0]

        prs = collect_prs_manual(repo, f"{oldest}..{newest}")
        # Should have 4 commits (5 total minus the oldest endpoint)
        assert len(prs) == 4
        assert all(pr.ref for pr in prs)
        assert all(pr.title for pr in prs)

    def test_empty_range(self, tmp_path):
        repo = _init_repo(tmp_path)
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo, capture_output=True, text=True, check=True,
        ).stdout.strip()
        prs = collect_prs_manual(repo, f"{head}..{head}")
        assert len(prs) == 0


class TestCollectSince:
    def test_collects_since_past(self, tmp_path):
        repo = _init_repo(tmp_path)
        # All commits are recent, so "since yesterday" should get them
        prs = collect_prs_since(repo, "2020-01-01")
        assert len(prs) == 5

    def test_collects_since_future(self, tmp_path):
        repo = _init_repo(tmp_path)
        prs = collect_prs_since(repo, "2099-01-01")
        assert len(prs) == 0


class TestCollectLastN:
    def test_collects_last_3(self, tmp_path):
        repo = _init_repo(tmp_path)
        prs = collect_prs_last_n(repo, 3)
        assert len(prs) == 3

    def test_collects_more_than_available(self, tmp_path):
        repo = _init_repo(tmp_path)
        prs = collect_prs_last_n(repo, 100)
        assert len(prs) == 5


class TestVersionInfo:
    def test_returns_version_string(self, tmp_path):
        repo = _init_repo(tmp_path)
        info = get_version_info(repo)
        assert info  # Non-empty
        assert "(" in info  # Contains date in parens


class TestState:
    def test_save_and_load(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        save_state(repo, {"last_report_timestamp": "2026-02-27", "foo": "bar"})
        state = load_state(repo)
        assert state["last_report_timestamp"] == "2026-02-27"
        assert state["foo"] == "bar"

    def test_load_missing(self, tmp_path):
        state = load_state(tmp_path)
        assert state == {}

    def test_update_state(self, tmp_path):
        repo = _init_repo(tmp_path)
        update_state(repo)
        state = load_state(repo)
        assert "last_report_timestamp" in state
        assert "last_reported_commit" in state


class TestPRSummaryFields:
    def test_has_file_stats(self, tmp_path):
        repo = _init_repo(tmp_path)
        prs = collect_prs_last_n(repo, 1)
        assert len(prs) == 1
        pr = prs[0]
        assert pr.files_changed >= 0
        assert pr.insertions >= 0
        assert pr.deletions >= 0
        assert pr.author == "Test"
