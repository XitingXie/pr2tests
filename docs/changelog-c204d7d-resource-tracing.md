# Changelog: Trace UI Resources Through Layouts to Affected Screens

**Commit:** `c204d7d`
**Date:** 2026-02-27
**Scope:** `layout_parser.py`, `context_builder.py`, tests, fixtures, docs

## Why

When changed files were UI resources (strings, drawables, generic resources), the system produced `affected_screen: None` — meaning downstream consumers (e.g. test generators) had no idea which screens were impacted. Layout files also mapped to only a single screen, missing shared or included layouts. This made UI change context incomplete and limited the quality of generated tests for resource-only PRs.

## What Changed

### 1. Layout parser: drawable extraction (`layout_parser.py`)
- Added `referenced_drawables: list[str]` field to `LayoutInfo` dataclass.
- Added `_DRAWABLE_REF_PATTERN` regex (`@(?:drawable|mipmap)/(\w+)`) to extract drawable/mipmap references from XML attributes, following the same pattern as existing string extraction.

### 2. Dataclass rename (`context_builder.py`)
- Renamed `UIChangeContext.affected_screen: str | None` to `affected_screens: list[str]`.
- This aligns UI changes with `LogicChangeContext.affected_screens` (already a list).
- JSON output key changes from `"affected_screen"` to `"affected_screens"`.

### 3. Three new resource tracing helpers (`context_builder.py`)
- **`_find_screens_for_layout()`** — like existing `_find_screen_for_layout()` but returns all matching screens (Fragment + Activity, `.kt` + `.java`), not just the first.
- **`_find_layouts_referencing_resource(name, type, ...)`** — scans all layout XMLs in the layouts directory to find which ones reference a given string or drawable name.
- **`_trace_resource_to_screens(names, type, ...)`** — orchestrates the 2-hop trace: resource names -> layouts -> screens. De-duplicates results.

### 4. Updated `_build_ui_context()` for all UI categories
- **`ui_layout`**: Uses `_find_screens_for_layout()` for multi-screen support. Also scans for parent layouts that `<include>` this layout and adds their screens.
- **`ui_strings`**: Parses the strings file to get all string names, then traces through layouts to screens.
- **`ui_drawable`**: Extracts drawable name from the filename stem, traces through layouts to screens.
- **`ui_resource`**: Tries string-based matching first, falls back to drawable-based matching.

### 5. Fixtures and tests
- Added `@drawable/ic_search` reference to both `fragment_search.xml` fixtures (standalone and mock_repo).
- Created `drawable/ic_search.xml` vector drawable fixture.
- Added `test_extracts_drawable_references` to `test_layout_parser.py` (5 -> 6 tests).
- Created `test_resource_tracing.py` with 17 tests covering: `_find_screens_for_layout`, `_find_layouts_referencing_resource`, `_trace_resource_to_screens`, and `_build_ui_context` for all UI categories.

### 6. Documentation
- Updated `README.md` JSON example (`affected_screen` -> `affected_screens` as list, added `referenced_drawables`).
- Updated `docs/apptest-framework-spec.md` pseudocode and JSON examples.

## How It Works

The core mechanism is a **2-hop trace**:

```
Resource name (e.g. "search_hint", "ic_search")
    → Scan all layout XMLs for references to that resource
        → Map each referencing layout to its screen file(s) by naming convention
```

For layouts specifically, the system now also checks for **include parents**: if `toolbar_search.xml` is changed, it scans other layouts for `<include layout="@layout/toolbar_search" />` and adds those parent layouts' screens too.

## Files Modified

| File | Change |
|------|--------|
| `apptest/analyzer/layout_parser.py` | Added `referenced_drawables` field + extraction |
| `apptest/analyzer/context_builder.py` | Dataclass rename, 3 new helpers, updated `_build_ui_context` |
| `apptest/tests/test_layout_parser.py` | +1 drawable extraction test |
| `apptest/tests/test_resource_tracing.py` | New file, 17 tests |
| `apptest/tests/fixtures/fragment_search.xml` | Added `@drawable/ic_search` ref |
| `apptest/tests/fixtures/mock_repo/.../fragment_search.xml` | Added `@drawable/ic_search` ref |
| `apptest/tests/fixtures/mock_repo/.../drawable/ic_search.xml` | New vector drawable fixture |
| `README.md` | Updated JSON schema and project structure |
| `docs/apptest-framework-spec.md` | Updated pseudocode and JSON examples |

## Lessons Learned

- The existing `_find_screen_for_layout()` returned early on the first match — fine for single-screen lookup but insufficient when a layout name matches both a Fragment and an Activity. The new `_find_screens_for_layout()` collects all matches.
- Parsing every layout XML for each resource name is O(resources * layouts), which is acceptable for typical Android projects (dozens of layouts). If performance becomes a concern, a pre-built index (like the app profile) could cache resource-to-layout mappings.

## Potential Issues

- **Performance**: For very large projects with hundreds of layouts, the per-resource layout scanning could be slow during analysis. The existing profile system could be extended to cache resource-to-screen mappings.
- **Breaking change**: Any downstream code reading `affected_screen` (singular) from the JSON output will need to update to `affected_screens` (list). The `cli.py` only referenced `affected_screens` on logic changes, so it was unaffected.
- **Partial string matching**: For `ui_strings`, we trace ALL string names in the file, not just the changed ones. This is intentional (we don't have the old version to diff against at this layer), but could over-report affected screens for large strings.xml files.

## Further Improvements

- Extend the app profile (`apptest init`) to pre-compute resource-to-screen mappings for faster analysis.
- Parse string diffs to identify only added/changed/removed string names and trace just those.
- Support `@color/`, `@dimen/`, and `@style/` resource types for even broader tracing coverage.
- Add mipmap directory fixture to test `@mipmap/` extraction specifically.
