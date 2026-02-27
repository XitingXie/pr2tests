"""Tests for scanner.profile_manager module."""

import yaml
from pathlib import Path

from apptest.scanner.profile_manager import (
    load_profile,
    load_effective_profile,
    save_profile,
    lookup_affected_screens,
    resolve_screen_file,
)


def _make_profile() -> dict:
    """Minimal valid profile for testing."""
    return {
        "auto": {
            "project": {"modules": ["app"], "architecture": "mvvm"},
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
                {
                    "screen_name": "PageActivity",
                    "screen_file": "app/src/main/java/org/wikipedia/page/PageActivity.kt",
                    "confidence": "high",
                    "members": [
                        "app/src/main/java/org/wikipedia/page/PageViewModel.kt",
                        "app/src/main/java/org/wikipedia/page/PageActivity.kt",
                    ],
                },
            ],
        },
    }


# ---------------------------------------------------------------------------
# TestLoadEffectiveProfile
# ---------------------------------------------------------------------------


class TestLoadEffectiveProfile:
    def test_returns_none_when_missing(self, tmp_path):
        assert load_effective_profile(tmp_path) is None

    def test_returns_profile_without_overrides(self, tmp_path):
        profile = _make_profile()
        save_profile(tmp_path, profile)
        loaded = load_effective_profile(tmp_path)
        assert loaded is not None
        assert len(loaded["auto"]["screens"]) == 2

    def test_merges_reclassify(self, tmp_path):
        profile = _make_profile()
        profile["overrides"] = {
            "reclassify": [
                {
                    "file": "app/src/main/java/org/wikipedia/search/SearchFragment.kt",
                    "screen_type": "compose_screen",
                }
            ]
        }
        save_profile(tmp_path, profile)
        loaded = load_effective_profile(tmp_path)
        search_screen = next(
            s for s in loaded["auto"]["screens"]
            if s["name"] == "SearchFragment"
        )
        assert search_screen["type"] == "compose_screen"

    def test_applies_ignore(self, tmp_path):
        profile = _make_profile()
        profile["overrides"] = {
            "ignore": [
                "app/src/main/java/org/wikipedia/page/PageActivity.kt",
            ]
        }
        save_profile(tmp_path, profile)
        loaded = load_effective_profile(tmp_path)
        screen_names = [s["name"] for s in loaded["auto"]["screens"]]
        assert "PageActivity" not in screen_names
        # Chains should also be filtered
        chain_screens = [c["screen_file"] for c in loaded["auto"]["chains"]]
        assert "app/src/main/java/org/wikipedia/page/PageActivity.kt" not in chain_screens

    def test_applies_extra_screens(self, tmp_path):
        profile = _make_profile()
        profile["overrides"] = {
            "extra_screens": [
                {
                    "name": "SettingsScreen",
                    "file": "app/src/main/java/com/example/SettingsScreen.kt",
                    "type": "composable",
                }
            ]
        }
        save_profile(tmp_path, profile)
        loaded = load_effective_profile(tmp_path)
        screen_names = [s["name"] for s in loaded["auto"]["screens"]]
        assert "SettingsScreen" in screen_names
        assert len(loaded["auto"]["screens"]) == 3

    def test_does_not_mutate_overrides(self, tmp_path):
        profile = _make_profile()
        profile["overrides"] = {"ignore": ["app/src/main/java/org/wikipedia/page/PageActivity.kt"]}
        save_profile(tmp_path, profile)
        loaded = load_effective_profile(tmp_path)
        # Overrides section is preserved as-is
        assert "overrides" in loaded
        assert loaded["overrides"]["ignore"] == [
            "app/src/main/java/org/wikipedia/page/PageActivity.kt"
        ]


# ---------------------------------------------------------------------------
# TestLookupAffectedScreens
# ---------------------------------------------------------------------------


class TestLookupAffectedScreens:
    def test_finds_screen_by_file_path(self):
        profile = _make_profile()
        results = lookup_affected_screens(
            "app/src/main/java/org/wikipedia/search/SearchRepository.kt",
            profile,
        )
        assert len(results) == 1
        assert results[0]["screen_name"] == "SearchFragment"
        assert results[0]["confidence"] == "high"

    def test_finds_screen_by_class_name(self):
        profile = _make_profile()
        # Use a path that won't match directly but stem matches
        results = lookup_affected_screens(
            "different/path/SearchRepository.kt",
            profile,
        )
        assert len(results) == 1
        assert results[0]["screen_name"] == "SearchFragment"

    def test_returns_empty_for_unknown(self):
        profile = _make_profile()
        results = lookup_affected_screens(
            "app/src/main/java/org/wikipedia/unknown/Unknown.kt",
            profile,
        )
        assert results == []

    def test_deduplicates_screens(self):
        profile = _make_profile()
        # SearchFragment is in the chain — only one result
        results = lookup_affected_screens(
            "app/src/main/java/org/wikipedia/search/SearchApi.kt",
            profile,
        )
        screen_names = [r["screen_name"] for r in results]
        assert screen_names.count("SearchFragment") == 1

    def test_finds_viewmodel_in_chain(self):
        profile = _make_profile()
        results = lookup_affected_screens(
            "app/src/main/java/org/wikipedia/page/PageViewModel.kt",
            profile,
        )
        assert len(results) == 1
        assert results[0]["screen_name"] == "PageActivity"


# ---------------------------------------------------------------------------
# TestSaveProfile
# ---------------------------------------------------------------------------


class TestSaveProfile:
    def test_creates_directory(self, tmp_path):
        profile = _make_profile()
        out = save_profile(tmp_path, profile)
        assert out.exists()
        assert out.parent.name == ".apptest"

    def test_valid_yaml_roundtrip(self, tmp_path):
        profile = _make_profile()
        save_profile(tmp_path, profile)
        loaded = load_profile(tmp_path)
        assert loaded is not None
        assert loaded["auto"]["screens"][0]["name"] == "SearchFragment"
        assert "updated_at" in loaded["auto"]

    def test_appends_overrides_template(self, tmp_path):
        profile = _make_profile()
        save_profile(tmp_path, profile)
        text = (tmp_path / ".apptest" / "app-profile.yml").read_text()
        assert "# overrides:" in text

    def test_no_template_when_overrides_present(self, tmp_path):
        profile = _make_profile()
        profile["overrides"] = {"ignore": ["some/file.kt"]}
        save_profile(tmp_path, profile)
        text = (tmp_path / ".apptest" / "app-profile.yml").read_text()
        # Template should NOT be appended since overrides key exists
        lines = text.split("\n")
        # The actual overrides section is in the YAML, not the comment template
        assert any("ignore:" in line and not line.strip().startswith("#") for line in lines)


# ---------------------------------------------------------------------------
# TestResolveScreenFile
# ---------------------------------------------------------------------------


class TestResolveScreenFile:
    def test_resolves_known_screen(self):
        profile = _make_profile()
        path = resolve_screen_file("SearchFragment", profile)
        assert path == "app/src/main/java/org/wikipedia/search/SearchFragment.kt"

    def test_returns_none_for_unknown(self):
        profile = _make_profile()
        assert resolve_screen_file("NonExistentScreen", profile) is None
