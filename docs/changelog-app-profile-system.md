# Changelog: `apptest init` + App Profile System

**Date:** 2026-02-27
**Scope:** New `init` command, scanner package, profile lifecycle, analyzer integration

## Why

The analyzer traced dependency chains at runtime for every PR — scanning the full source tree with `find_consumers()` for each changed file. This was slow on large codebases (e.g. Wikipedia Android with 50+ screens). The spec defined an `apptest init` command that scans once, pre-computes all chains, and saves them for fast lookups.

## What Changed

### New files (7 modules + 4 test files)

| File | Purpose |
|------|---------|
| `apptest/scanner/__init__.py` | Package init |
| `apptest/scanner/project_scanner.py` | Single-pass codebase scan: structure detection, screen discovery, architecture/DI detection, chain tracing |
| `apptest/scanner/profile_manager.py` | Profile YAML lifecycle: load, save, merge `auto` + `overrides`, fast chain lookup |
| `apptest/analyzer/profile_updater.py` | Auto-patch profile's `auto` section from PR changes (add/remove screens, update chains) |
| `apptest/tests/test_scanner.py` | 24 tests: project structure, single-pass scan, screen detection, chain tracing, end-to-end |
| `apptest/tests/test_profile_manager.py` | 17 tests: load/save/merge, lookup, resolve, YAML roundtrip |
| `apptest/tests/test_profile_updater.py` | 9 tests: remove deleted, upsert screen, update chains, preserve overrides |
| `apptest/tests/test_integration_init.py` | 8 integration tests against Wikipedia repo (skipped if missing) |

### Modified files (3)

| File | Changes |
|------|---------|
| `apptest/analyzer/dependency_tracer.py` | Added `extract_constructor_dependencies()`, `find_viewmodel_reference()`, made `iter_source_files()` public. No breaking changes. |
| `apptest/analyzer/context_builder.py` | `build_context()` and `_build_logic_context()` gained optional `profile` param. When present, does fast lookup first, falls back to runtime tracing on miss. Fully backward-compatible. |
| `apptest/cli.py` | Added `init` command. Modified `analyze` to load profile if present, pass to `build_context()`, and auto-update profile after analysis. |

### New fixtures (6)

Added to `apptest/tests/fixtures/mock_repo/`:
- `settings.gradle`, `app/build.gradle`, `app/src/main/AndroidManifest.xml`
- `app/src/main/res/layout/fragment_search.xml`, `app/src/main/res/layout/activity_page.xml`
- `app/src/main/res/values/strings.xml`

## How It Works

### `apptest init --repo .`

1. **Detect project structure** — parses `settings.gradle(.kts)` for modules, discovers source/resource roots
2. **Single-pass scan** — walks all `.kt/.java` files once; classifies each, detects screens by content (`Fragment()`, `Activity()`, `@Composable`), counts architecture/DI keywords
3. **Detect navigation** — checks for XML nav graphs and Compose NavHost references
4. **Trace all chains** — for each screen, finds ViewModel reference, extracts constructor dependencies, builds backward chain
5. **Save profile** — writes `.apptest/app-profile.yml` with `auto` section + commented `overrides` template

### Profile-accelerated `apptest analyze`

1. Loads profile via `load_effective_profile()` (merges `auto` + `overrides`)
2. Passes profile to `build_context()` → `_build_logic_context()`
3. For each logic file: `lookup_affected_screens()` does O(chains) lookup by class name
4. On miss: falls back to existing `trace_to_screen()` (runtime tracing)
5. After analysis: `update_profile_from_analysis()` patches `auto` section with any new screens/chain members

### Design decisions

- **2 scanner files, not 5**: architecture detection, screen discovery, and DI detection all walk the same file tree, so they're combined in `project_scanner.py`. `profile_manager.py` stays separate (pure YAML I/O).
- **Profile path is convention**: always at `{repo}/.apptest/app-profile.yml`, not referenced from config.
- **New helpers in `dependency_tracer.py`**: `extract_constructor_dependencies()` and `find_viewmodel_reference()` are used by both scanner and profile_updater. Centralizes pattern-matching logic.

## Test Results

188 total tests pass (130 existing + 58 new), including 8 Wikipedia integration tests that verify:
- 50+ screens discovered
- MVVM architecture detected
- Valid YAML roundtrip
- Search chain includes ViewModel
- Profile lookup returns correct screens

## Potential Issues

- **Large monorepo scan time**: `scan_project()` walks all source files. For very large repos, the initial `init` may take several seconds. The profile is then reused across all PRs.
- **Constructor dependency patterns**: `extract_constructor_dependencies()` relies on naming conventions (suffixes like Repository, UseCase, Api). Unusual naming may miss dependencies.
- **Profile staleness**: if the codebase changes significantly without running `init` again, the profile may have stale chains. The auto-update from `analyze` mitigates this for incremental changes.

## Further Improvements

- Add `--force` flag to `init` for re-scanning when profile exists
- Support multi-module source roots (currently uses first source root for chain tracing)
- Add profile validation CLI command (`apptest profile check`)
- Benchmark profile lookup vs runtime tracing on large PRs
