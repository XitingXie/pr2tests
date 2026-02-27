"""Tests for layout_parser module."""

from pathlib import Path

from apptest.analyzer.layout_parser import parse_layout

FIXTURES = Path(__file__).parent / "fixtures"


class TestLayoutParser:
    def setup_method(self):
        self.layout = parse_layout(FIXTURES / "fragment_search.xml")

    def test_filename(self):
        assert self.layout.filename == "fragment_search.xml"

    def test_extracts_ids(self):
        assert "search_input" in self.layout.referenced_ids
        assert "voice_search_button" in self.layout.referenced_ids
        assert "search_results_list" in self.layout.referenced_ids
        assert "search_empty_message" in self.layout.referenced_ids

    def test_extracts_string_references(self):
        assert "search_hint" in self.layout.referenced_strings
        assert "voice_search" in self.layout.referenced_strings
        assert "search_empty" in self.layout.referenced_strings

    def test_extracts_include_layouts(self):
        assert "toolbar_search" in self.layout.include_layouts

    def test_extracts_drawable_references(self):
        assert "ic_search" in self.layout.referenced_drawables

    def test_extracts_view_types(self):
        assert "EditText" in self.layout.view_types
        assert "ImageButton" in self.layout.view_types
        assert "LinearLayout" in self.layout.view_types
        # RecyclerView has full package name in tag
        assert any("RecyclerView" in vt for vt in self.layout.view_types)
