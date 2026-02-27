"""Tests for resource-to-screen tracing in context_builder."""

from pathlib import Path

from apptest.analyzer.context_builder import (
    _build_ui_context,
    _find_layouts_referencing_resource,
    _find_screens_for_layout,
    _trace_resource_to_screens,
)
from apptest.analyzer.change_classifier import ClassifiedFile
from apptest.analyzer.diff_parser import ChangedFile
from apptest.analyzer.strings_parser import parse_strings

MOCK_REPO = Path(__file__).parent / "fixtures" / "mock_repo"
SOURCE_ROOT = "app/src/main/java/org/wikipedia"
LAYOUTS_DIR = "app/src/main/res/layout"
STRINGS_FILE = "app/src/main/res/values/strings.xml"


class TestFindScreensForLayout:
    def test_finds_fragment_for_layout(self):
        screens = _find_screens_for_layout(
            "app/src/main/res/layout/fragment_search.xml",
            MOCK_REPO,
            SOURCE_ROOT,
        )
        assert len(screens) >= 1
        assert any("SearchFragment" in s for s in screens)

    def test_finds_activity_for_layout(self):
        screens = _find_screens_for_layout(
            "app/src/main/res/layout/activity_page.xml",
            MOCK_REPO,
            SOURCE_ROOT,
        )
        assert len(screens) >= 1
        assert any("PageActivity" in s for s in screens)

    def test_returns_empty_for_unmatched(self):
        screens = _find_screens_for_layout(
            "app/src/main/res/layout/item_row.xml",
            MOCK_REPO,
            SOURCE_ROOT,
        )
        assert screens == []


class TestFindLayoutsReferencingResource:
    def test_finds_layout_referencing_string(self):
        layouts = _find_layouts_referencing_resource(
            "search_hint", "string", MOCK_REPO, LAYOUTS_DIR,
        )
        assert any("fragment_search" in lp for lp in layouts)

    def test_finds_layout_referencing_drawable(self):
        layouts = _find_layouts_referencing_resource(
            "ic_search", "drawable", MOCK_REPO, LAYOUTS_DIR,
        )
        assert any("fragment_search" in lp for lp in layouts)

    def test_returns_empty_for_unknown_resource(self):
        layouts = _find_layouts_referencing_resource(
            "nonexistent_string", "string", MOCK_REPO, LAYOUTS_DIR,
        )
        assert layouts == []

    def test_returns_empty_for_missing_dir(self):
        layouts = _find_layouts_referencing_resource(
            "search_hint", "string", MOCK_REPO, "nonexistent/dir",
        )
        assert layouts == []


class TestTraceResourceToScreens:
    def test_traces_string_to_screen(self):
        screens = _trace_resource_to_screens(
            ["search_hint"], "string", MOCK_REPO, SOURCE_ROOT, LAYOUTS_DIR,
        )
        assert any("SearchFragment" in s for s in screens)

    def test_traces_drawable_to_screen(self):
        screens = _trace_resource_to_screens(
            ["ic_search"], "drawable", MOCK_REPO, SOURCE_ROOT, LAYOUTS_DIR,
        )
        assert any("SearchFragment" in s for s in screens)

    def test_deduplicates_screens(self):
        # Both resources live in fragment_search.xml → same screen
        screens = _trace_resource_to_screens(
            ["search_hint", "ic_search"], "string", MOCK_REPO, SOURCE_ROOT, LAYOUTS_DIR,
        )
        search_screens = [s for s in screens if "SearchFragment" in s]
        assert len(search_screens) <= 1

    def test_returns_empty_for_unknown(self):
        screens = _trace_resource_to_screens(
            ["no_such_resource"], "string", MOCK_REPO, SOURCE_ROOT, LAYOUTS_DIR,
        )
        assert screens == []


class TestBuildUIContextAffectedScreens:
    """Test that _build_ui_context populates affected_screens for all UI categories."""

    def _make_cf(self, path: str, category: str) -> ClassifiedFile:
        return ClassifiedFile(
            file=ChangedFile(path=path, status="modified", diff_content="", language="xml"),
            category=category,
            change_nature=None,
        )

    def test_ui_layout_finds_screens(self):
        cf = self._make_cf("app/src/main/res/layout/fragment_search.xml", "ui_layout")
        all_strings = parse_strings(MOCK_REPO / STRINGS_FILE)
        ctx = _build_ui_context(cf, MOCK_REPO, SOURCE_ROOT, LAYOUTS_DIR, all_strings)
        assert isinstance(ctx.affected_screens, list)
        assert any("SearchFragment" in s for s in ctx.affected_screens)

    def test_ui_layout_includes_layout_info_with_drawables(self):
        cf = self._make_cf("app/src/main/res/layout/fragment_search.xml", "ui_layout")
        all_strings = parse_strings(MOCK_REPO / STRINGS_FILE)
        ctx = _build_ui_context(cf, MOCK_REPO, SOURCE_ROOT, LAYOUTS_DIR, all_strings)
        assert ctx.layout_info is not None
        assert "referenced_drawables" in ctx.layout_info
        assert "ic_search" in ctx.layout_info["referenced_drawables"]

    def test_ui_strings_traces_to_screens(self):
        cf = self._make_cf("app/src/main/res/values/strings.xml", "ui_strings")
        all_strings = parse_strings(MOCK_REPO / STRINGS_FILE)
        ctx = _build_ui_context(cf, MOCK_REPO, SOURCE_ROOT, LAYOUTS_DIR, all_strings)
        assert isinstance(ctx.affected_screens, list)
        assert any("SearchFragment" in s for s in ctx.affected_screens)

    def test_ui_drawable_traces_to_screens(self):
        cf = self._make_cf("app/src/main/res/drawable/ic_search.xml", "ui_drawable")
        all_strings = {}
        ctx = _build_ui_context(cf, MOCK_REPO, SOURCE_ROOT, LAYOUTS_DIR, all_strings)
        assert isinstance(ctx.affected_screens, list)
        assert any("SearchFragment" in s for s in ctx.affected_screens)

    def test_ui_resource_fallback_traces_to_screens(self):
        # ui_resource with a drawable-style name
        cf = self._make_cf("app/src/main/res/drawable/ic_search.xml", "ui_resource")
        all_strings = {}
        ctx = _build_ui_context(cf, MOCK_REPO, SOURCE_ROOT, LAYOUTS_DIR, all_strings)
        assert isinstance(ctx.affected_screens, list)
        assert any("SearchFragment" in s for s in ctx.affected_screens)

    def test_affected_screens_is_always_list(self):
        cf = self._make_cf("app/src/main/res/layout/nonexistent.xml", "ui_layout")
        ctx = _build_ui_context(cf, MOCK_REPO, SOURCE_ROOT, LAYOUTS_DIR, {})
        assert isinstance(ctx.affected_screens, list)
