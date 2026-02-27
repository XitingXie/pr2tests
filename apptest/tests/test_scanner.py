"""Tests for scanner.project_scanner module."""

from pathlib import Path

from apptest.scanner.project_scanner import (
    _detect_project_structure,
    _single_pass_scan,
    _trace_all_chains,
    _detect_navigation,
    detect_screen_type,
    is_screen_file,
    scan_project,
)


MOCK_REPO = str(Path(__file__).parent / "fixtures" / "mock_repo")


# ---------------------------------------------------------------------------
# TestDetectProjectStructure
# ---------------------------------------------------------------------------


class TestDetectProjectStructure:
    def test_finds_app_module(self):
        structure = _detect_project_structure(MOCK_REPO)
        assert "app" in structure["modules"]

    def test_finds_source_roots(self):
        structure = _detect_project_structure(MOCK_REPO)
        assert len(structure["source_roots"]) >= 1
        assert any("app/src/main/java" in r for r in structure["source_roots"])

    def test_finds_resource_roots(self):
        structure = _detect_project_structure(MOCK_REPO)
        assert len(structure["resource_roots"]) >= 1
        assert any("app/src/main/res" in r for r in structure["resource_roots"])

    def test_fallback_when_no_settings_gradle(self, tmp_path):
        (tmp_path / "app" / "build.gradle").parent.mkdir(parents=True)
        (tmp_path / "app" / "build.gradle").write_text("apply plugin: 'android'")
        structure = _detect_project_structure(tmp_path)
        assert "app" in structure["modules"]

    def test_empty_project(self, tmp_path):
        structure = _detect_project_structure(tmp_path)
        assert structure["modules"] == []


# ---------------------------------------------------------------------------
# TestSinglePassScan
# ---------------------------------------------------------------------------


class TestSinglePassScan:
    def test_discovers_screens(self):
        screens, _, _ = _single_pass_scan(["app/src/main/java"], MOCK_REPO)
        screen_names = [s["name"] for s in screens]
        assert "SearchFragment" in screen_names
        assert "PageActivity" in screen_names

    def test_detects_mvvm_architecture(self):
        _, arch_counts, _ = _single_pass_scan(["app/src/main/java"], MOCK_REPO)
        assert "mvvm" in arch_counts
        assert arch_counts["mvvm"] > 0

    def test_finds_viewmodels_not_as_screens(self):
        screens, _, _ = _single_pass_scan(["app/src/main/java"], MOCK_REPO)
        screen_names = [s["name"] for s in screens]
        # ViewModels should NOT be classified as screens
        assert "SearchViewModel" not in screen_names
        assert "PageViewModel" not in screen_names

    def test_screen_types_correct(self):
        screens, _, _ = _single_pass_scan(["app/src/main/java"], MOCK_REPO)
        by_name = {s["name"]: s for s in screens}
        assert by_name["SearchFragment"]["type"] == "fragment"
        assert by_name["PageActivity"]["type"] == "activity"


# ---------------------------------------------------------------------------
# TestScreenDetection
# ---------------------------------------------------------------------------


class TestScreenDetection:
    def test_fragment_detected(self):
        content = "class SearchFragment : Fragment() {"
        assert is_screen_file(content)
        assert detect_screen_type(content) == "fragment"

    def test_activity_detected(self):
        content = "class PageActivity : AppCompatActivity() {"
        assert is_screen_file(content)
        assert detect_screen_type(content) == "activity"

    def test_composable_detected(self):
        content = '@Composable\nfun HomeScreen(viewModel: HomeViewModel) {'
        assert is_screen_file(content)
        assert detect_screen_type(content) == "composable"

    def test_dialog_fragment_detected(self):
        content = "class ConfirmDialog : DialogFragment() {"
        assert is_screen_file(content)
        assert detect_screen_type(content) == "dialog_fragment"

    def test_bottom_sheet_detected(self):
        content = "class ShareSheet : BottomSheetDialogFragment() {"
        assert is_screen_file(content)
        assert detect_screen_type(content) == "bottom_sheet"

    def test_non_screen(self):
        content = "class SearchRepository(private val api: SearchApi) {"
        assert not is_screen_file(content)
        assert detect_screen_type(content) == "unknown"


# ---------------------------------------------------------------------------
# TestTraceAllChains
# ---------------------------------------------------------------------------


class TestTraceAllChains:
    def test_search_fragment_chain(self):
        screens = [
            {"name": "SearchFragment", "file": "app/src/main/java/org/wikipedia/search/SearchFragment.kt", "type": "fragment"},
        ]
        chains = _trace_all_chains(screens, MOCK_REPO, ["app/src/main/java"])
        assert len(chains) == 1
        chain = chains[0]
        assert chain["screen_name"] == "SearchFragment"
        # Chain should include at least the screen and viewmodel
        member_stems = [Path(m).stem for m in chain["members"]]
        assert "SearchFragment" in member_stems
        assert "SearchViewModel" in member_stems

    def test_page_activity_chain(self):
        screens = [
            {"name": "PageActivity", "file": "app/src/main/java/org/wikipedia/page/PageActivity.kt", "type": "activity"},
        ]
        chains = _trace_all_chains(screens, MOCK_REPO, ["app/src/main/java"])
        assert len(chains) == 1
        chain = chains[0]
        assert chain["screen_name"] == "PageActivity"
        member_stems = [Path(m).stem for m in chain["members"]]
        assert "PageActivity" in member_stems
        assert "PageViewModel" in member_stems

    def test_chain_has_repository(self):
        screens = [
            {"name": "SearchFragment", "file": "app/src/main/java/org/wikipedia/search/SearchFragment.kt", "type": "fragment"},
        ]
        chains = _trace_all_chains(screens, MOCK_REPO, ["app/src/main/java"])
        member_stems = [Path(m).stem for m in chains[0]["members"]]
        assert "SearchRepository" in member_stems


# ---------------------------------------------------------------------------
# TestDetectNavigation
# ---------------------------------------------------------------------------


class TestDetectNavigation:
    def test_no_navigation(self, tmp_path):
        nav = _detect_navigation(tmp_path, [])
        assert nav["type"] == "unknown"
        assert nav["nav_graphs"] == []
        assert nav["has_compose_nav"] is False


# ---------------------------------------------------------------------------
# TestScanProject (end-to-end on mock_repo)
# ---------------------------------------------------------------------------


class TestScanProject:
    def test_end_to_end(self):
        result = scan_project(MOCK_REPO)
        assert "project" in result
        assert "screens" in result
        assert "chains" in result

    def test_finds_modules(self):
        result = scan_project(MOCK_REPO)
        assert "app" in result["project"]["modules"]

    def test_finds_screens(self):
        result = scan_project(MOCK_REPO)
        screen_names = [s["name"] for s in result["screens"]]
        assert "SearchFragment" in screen_names
        assert "PageActivity" in screen_names

    def test_detects_architecture(self):
        result = scan_project(MOCK_REPO)
        assert result["project"]["architecture"] == "mvvm"

    def test_chains_built(self):
        result = scan_project(MOCK_REPO)
        assert len(result["chains"]) >= 2
        chain_screens = {c["screen_name"] for c in result["chains"]}
        assert "SearchFragment" in chain_screens
        assert "PageActivity" in chain_screens
