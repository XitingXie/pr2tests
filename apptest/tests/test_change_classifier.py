"""Tests for change_classifier module."""

from apptest.analyzer.change_classifier import (
    ClassifiedFile,
    classify_change_nature,
    classify_changed_files,
    classify_file,
)
from apptest.analyzer.diff_parser import ChangedFile


class TestClassifyFile:
    # --- Screen files ---
    def test_activity_kt(self):
        assert classify_file("app/src/main/java/com/example/SearchActivity.kt") == "logic_screen"

    def test_fragment_java(self):
        assert classify_file("app/src/main/java/com/example/SearchFragment.java") == "logic_screen"

    # --- ViewModel ---
    def test_viewmodel(self):
        assert classify_file("app/src/main/java/com/example/SearchViewModel.kt") == "logic_viewmodel"

    # --- Repository ---
    def test_repository(self):
        assert classify_file("app/src/main/java/com/example/SearchRepository.kt") == "logic_repository"

    def test_repo_suffix(self):
        assert classify_file("app/src/main/java/com/example/SearchRepo.kt") == "logic_repository"

    # --- DataSource ---
    def test_datasource(self):
        assert classify_file("app/src/main/java/com/example/LocalDataSource.kt") == "logic_datasource"

    # --- UseCase ---
    def test_usecase(self):
        assert classify_file("app/src/main/java/com/example/GetSearchResultsUseCase.kt") == "logic_usecase"

    def test_interactor(self):
        assert classify_file("app/src/main/java/com/example/SearchInteractor.kt") == "logic_usecase"

    # --- API ---
    def test_api(self):
        assert classify_file("app/src/main/java/com/example/SearchApi.kt") == "logic_api"

    def test_service(self):
        assert classify_file("app/src/main/java/com/example/SearchService.kt") == "logic_api"

    def test_client(self):
        assert classify_file("app/src/main/java/com/example/HttpClient.kt") == "logic_api"

    # --- Adapter ---
    def test_adapter(self):
        assert classify_file("app/src/main/java/com/example/SearchAdapter.kt") == "logic_adapter"

    def test_viewholder(self):
        assert classify_file("app/src/main/java/com/example/SearchViewHolder.kt") == "logic_adapter"

    # --- Model ---
    def test_model(self):
        assert classify_file("app/src/main/java/com/example/SearchModel.kt") == "logic_model"

    def test_entity(self):
        assert classify_file("app/src/main/java/com/example/UserEntity.kt") == "logic_model"

    def test_dto(self):
        assert classify_file("app/src/main/java/com/example/SearchResultDto.kt") == "logic_model"

    # --- Compose screen ---
    def test_compose_screen(self):
        assert classify_file("app/src/main/java/com/example/SearchResultsScreen.kt") == "logic_compose_screen"

    def test_compose_screen_deck(self):
        assert classify_file("app/src/main/java/com/example/YearInReviewScreenDeck.kt") == "logic_compose_screen"

    # --- Dialog ---
    def test_dialog(self):
        assert classify_file("app/src/main/java/com/example/ConfirmDialog.kt") == "logic_dialog"

    def test_bottom_sheet(self):
        assert classify_file("app/src/main/java/com/example/ShareBottomSheet.kt") == "logic_dialog"

    # --- AB test ---
    def test_abtest(self):
        assert classify_file("app/src/main/java/com/example/SemanticSearchAbTest.kt") == "logic_abtest"

    def test_abtest_uppercase(self):
        assert classify_file("app/src/main/java/com/example/FeatureABTest.kt") == "logic_abtest"

    # --- Callback ---
    def test_callback(self):
        assert classify_file("app/src/main/java/com/example/SearchResultCallback.kt") == "logic_callback"

    def test_listener(self):
        assert classify_file("app/src/main/java/com/example/OnClickListener.kt") == "logic_callback"

    # --- Config ---
    def test_prefs(self):
        assert classify_file("app/src/main/java/com/example/Prefs.kt") == "logic_config"

    def test_remote_config(self):
        assert classify_file("app/src/main/java/com/example/RemoteConfig.kt") == "logic_config"

    # --- Compose component (by path) ---
    def test_compose_component_by_path(self):
        assert classify_file("app/src/main/java/com/example/compose/components/PageIndicator.kt") == "logic_compose_component"

    def test_compose_theme_by_path(self):
        assert classify_file("app/src/main/java/com/example/compose/theme/AppTheme.kt") == "logic_compose_component"

    # --- Compose component (by name) ---
    def test_views_suffix(self):
        assert classify_file("app/src/main/java/com/example/HybridSearchViews.kt") == "logic_compose_component"

    def test_skeleton_loader(self):
        assert classify_file("app/src/main/java/com/example/ListItemSkeletonLoader.kt") == "logic_compose_component"

    # --- Extension ---
    def test_extension_by_path(self):
        assert classify_file("app/src/main/java/com/example/compose/extensions/Modifier.kt") == "logic_extension"

    # --- Utility ---
    def test_helper_kt(self):
        assert classify_file("app/src/main/java/com/example/SearchHelper.kt") == "logic_util"

    def test_util_kt(self):
        assert classify_file("app/src/main/java/com/example/DeviceUtil.kt") == "logic_util"

    def test_utils_kt(self):
        assert classify_file("app/src/main/java/com/example/StringUtils.kt") == "logic_util"

    # --- Other logic ---
    def test_other_kt(self):
        assert classify_file("app/src/main/java/com/example/SearchManager.kt") == "logic_other"

    # --- UI resources ---
    def test_layout_xml(self):
        assert classify_file("app/src/main/res/layout/fragment_search.xml") == "ui_layout"

    def test_strings_xml(self):
        assert classify_file("app/src/main/res/values/strings.xml") == "ui_strings"

    def test_values_xml(self):
        assert classify_file("app/src/main/res/values/colors.xml") == "ui_strings"

    def test_drawable(self):
        assert classify_file("app/src/main/res/drawable/icon.xml") == "ui_drawable"

    def test_mipmap(self):
        assert classify_file("app/src/main/res/mipmap-hdpi/ic_launcher.png") == "ui_drawable"

    def test_other_resource(self):
        assert classify_file("app/src/main/res/anim/fade_in.xml") == "ui_resource"

    # --- Test files ---
    def test_unit_test(self):
        assert classify_file("app/src/test/java/com/example/SearchTest.kt") == "test"

    def test_android_test(self):
        assert classify_file("app/src/androidTest/java/com/example/SearchUITest.kt") == "test"

    # --- Infra ---
    def test_build_gradle(self):
        assert classify_file("app/build.gradle") == "infra_build"

    def test_settings_gradle(self):
        assert classify_file("settings.gradle.kts") == "infra_build"

    def test_gradle_properties(self):
        assert classify_file("gradle.properties") == "infra_build"

    def test_manifest(self):
        assert classify_file("app/src/main/AndroidManifest.xml") == "infra_manifest"

    def test_proguard(self):
        assert classify_file("app/proguard-rules.pro") == "infra_config"

    # --- Other ---
    def test_unknown_extension(self):
        assert classify_file("README.md") == "other"

    def test_non_layout_xml(self):
        assert classify_file("some/random/config.xml") == "other"


class TestClassifyChangeNature:
    def test_pure_addition(self):
        diff = """\
@@ -10,0 +11,3 @@
+fun newMethod() {
+    println("hello")
+}"""
        assert classify_change_nature(diff) == "new_feature"

    def test_pure_deletion(self):
        diff = """\
@@ -10,3 +10,0 @@
-fun oldMethod() {
-    println("goodbye")
-}"""
        assert classify_change_nature(diff) == "feature_removal"

    def test_bug_fix(self):
        diff = """\
@@ -10,2 +10,2 @@
-val result = items.first()
+val result = items.firstOrNull()  // fix crash when empty"""
        assert classify_change_nature(diff) == "bug_fix"

    def test_error_handling(self):
        diff = """\
@@ -10,1 +10,5 @@
-fetchData()
+try {
+    fetchData()
+} catch (e: Exception) {
+    handleError(e)
+}"""
        assert classify_change_nature(diff) == "error_handling"

    def test_performance(self):
        diff = """\
@@ -10,2 +10,2 @@
-val items = repository.getAll()
+val items = cache.getOrPut("items") { repository.getAll() }"""
        assert classify_change_nature(diff) == "performance"

    def test_validation(self):
        diff = """\
@@ -10,1 +10,3 @@
-fun save(name: String) {
+fun save(name: String) {
+    require(name.isNotBlank()) { "Name must not be blank" }
+    check(name.length <= 100) { "Name too long" }"""
        assert classify_change_nature(diff) == "validation"

    def test_refactor(self):
        diff = """\
@@ -10,3 +10,3 @@
-fun getItems(): List<Item> {
-    return database.query("SELECT * FROM items")
-}
+fun getItems(): List<Item> =
+    database.query("SELECT * FROM items")
+        .map { Item.fromRow(it) }"""
        assert classify_change_nature(diff) == "refactor"

    def test_modification_default(self):
        diff = """\
@@ -10,1 +10,3 @@
-val PAGE_SIZE = 20
+val PAGE_SIZE = 50
+val MAX_PAGES = 100
+val DEFAULT_SORT = "name" """
        assert classify_change_nature(diff) == "modification"

    def test_empty_diff(self):
        assert classify_change_nature("") == "modification"

    def test_header_lines_ignored(self):
        diff = """\
--- a/Foo.kt
+++ b/Foo.kt
@@ -1,1 +1,2 @@
+import bar
+import baz"""
        assert classify_change_nature(diff) == "new_feature"


class TestClassifyChangedFiles:
    def test_batch_classification(self):
        files = [
            ChangedFile("app/src/main/java/com/ex/SearchFragment.kt", "modified", "+code", "kt"),
            ChangedFile("app/src/main/res/layout/fragment_search.xml", "modified", "", "xml"),
            ChangedFile("app/src/test/java/com/ex/SearchTest.kt", "modified", "+test", "kt"),
            ChangedFile("build.gradle", "modified", "+dep", "gradle"),
        ]
        result = classify_changed_files(files)
        assert len(result) == 4

        assert result[0].category == "logic_screen"
        assert result[0].change_nature is not None  # logic files get nature

        assert result[1].category == "ui_layout"
        assert result[1].change_nature is None  # non-logic files don't

        assert result[2].category == "test"
        assert result[2].change_nature is None

        assert result[3].category == "infra_build"
        assert result[3].change_nature is None
