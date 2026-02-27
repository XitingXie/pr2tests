"""Tests for manifest_parser module."""

from pathlib import Path

from apptest.analyzer.manifest_parser import parse_manifest

FIXTURES = Path(__file__).parent / "fixtures"


class TestManifestParser:
    def setup_method(self):
        self.activities = parse_manifest(FIXTURES / "AndroidManifest.xml")
        self.by_name = {a.name: a for a in self.activities}

    def test_parses_all_activities(self):
        assert len(self.activities) == 5

    def test_resolves_shorthand_names(self):
        # ".main.MainActivity" → "org.wikipedia.main.MainActivity"
        assert "org.wikipedia.main.MainActivity" in self.by_name
        assert "org.wikipedia.search.SearchActivity" in self.by_name
        assert "org.wikipedia.settings.SettingsActivity" in self.by_name

    def test_preserves_fully_qualified_names(self):
        assert "org.wikipedia.login.LoginActivity" in self.by_name

    def test_identifies_launcher_activity(self):
        main = self.by_name["org.wikipedia.main.MainActivity"]
        assert main.is_launcher is True
        search = self.by_name["org.wikipedia.search.SearchActivity"]
        assert search.is_launcher is False

    def test_exported_flag(self):
        main = self.by_name["org.wikipedia.main.MainActivity"]
        assert main.exported is True
        search = self.by_name["org.wikipedia.search.SearchActivity"]
        assert search.exported is False

    def test_intent_filters(self):
        page = self.by_name["org.wikipedia.page.PageActivity"]
        assert len(page.intent_filters) == 1
        f = page.intent_filters[0]
        assert "android.intent.action.VIEW" in f["actions"]
        assert len(f["data"]) == 1
        assert f["data"][0]["scheme"] == "https"
        assert f["data"][0]["host"] == "en.wikipedia.org"
