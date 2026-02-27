"""Tests for screen_mapper module."""

from apptest.analyzer.diff_parser import ChangedFile
from apptest.analyzer.manifest_parser import ActivityInfo
from apptest.analyzer.screen_mapper import ScreenInfo, map_changed_files

SOURCE_ROOT = "app/src/main/java/org/wikipedia"
LAYOUTS_DIR = "app/src/main/res/layout"

ACTIVITIES = [
    ActivityInfo(name="org.wikipedia.main.MainActivity", exported=True, is_launcher=True),
    ActivityInfo(name="org.wikipedia.search.SearchActivity", exported=False),
    ActivityInfo(name="org.wikipedia.page.PageActivity", exported=True),
    ActivityInfo(name="org.wikipedia.settings.SettingsActivity"),
]


def _make_file(path: str, status: str = "modified") -> ChangedFile:
    ext = path.rsplit(".", 1)[-1]
    return ChangedFile(path=path, status=status, diff_content="", language=ext)


class TestScreenMapper:
    def test_maps_fragment_directly(self):
        files = [_make_file("app/src/main/java/org/wikipedia/search/SearchFragment.kt")]
        screens = map_changed_files(files, ACTIVITIES, SOURCE_ROOT, LAYOUTS_DIR)
        assert len(screens) == 1
        assert screens[0].name == "SearchFragment"
        assert screens[0].package == "org.wikipedia.search"

    def test_maps_activity_directly(self):
        files = [_make_file("app/src/main/java/org/wikipedia/page/PageActivity.kt")]
        screens = map_changed_files(files, ACTIVITIES, SOURCE_ROOT, LAYOUTS_DIR)
        assert len(screens) == 1
        assert screens[0].name == "PageActivity"

    def test_fragment_resolves_host_activity(self):
        files = [_make_file("app/src/main/java/org/wikipedia/search/SearchFragment.kt")]
        screens = map_changed_files(files, ACTIVITIES, SOURCE_ROOT, LAYOUTS_DIR)
        assert screens[0].host_activity == "org.wikipedia.search.SearchActivity"

    def test_viewmodel_associates_with_screen(self):
        files = [
            _make_file("app/src/main/java/org/wikipedia/search/SearchFragment.kt"),
            _make_file("app/src/main/java/org/wikipedia/search/SearchViewModel.kt"),
        ]
        screens = map_changed_files(files, ACTIVITIES, SOURCE_ROOT, LAYOUTS_DIR)
        assert len(screens) == 1
        assert "app/src/main/java/org/wikipedia/search/SearchViewModel.kt" in screens[0].related_files

    def test_layout_associates_with_screen(self):
        files = [
            _make_file("app/src/main/java/org/wikipedia/search/SearchFragment.kt"),
            _make_file("app/src/main/res/layout/fragment_search.xml"),
        ]
        screens = map_changed_files(files, ACTIVITIES, SOURCE_ROOT, LAYOUTS_DIR)
        assert len(screens) == 1
        assert "app/src/main/res/layout/fragment_search.xml" in screens[0].layout_files

    def test_multiple_screens(self):
        files = [
            _make_file("app/src/main/java/org/wikipedia/search/SearchFragment.kt"),
            _make_file("app/src/main/java/org/wikipedia/page/PageActivity.kt"),
        ]
        screens = map_changed_files(files, ACTIVITIES, SOURCE_ROOT, LAYOUTS_DIR)
        assert len(screens) == 2
        names = {s.name for s in screens}
        assert "SearchFragment" in names
        assert "PageActivity" in names

    def test_repository_associates_with_screen(self):
        files = [
            _make_file("app/src/main/java/org/wikipedia/search/SearchFragment.kt"),
            _make_file("app/src/main/java/org/wikipedia/search/SearchRepository.kt"),
        ]
        screens = map_changed_files(files, ACTIVITIES, SOURCE_ROOT, LAYOUTS_DIR)
        assert len(screens) == 1
        assert "app/src/main/java/org/wikipedia/search/SearchRepository.kt" in screens[0].related_files

    def test_other_kt_file_associates_by_package(self):
        files = [
            _make_file("app/src/main/java/org/wikipedia/search/SearchFragment.kt"),
            _make_file("app/src/main/java/org/wikipedia/search/SearchResultItem.kt"),
        ]
        screens = map_changed_files(files, ACTIVITIES, SOURCE_ROOT, LAYOUTS_DIR)
        assert len(screens) == 1
        assert "app/src/main/java/org/wikipedia/search/SearchResultItem.kt" in screens[0].related_files

    def test_no_screen_file_falls_back_to_manifest(self):
        """When no Activity/Fragment is directly changed, use manifest to find screen."""
        files = [
            _make_file("app/src/main/java/org/wikipedia/search/SearchHelper.kt"),
        ]
        screens = map_changed_files(files, ACTIVITIES, SOURCE_ROOT, LAYOUTS_DIR)
        assert len(screens) == 1
        assert screens[0].name == "SearchActivity"

    def test_changed_files_tracked(self):
        files = [
            _make_file("app/src/main/java/org/wikipedia/search/SearchFragment.kt"),
            _make_file("app/src/main/java/org/wikipedia/search/SearchViewModel.kt"),
            _make_file("app/src/main/res/layout/fragment_search.xml"),
        ]
        screens = map_changed_files(files, ACTIVITIES, SOURCE_ROOT, LAYOUTS_DIR)
        assert len(screens) == 1
        assert len(screens[0].changed_files) == 3
