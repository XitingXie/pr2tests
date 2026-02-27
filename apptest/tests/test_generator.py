"""Tests for the test generator module."""

import json

import pytest

from apptest.config import LLMConfig
from apptest.generator.test_generator import (
    GenerationResult,
    TestCase,
    _format_changes,
    _parse_test_cases,
    _truncate_source,
    generate_tests,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_ANALYSIS = {
    "app_name": "Wikipedia",
    "app_package": "org.wikipedia",
    "diff_ref": "abc123..def456",
    "total_changed_files": 3,
    "ui_changes": [
        {
            "file": "app/src/main/res/layout/fragment_search.xml",
            "diff": "@@ -10,3 +10,5 @@\n+<EditText android:id=\"@+id/search_input\" />",
            "type": "ui_layout",
            "content": "<LinearLayout>...</LinearLayout>",
            "affected_screens": [
                "app/src/main/java/org/wikipedia/search/SearchFragment.kt"
            ],
            "related_strings": {
                "search_hint": "Search Wikipedia",
                "no_results": "No results found",
            },
            "layout_info": {
                "filename": "fragment_search.xml",
                "referenced_ids": ["search_input", "results_list"],
                "referenced_strings": ["search_hint", "no_results"],
                "referenced_drawables": ["ic_search"],
                "include_layouts": [],
                "view_types": ["LinearLayout", "EditText"],
            },
        }
    ],
    "logic_changes": [
        {
            "file": "app/src/main/java/org/wikipedia/search/SearchViewModel.kt",
            "diff": "@@ -20,3 +20,8 @@\n+fun search(query: String) { ... }",
            "full_source": "class SearchViewModel {\n    fun search(query: String) {\n        // implementation\n    }\n}",
            "type": "logic_viewmodel",
            "change_nature": "new_feature",
            "dependency_chain": [
                "app/src/main/java/org/wikipedia/search/SearchRepository.kt",
                "app/src/main/java/org/wikipedia/search/SearchViewModel.kt",
                "app/src/main/java/org/wikipedia/search/SearchFragment.kt",
            ],
            "affected_screens": [
                "app/src/main/java/org/wikipedia/search/SearchFragment.kt"
            ],
            "trace_confidence": "high",
            "screen_context": [
                {
                    "screen_file": "app/src/main/java/org/wikipedia/search/SearchFragment.kt",
                    "screen_source": "class SearchFragment : Fragment() { ... }",
                    "layout_file": "fragment_search.xml",
                    "layout": "<LinearLayout>...</LinearLayout>",
                }
            ],
        }
    ],
    "test_changes": [
        {
            "file": "app/src/test/java/org/wikipedia/search/SearchViewModelTest.kt",
            "diff": "+@Test fun testSearch() { ... }",
            "note": "Unit test for search.",
        }
    ],
    "infra_changes": [
        {
            "file": "app/build.gradle.kts",
            "diff": "+implementation(\"com.example:lib:1.0\")",
            "type": "infra_build",
        }
    ],
    "all_activities": ["org.wikipedia.main.MainActivity"],
}

MOCK_LOGIC_ONLY_ANALYSIS = {
    "app_name": "Wikipedia",
    "app_package": "org.wikipedia",
    "diff_ref": "aaa..bbb",
    "total_changed_files": 1,
    "ui_changes": [],
    "logic_changes": [
        {
            "file": "app/src/main/java/org/wikipedia/feed/FeedViewModel.kt",
            "diff": "@@ -5 +5,10 @@\n+val items = mutableListOf<FeedItem>()",
            "full_source": "class FeedViewModel { ... }",
            "type": "logic_viewmodel",
            "change_nature": "bug_fix",
            "dependency_chain": ["FeedViewModel.kt", "FeedFragment.kt"],
            "affected_screens": ["app/src/main/java/org/wikipedia/feed/FeedFragment.kt"],
            "trace_confidence": "high",
            "screen_context": [],
        }
    ],
    "test_changes": [],
    "infra_changes": [],
    "all_activities": [],
}

VALID_LLM_RESPONSE = json.dumps([
    {
        "id": "test_001",
        "description": "1. Open the app\n2. Navigate to Search\n3. Type 'dog'\n4. Verify results appear",
        "covers": "Basic search functionality",
        "change_type": "new_feature",
        "priority": "high",
        "test_data": {"search_term": "dog"},
    },
    {
        "id": "test_002",
        "description": "1. Open Search\n2. Type empty string\n3. Verify no crash",
        "covers": "Empty search edge case",
        "change_type": "edge_case",
        "priority": "medium",
        "test_data": {},
    },
])


# ---------------------------------------------------------------------------
# Tests: _truncate_source
# ---------------------------------------------------------------------------


class TestTruncateSource:
    def test_short_source_unchanged(self):
        src = "line1\nline2\nline3"
        assert _truncate_source(src, max_lines=10) == src

    def test_long_source_truncated(self):
        lines = [f"line {i}" for i in range(200)]
        result = _truncate_source("\n".join(lines), max_lines=100)
        result_lines = result.splitlines()
        assert len(result_lines) == 101  # 100 lines + truncation note
        assert "100 more lines" in result_lines[-1]


# ---------------------------------------------------------------------------
# Tests: _format_changes
# ---------------------------------------------------------------------------


class TestFormatChanges:
    def test_formats_ui_changes(self):
        text = _format_changes(MOCK_ANALYSIS)
        assert "## UI Changes" in text
        assert "fragment_search.xml" in text
        assert "search_hint" in text
        assert "SearchFragment" in text

    def test_formats_logic_changes(self):
        text = _format_changes(MOCK_ANALYSIS)
        assert "## Logic Changes" in text
        assert "SearchViewModel.kt" in text
        assert "new_feature" in text
        assert "SearchRepository" in text
        assert "SearchFragment" in text

    def test_formats_test_changes(self):
        text = _format_changes(MOCK_ANALYSIS)
        assert "Existing Test Changes" in text
        assert "SearchViewModelTest.kt" in text

    def test_formats_infra_changes(self):
        text = _format_changes(MOCK_ANALYSIS)
        assert "Infrastructure Changes" in text
        assert "build.gradle.kts" in text

    def test_empty_analysis(self):
        text = _format_changes({})
        assert text == ""

    def test_logic_only_no_ui_section(self):
        text = _format_changes(MOCK_LOGIC_ONLY_ANALYSIS)
        assert "## UI Changes" not in text
        assert "## Logic Changes" in text

    def test_screen_context_layout_included(self):
        text = _format_changes(MOCK_ANALYSIS)
        assert "Screen context (SearchFragment)" in text
        assert "fragment_search.xml" in text


# ---------------------------------------------------------------------------
# Tests: _parse_test_cases
# ---------------------------------------------------------------------------


class TestParseTestCases:
    def test_valid_json_array(self):
        cases = _parse_test_cases(VALID_LLM_RESPONSE)
        assert len(cases) == 2
        assert cases[0].id == "test_001"
        assert cases[0].priority == "high"
        assert cases[0].change_type == "new_feature"
        assert cases[0].test_data == {"search_term": "dog"}
        assert cases[1].id == "test_002"

    def test_json_with_markdown_fences(self):
        wrapped = f"```json\n{VALID_LLM_RESPONSE}\n```"
        cases = _parse_test_cases(wrapped)
        assert len(cases) == 2
        assert cases[0].id == "test_001"

    def test_json_with_surrounding_text(self):
        wrapped = f"Here are the tests:\n{VALID_LLM_RESPONSE}\n\nDone!"
        cases = _parse_test_cases(wrapped)
        assert len(cases) == 2

    def test_malformed_json(self):
        cases = _parse_test_cases("this is not json at all")
        assert cases == []

    def test_json_object_not_array(self):
        cases = _parse_test_cases('{"key": "value"}')
        assert cases == []

    def test_empty_array(self):
        cases = _parse_test_cases("[]")
        assert cases == []

    def test_missing_fields_get_defaults(self):
        partial = json.dumps([{"id": "test_x"}])
        cases = _parse_test_cases(partial)
        assert len(cases) == 1
        assert cases[0].id == "test_x"
        assert cases[0].description == ""
        assert cases[0].priority == "medium"
        assert cases[0].change_type == "unknown"
        assert cases[0].test_data == {}

    def test_non_dict_items_skipped(self):
        mixed = json.dumps([{"id": "test_1"}, "not a dict", 42, {"id": "test_2"}])
        cases = _parse_test_cases(mixed)
        assert len(cases) == 2
        assert cases[0].id == "test_1"
        assert cases[1].id == "test_2"

    def test_invalid_test_data_defaults_to_empty_dict(self):
        data = json.dumps([{"id": "t1", "test_data": "not a dict"}])
        cases = _parse_test_cases(data)
        assert len(cases) == 1
        assert cases[0].test_data == {}


# ---------------------------------------------------------------------------
# Tests: generate_tests (with mocked LLM)
# ---------------------------------------------------------------------------


class TestGenerateTests:
    def test_empty_analysis_returns_no_tests(self):
        empty = {
            "diff_ref": "x..y",
            "ui_changes": [],
            "logic_changes": [],
            "test_changes": [],
            "infra_changes": [],
        }
        result = generate_tests(empty, LLMConfig())
        assert isinstance(result, GenerationResult)
        assert result.tests == []
        assert result.pr_ref == "x..y"

    def test_logic_only_addendum_included(self, monkeypatch):
        """When there are no UI changes, the logic-only addendum should be in the prompt."""
        captured_prompts = []

        def fake_call_llm(user_message, system_prompt, config):
            captured_prompts.append(system_prompt)
            return VALID_LLM_RESPONSE

        monkeypatch.setattr(
            "apptest.generator.test_generator._call_llm", fake_call_llm
        )

        result = generate_tests(MOCK_LOGIC_ONLY_ANALYSIS, LLMConfig())
        assert len(captured_prompts) == 1
        assert "Logic-Only Changes" in captured_prompts[0]
        assert len(result.tests) == 2

    def test_ui_and_logic_no_addendum(self, monkeypatch):
        """When there are UI changes, the logic-only addendum should NOT appear."""
        captured_prompts = []

        def fake_call_llm(user_message, system_prompt, config):
            captured_prompts.append(system_prompt)
            return VALID_LLM_RESPONSE

        monkeypatch.setattr(
            "apptest.generator.test_generator._call_llm", fake_call_llm
        )

        result = generate_tests(MOCK_ANALYSIS, LLMConfig())
        assert len(captured_prompts) == 1
        assert "Logic-Only Changes" not in captured_prompts[0]
        assert len(result.tests) == 2

    def test_change_summary_counts(self, monkeypatch):
        monkeypatch.setattr(
            "apptest.generator.test_generator._call_llm",
            lambda *a: VALID_LLM_RESPONSE,
        )
        result = generate_tests(MOCK_ANALYSIS, LLMConfig())
        assert result.change_summary == {
            "ui": 1,
            "logic": 1,
            "test": 1,
            "infra": 1,
        }

    def test_pr_ref_captured(self, monkeypatch):
        monkeypatch.setattr(
            "apptest.generator.test_generator._call_llm",
            lambda *a: VALID_LLM_RESPONSE,
        )
        result = generate_tests(MOCK_ANALYSIS, LLMConfig())
        assert result.pr_ref == "abc123..def456"

    def test_malformed_llm_response_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            "apptest.generator.test_generator._call_llm",
            lambda *a: "Sorry, I can't help with that.",
        )
        result = generate_tests(MOCK_ANALYSIS, LLMConfig())
        assert result.tests == []
        assert result.change_summary["ui"] == 1


# ---------------------------------------------------------------------------
# Tests: write_tests / GenerationResult serialization
# ---------------------------------------------------------------------------


class TestWriteTests:
    def test_write_and_read_round_trip(self, tmp_path):
        from apptest.generator.test_generator import write_tests

        result = GenerationResult(
            generated_at="2026-02-27T12:00:00+00:00",
            pr_ref="abc..def",
            change_summary={"ui": 1, "logic": 2, "test": 0, "infra": 0},
            tests=[
                TestCase(
                    id="test_001",
                    description="1. Open app\n2. Tap search",
                    covers="Search feature",
                    change_type="new_feature",
                    priority="high",
                    test_data={"query": "test"},
                )
            ],
        )

        out_path = tmp_path / "tests.json"
        write_tests(result, out_path)

        with open(out_path) as f:
            data = json.load(f)

        assert data["pr_ref"] == "abc..def"
        assert len(data["tests"]) == 1
        assert data["tests"][0]["id"] == "test_001"
        assert data["tests"][0]["test_data"] == {"query": "test"}
