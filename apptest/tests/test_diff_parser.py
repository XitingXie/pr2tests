"""Tests for diff_parser module."""

from pathlib import Path

from apptest.analyzer.diff_parser import parse_diff_from_output

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


class TestParseDiff:
    def setup_method(self):
        self.name_status = _load_fixture("sample_name_status.txt")
        self.diff_output = _load_fixture("sample_diff.txt")

    def test_parses_correct_number_of_files(self):
        results = parse_diff_from_output(self.name_status, self.diff_output)
        # Should exclude: test file, build.gradle (not relevant extensions or paths)
        # Included: SearchFragment.kt, SearchViewModel.kt, SearchResultItem.kt,
        #           fragment_search.xml, strings.xml, OldSearchHelper.kt, NewUtil.kt
        paths = [f.path for f in results]
        assert "app/src/test/java/org/wikipedia/search/SearchTest.kt" not in paths
        assert "build.gradle" not in paths

    def test_detects_statuses_correctly(self):
        results = parse_diff_from_output(self.name_status, self.diff_output)
        by_path = {f.path: f for f in results}

        fragment = by_path["app/src/main/java/org/wikipedia/search/SearchFragment.kt"]
        assert fragment.status == "modified"

        result_item = by_path["app/src/main/java/org/wikipedia/search/SearchResultItem.kt"]
        assert result_item.status == "added"

        old_helper = by_path["app/src/main/java/org/wikipedia/search/OldSearchHelper.kt"]
        assert old_helper.status == "deleted"

        new_util = by_path["app/src/main/java/org/wikipedia/util/NewUtil.kt"]
        assert new_util.status == "renamed"

    def test_detects_language(self):
        results = parse_diff_from_output(self.name_status, self.diff_output)
        by_path = {f.path: f for f in results}

        assert by_path["app/src/main/java/org/wikipedia/search/SearchFragment.kt"].language == "kt"
        assert by_path["app/src/main/res/layout/fragment_search.xml"].language == "xml"

    def test_includes_diff_content(self):
        results = parse_diff_from_output(self.name_status, self.diff_output)
        by_path = {f.path: f for f in results}

        fragment = by_path["app/src/main/java/org/wikipedia/search/SearchFragment.kt"]
        assert "setupVoiceSearch" in fragment.diff_content

    def test_unfiltered_includes_all(self):
        results = parse_diff_from_output(
            self.name_status, self.diff_output, filter_relevant=False
        )
        paths = [f.path for f in results]
        assert "build.gradle" in paths
        assert "app/src/test/java/org/wikipedia/search/SearchTest.kt" in paths
