"""Tests for analyzer.profile_updater module."""

import yaml
from pathlib import Path

from apptest.analyzer.profile_updater import (
    _remove_deleted_file,
    _upsert_screen,
    _update_chains_for_file,
    update_profile_from_analysis,
)
from apptest.scanner.profile_manager import load_profile, save_profile


MOCK_REPO = str(Path(__file__).parent / "fixtures" / "mock_repo")
SOURCE_ROOT = "app/src/main/java"


def _make_auto() -> dict:
    return {
        "screens": [
            {
                "name": "SearchFragment",
                "file": "app/src/main/java/org/wikipedia/search/SearchFragment.kt",
                "type": "fragment",
            },
            {
                "name": "PageActivity",
                "file": "app/src/main/java/org/wikipedia/page/PageActivity.kt",
                "type": "activity",
            },
        ],
        "chains": [
            {
                "screen_name": "SearchFragment",
                "screen_file": "app/src/main/java/org/wikipedia/search/SearchFragment.kt",
                "confidence": "high",
                "members": [
                    "app/src/main/java/org/wikipedia/search/SearchApi.kt",
                    "app/src/main/java/org/wikipedia/search/SearchRepository.kt",
                    "app/src/main/java/org/wikipedia/search/SearchViewModel.kt",
                    "app/src/main/java/org/wikipedia/search/SearchFragment.kt",
                ],
            },
        ],
    }


class TestRemoveDeletedFile:
    def test_removes_from_screens(self):
        auto = _make_auto()
        _remove_deleted_file(auto, "app/src/main/java/org/wikipedia/page/PageActivity.kt")
        names = [s["name"] for s in auto["screens"]]
        assert "PageActivity" not in names
        assert "SearchFragment" in names

    def test_removes_screen_chain(self):
        auto = _make_auto()
        _remove_deleted_file(auto, "app/src/main/java/org/wikipedia/search/SearchFragment.kt")
        # Chain for SearchFragment should be removed since screen was deleted
        assert len(auto["chains"]) == 0

    def test_removes_from_chain_members(self):
        auto = _make_auto()
        _remove_deleted_file(auto, "app/src/main/java/org/wikipedia/search/SearchApi.kt")
        chain = auto["chains"][0]
        assert "app/src/main/java/org/wikipedia/search/SearchApi.kt" not in chain["members"]
        # Other members should remain
        assert len(chain["members"]) == 3


class TestUpsertScreen:
    def test_adds_new_screen(self):
        auto = _make_auto()
        content = "class NewFragment : Fragment() {"
        _upsert_screen(
            auto,
            "app/src/main/java/org/wikipedia/new/NewFragment.kt",
            content,
            MOCK_REPO,
        )
        names = [s["name"] for s in auto["screens"]]
        assert "NewFragment" in names
        assert len(auto["screens"]) == 3

    def test_updates_existing_screen(self):
        auto = _make_auto()
        content = "class SearchFragment : Fragment() {"
        _upsert_screen(
            auto,
            "app/src/main/java/org/wikipedia/search/SearchFragment.kt",
            content,
            MOCK_REPO,
        )
        # Should still have same count, not duplicate
        assert len(auto["screens"]) == 2


class TestUpdateChainsForFile:
    def test_updates_existing_member_path(self):
        auto = _make_auto()
        _update_chains_for_file(
            auto, "SearchRepository",
            "app/src/main/java/org/wikipedia/search/SearchRepository.kt",
            MOCK_REPO, SOURCE_ROOT, ["build", ".gradle", "test"],
        )
        # Member should still be in chain
        chain = auto["chains"][0]
        assert "app/src/main/java/org/wikipedia/search/SearchRepository.kt" in chain["members"]


class TestUpdateProfileFromAnalysis:
    def test_preserves_overrides(self, tmp_path):
        """Overrides section must never be modified by auto-update."""
        # Set up a mock repo structure within tmp_path
        profile = {
            "auto": _make_auto(),
            "overrides": {"ignore": ["some/file.kt"]},
        }
        save_profile(tmp_path, profile)

        # Pretend to analyze (no actual files in tmp_path, so no updates)
        update_profile_from_analysis(
            tmp_path,
            changed_files=[],
            repo_path=tmp_path,
            source_root=SOURCE_ROOT,
        )

        loaded = load_profile(tmp_path)
        assert loaded["overrides"]["ignore"] == ["some/file.kt"]

    def test_updates_timestamp(self, tmp_path):
        profile = {"auto": _make_auto()}
        save_profile(tmp_path, profile)

        update_profile_from_analysis(
            tmp_path,
            changed_files=[],
            repo_path=tmp_path,
            source_root=SOURCE_ROOT,
        )

        loaded = load_profile(tmp_path)
        assert "updated_at" in loaded["auto"]

    def test_removes_deleted_file(self, tmp_path):
        profile = {"auto": _make_auto()}
        save_profile(tmp_path, profile)

        # Pretend PageActivity.kt was deleted (file doesn't exist in tmp_path)
        update_profile_from_analysis(
            tmp_path,
            changed_files=["app/src/main/java/org/wikipedia/page/PageActivity.kt"],
            repo_path=tmp_path,
            source_root=SOURCE_ROOT,
        )

        loaded = load_profile(tmp_path)
        screen_names = [s["name"] for s in loaded["auto"]["screens"]]
        assert "PageActivity" not in screen_names
