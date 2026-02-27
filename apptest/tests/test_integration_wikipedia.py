"""Integration tests against real Wikipedia Android repo.

These tests require the Wikipedia Android repo to be cloned at
/tmp/apps-android-wikipedia. Skip gracefully if not available.

To set up:
    git clone --depth 200 https://github.com/wikimedia/apps-android-wikipedia.git /tmp/apps-android-wikipedia

Results are written to .apptest/integration/ for inspection and
downstream use by `apptest generate`.
"""

import json
from pathlib import Path

import pytest

from apptest.analyzer.context_builder import build_context, write_analysis
from apptest.analyzer.diff_parser import parse_diff
from apptest.analyzer.manifest_parser import parse_manifest

WIKI_REPO = Path("/tmp/apps-android-wikipedia")
SOURCE_ROOT = "app/src/main/java/org/wikipedia"
LAYOUTS_DIR = "app/src/main/res/layout"
STRINGS_FILE = "app/src/main/res/values/strings.xml"
MANIFEST = "app/src/main/AndroidManifest.xml"
EXCLUDE_DIRS = ["build", ".gradle", "test", "androidTest"]

# Persistent output directory for integration test results
OUTPUT_DIR = Path(__file__).resolve().parents[2] / ".apptest" / "integration"

skip_no_repo = pytest.mark.skipif(
    not WIKI_REPO.exists(),
    reason="Wikipedia Android repo not cloned at /tmp/apps-android-wikipedia",
)


def _run_analysis(diff_ref: str):
    """Run the full pipeline on a Wikipedia diff."""
    changed_files = parse_diff(WIKI_REPO, diff_ref, filter_relevant=False)
    manifest_path = WIKI_REPO / MANIFEST
    activities = parse_manifest(manifest_path, namespace="org.wikipedia") if manifest_path.exists() else []
    return build_context(
        changed_files=changed_files,
        activities=activities,
        repo_path=WIKI_REPO,
        source_root=SOURCE_ROOT,
        layouts_dir=LAYOUTS_DIR,
        strings_file=STRINGS_FILE,
        exclude_dirs=EXCLUDE_DIRS,
        app_name="Wikipedia",
        app_package="org.wikipedia",
        diff_ref=diff_ref,
    )


def _write_result(result, name: str) -> Path:
    """Write analysis result to persistent output directory."""
    out_dir = OUTPUT_DIR / name
    return write_analysis(result, out_dir)


@skip_no_repo
class TestSmallSearchPR:
    """PR #6350: Show keyboard when showing no results (3 files)."""

    @classmethod
    def setup_class(cls):
        cls.result = _run_analysis("9512546..4778ade")
        cls.output_path = _write_result(cls.result, "pr6350-search-keyboard")

    def test_correct_file_count(self):
        assert self.result.total_changed_files == 3

    def test_all_logic_changes(self):
        assert len(self.result.ui_changes) == 0
        assert len(self.result.logic_changes) == 3
        assert len(self.result.test_changes) == 0
        assert len(self.result.infra_changes) == 0

    def test_search_results_fragment_is_screen(self):
        frag = next(
            lc for lc in self.result.logic_changes
            if "SearchResultsFragment" in lc.file
        )
        assert frag.type == "logic_screen"
        assert frag.trace_confidence == "high"

    def test_search_results_screen_is_compose_screen(self):
        screen = next(
            lc for lc in self.result.logic_changes
            if "SearchResultsScreen" in lc.file
        )
        assert screen.type == "logic_compose_screen"
        assert any("SearchResultsFragment" in s for s in screen.affected_screens)

    def test_device_util_narrowed_to_pr_screen(self):
        util = next(
            lc for lc in self.result.logic_changes
            if "DeviceUtil" in lc.file
        )
        assert util.type == "logic_util"
        # Should narrow to PR-relevant screens, not 20
        assert len(util.affected_screens) <= 5
        assert any("SearchResultsFragment" in s for s in util.affected_screens)

    def test_logic_changes_have_source(self):
        for lc in self.result.logic_changes:
            assert len(lc.full_source) > 0

    def test_activities_found(self):
        assert len(self.result.all_activities) > 50


@skip_no_repo
class TestBigHybridSearchPR:
    """PR #6221: Hybrid search feature branch (55 files)."""

    @classmethod
    def setup_class(cls):
        cls.result = _run_analysis("af457ff^..af457ff")
        cls.output_path = _write_result(cls.result, "pr6221-hybrid-search")

    def test_correct_file_count(self):
        assert self.result.total_changed_files == 55

    def test_all_change_types_present(self):
        assert len(self.result.ui_changes) > 0
        assert len(self.result.logic_changes) > 0
        assert len(self.result.infra_changes) > 0

    def test_repository_traces_through_viewmodel_to_fragment(self):
        repo = next(
            lc for lc in self.result.logic_changes
            if "StandardSearchRepository" in lc.file
        )
        assert repo.type == "logic_repository"
        assert repo.trace_confidence == "high"
        assert len(repo.dependency_chain) == 3
        assert any("SearchResultsViewModel" in c for c in repo.dependency_chain)
        assert any("SearchResultsFragment" in s for s in repo.affected_screens)

    def test_viewmodel_traces_to_fragment(self):
        vm = next(
            lc for lc in self.result.logic_changes
            if "SearchResultsViewModel" in lc.file
        )
        assert vm.type == "logic_viewmodel"
        assert vm.trace_confidence == "high"
        assert any("SearchResultsFragment" in s for s in vm.affected_screens)

    def test_screen_files_have_high_confidence(self):
        screens = [lc for lc in self.result.logic_changes if lc.type == "logic_screen"]
        assert len(screens) >= 5
        for s in screens:
            assert s.trace_confidence == "high"

    def test_new_features_detected(self):
        new_features = [lc for lc in self.result.logic_changes if lc.change_nature == "new_feature"]
        assert len(new_features) >= 10

    def test_manifest_is_infra(self):
        manifests = [ic for ic in self.result.infra_changes if ic.type == "infra_manifest"]
        assert len(manifests) == 1

    def test_layout_changes_detected(self):
        layouts = [uc for uc in self.result.ui_changes if uc.type == "ui_layout"]
        assert len(layouts) >= 1

    def test_screen_context_has_source(self):
        """Logic changes with traced screens should include screen source code."""
        for lc in self.result.logic_changes:
            for sc in lc.screen_context:
                assert len(sc.get("screen_source", "")) > 0

    def test_output_json_written(self):
        assert self.output_path.exists()
        data = json.loads(self.output_path.read_text())
        assert "ui_changes" in data
        assert "logic_changes" in data
        assert "test_changes" in data
        assert "infra_changes" in data
        assert "all_activities" in data

    def test_logic_other_rate_below_25_percent(self):
        """Most logic files should have a specific category, not logic_other."""
        logic = self.result.logic_changes
        other_count = sum(1 for lc in logic if lc.type == "logic_other")
        assert other_count / len(logic) < 0.25

    def test_compose_screens_classified(self):
        compose_screens = [lc for lc in self.result.logic_changes
                           if lc.type == "logic_compose_screen"]
        assert len(compose_screens) >= 1

    def test_abtest_files_classified(self):
        abtests = [lc for lc in self.result.logic_changes
                   if lc.type == "logic_abtest"]
        assert len(abtests) >= 1

    def test_utility_files_narrowed_to_pr_screens(self):
        """Utility files should not fan out to 10+ screens."""
        for lc in self.result.logic_changes:
            if lc.type in ("logic_util", "logic_config", "logic_extension"):
                assert len(lc.affected_screens) <= 5

    def test_compose_screen_traces_to_fragment(self):
        hybrid = next(
            lc for lc in self.result.logic_changes
            if "HybridSearchResultsScreen" in lc.file
        )
        assert hybrid.type == "logic_compose_screen"
        assert any("SearchResultsFragment" in s for s in hybrid.affected_screens)

    def test_few_zero_screen_files(self):
        """Most files should trace to at least one screen."""
        logic = self.result.logic_changes
        zero = sum(1 for lc in logic if not lc.affected_screens)
        assert zero <= 5
