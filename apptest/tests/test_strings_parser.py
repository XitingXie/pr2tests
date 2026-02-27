"""Tests for strings_parser module."""

from pathlib import Path

from apptest.analyzer.strings_parser import filter_strings, parse_strings

FIXTURES = Path(__file__).parent / "fixtures"


class TestStringsParser:
    def setup_method(self):
        self.strings = parse_strings(FIXTURES / "strings.xml")

    def test_parses_all_strings(self):
        assert len(self.strings) == 8

    def test_simple_string(self):
        assert self.strings["app_name"] == "Wikipedia"
        assert self.strings["search_hint"] == "Search Wikipedia"

    def test_string_with_markup(self):
        # <b>Wikipedia</b> nested inside the string
        assert "Wikipedia" in self.strings["welcome_message"]

    def test_filter_strings(self):
        filtered = filter_strings(self.strings, {"search_hint", "voice_search"})
        assert len(filtered) == 2
        assert "search_hint" in filtered
        assert "voice_search" in filtered
        assert "app_name" not in filtered
