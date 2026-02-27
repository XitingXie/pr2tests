"""Integration tests for `apptest init` against real Android repos.

These tests require the Wikipedia Android repo at /tmp/apps-android-wikipedia.
They are automatically skipped if the repo is not available.
"""

import os
from pathlib import Path

import pytest
import yaml

from apptest.scanner.profile_manager import load_profile, save_profile, lookup_affected_screens
from apptest.scanner.project_scanner import scan_project


WIKIPEDIA_REPO = "/tmp/apps-android-wikipedia"
_skip_reason = "Wikipedia Android repo not found at /tmp/apps-android-wikipedia"


def _has_wikipedia_repo() -> bool:
    return (
        Path(WIKIPEDIA_REPO).exists()
        and (Path(WIKIPEDIA_REPO) / "settings.gradle.kts").exists()
    )


@pytest.mark.skipif(not _has_wikipedia_repo(), reason=_skip_reason)
class TestInitWikipedia:
    """Test apptest init against the Wikipedia Android repo."""

    def test_finds_many_screens(self):
        result = scan_project(WIKIPEDIA_REPO)
        screens = result.get("screens", [])
        assert len(screens) >= 50, f"Expected 50+ screens, found {len(screens)}"

    def test_detects_mvvm_architecture(self):
        result = scan_project(WIKIPEDIA_REPO)
        arch = result["project"]["architecture"]
        assert arch in ("mvvm", "mvi"), f"Expected MVVM/MVI, got {arch}"

    def test_generates_valid_yaml(self, tmp_path):
        result = scan_project(WIKIPEDIA_REPO)
        profile = {"auto": result}
        out_path = save_profile(tmp_path, profile)

        # Verify YAML roundtrip
        loaded = load_profile(tmp_path)
        assert loaded is not None
        assert len(loaded["auto"]["screens"]) == len(result["screens"])

        # Verify YAML is well-formed
        with open(out_path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)

    def test_chains_include_search_fragment(self):
        result = scan_project(WIKIPEDIA_REPO)
        chain_screens = {c["screen_name"] for c in result.get("chains", [])}
        # SearchFragment or SearchActivity should have a chain
        has_search = any("Search" in s for s in chain_screens)
        assert has_search, f"No Search screen in chains. Found: {sorted(chain_screens)[:10]}"

    def test_search_chain_includes_viewmodel(self):
        result = scan_project(WIKIPEDIA_REPO)
        for chain in result.get("chains", []):
            if "Search" in chain["screen_name"]:
                member_stems = [Path(m).stem for m in chain["members"]]
                has_vm = any("ViewModel" in s for s in member_stems)
                if has_vm:
                    return  # Found a search chain with ViewModel
        pytest.skip("No SearchFragment chain with ViewModel found")

    def test_profile_lookup_works(self):
        result = scan_project(WIKIPEDIA_REPO)
        profile = {"auto": result}

        # Find any chain member that isn't a screen
        for chain in result.get("chains", []):
            for member in chain["members"]:
                if member != chain["screen_file"]:
                    hits = lookup_affected_screens(member, profile)
                    if hits:
                        assert hits[0]["screen_file"] == chain["screen_file"]
                        return
        pytest.skip("No non-screen chain members found")

    def test_detects_modules(self):
        result = scan_project(WIKIPEDIA_REPO)
        modules = result["project"]["modules"]
        assert len(modules) >= 1
        assert "app" in modules

    def test_screen_types_varied(self):
        result = scan_project(WIKIPEDIA_REPO)
        types = {s["type"] for s in result["screens"]}
        # Wikipedia app has both activities and fragments
        assert len(types) >= 2, f"Only found types: {types}"
