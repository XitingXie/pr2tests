"""Tests for dependency_tracer module."""

from pathlib import Path

from apptest.analyzer.dependency_tracer import (
    TraceResult,
    extract_class_name,
    find_consumers,
    trace_to_screen,
)

MOCK_REPO = str(Path(__file__).parent / "fixtures" / "mock_repo")
SOURCE_ROOT = "app/src/main/java/org/wikipedia"


class TestExtractClassName:
    def test_reads_class_from_file(self):
        name = extract_class_name(
            "app/src/main/java/org/wikipedia/search/SearchFragment.kt",
            MOCK_REPO,
        )
        assert name == "SearchFragment"

    def test_reads_interface(self):
        name = extract_class_name(
            "app/src/main/java/org/wikipedia/search/SearchApi.kt",
            MOCK_REPO,
        )
        assert name == "SearchApi"

    def test_reads_data_class(self):
        name = extract_class_name(
            "app/src/main/java/org/wikipedia/search/SearchResultItem.kt",
            MOCK_REPO,
        )
        assert name == "SearchResultItem"

    def test_fallback_to_stem(self):
        name = extract_class_name("some/path/MissingFile.kt", MOCK_REPO)
        assert name == "MissingFile"


class TestFindConsumers:
    def test_finds_viewmodel_consumer_of_repository(self):
        consumers = find_consumers(
            "SearchRepository", MOCK_REPO, SOURCE_ROOT,
            target_types=["ViewModel"],
        )
        assert any("SearchViewModel" in c for c in consumers)

    def test_finds_fragment_consumer_of_viewmodel(self):
        consumers = find_consumers(
            "SearchViewModel", MOCK_REPO, SOURCE_ROOT,
            target_types=["Fragment", "Activity"],
        )
        assert any("SearchFragment" in c for c in consumers)

    def test_excludes_source_file(self):
        consumers = find_consumers(
            "SearchRepository", MOCK_REPO, SOURCE_ROOT,
            exclude_file="app/src/main/java/org/wikipedia/search/SearchRepository.kt",
        )
        # Should not include the file itself
        assert not any("SearchRepository.kt" in c for c in consumers)

    def test_no_match_returns_empty(self):
        consumers = find_consumers(
            "NonExistentClass", MOCK_REPO, SOURCE_ROOT,
        )
        assert consumers == []

    def test_target_types_filter(self):
        # SearchResultItem is used by SearchRepository, SearchAdapter, SearchViewModel
        # but we only want ViewModel
        consumers = find_consumers(
            "SearchResultItem", MOCK_REPO, SOURCE_ROOT,
            target_types=["ViewModel"],
        )
        for c in consumers:
            assert "ViewModel" in c


class TestTraceToScreen:
    def test_screen_file_returns_itself(self):
        result = trace_to_screen(
            "app/src/main/java/org/wikipedia/search/SearchFragment.kt",
            "logic_screen",
            MOCK_REPO,
            SOURCE_ROOT,
        )
        assert result.confidence == "high"
        assert len(result.screen_files) == 1
        assert "SearchFragment" in result.screen_files[0]

    def test_viewmodel_traces_to_fragment(self):
        result = trace_to_screen(
            "app/src/main/java/org/wikipedia/search/SearchViewModel.kt",
            "logic_viewmodel",
            MOCK_REPO,
            SOURCE_ROOT,
        )
        assert result.confidence == "high"
        assert any("SearchFragment" in s for s in result.screen_files)
        assert len(result.chain) >= 2

    def test_repository_traces_two_hops(self):
        result = trace_to_screen(
            "app/src/main/java/org/wikipedia/search/SearchRepository.kt",
            "logic_repository",
            MOCK_REPO,
            SOURCE_ROOT,
        )
        assert any("SearchFragment" in s for s in result.screen_files)
        # Chain: Repository → ViewModel → Fragment
        assert len(result.chain) >= 3

    def test_api_traces_three_hops(self):
        result = trace_to_screen(
            "app/src/main/java/org/wikipedia/search/SearchApi.kt",
            "logic_api",
            MOCK_REPO,
            SOURCE_ROOT,
        )
        assert any("SearchFragment" in s for s in result.screen_files)
        # Chain: Api → Repository → ViewModel → Fragment
        assert len(result.chain) >= 4

    def test_adapter_traces_to_fragment(self):
        result = trace_to_screen(
            "app/src/main/java/org/wikipedia/search/SearchAdapter.kt",
            "logic_adapter",
            MOCK_REPO,
            SOURCE_ROOT,
        )
        assert any("SearchFragment" in s for s in result.screen_files)

    def test_model_finds_screens(self):
        result = trace_to_screen(
            "app/src/main/java/org/wikipedia/search/SearchResultItem.kt",
            "logic_model",
            MOCK_REPO,
            SOURCE_ROOT,
        )
        # Model is used broadly; should find at least one screen
        assert len(result.screen_files) >= 1

    def test_unknown_file_graceful(self):
        result = trace_to_screen(
            "app/src/main/java/org/wikipedia/search/UnknownHelper.kt",
            "logic_other",
            MOCK_REPO,
            SOURCE_ROOT,
        )
        # Should not crash, returns low confidence
        assert result.confidence == "low"
        assert isinstance(result.screen_files, list)
