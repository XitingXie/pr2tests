# AppTest — AI-Powered Test Generation from PR Diffs

AppTest is a CLI tool that integrates into CI pipelines to automatically generate and execute test cases for Android apps. It reads PR diffs, classifies every change, traces logic changes to affected screens, and gathers structured context for LLM-powered test generation.

## Quick Start

```bash
pip install -e .

# Scan the codebase once to build an app profile (optional, speeds up analyze)
apptest init --repo /path/to/android-repo

# Analyze a PR diff
apptest analyze --diff "HEAD~1..HEAD" --repo /path/to/android-repo --config apptest.yml
```

## Example: Wikipedia Android

To run against real PRs from the [Wikipedia Android](https://github.com/wikimedia/apps-android-wikipedia) app:

```bash
# Clone the repo (one-time setup)
git clone --depth 200 https://github.com/wikimedia/apps-android-wikipedia.git /tmp/apps-android-wikipedia

# Scan the codebase to build a profile (finds 50+ screens, MVVM architecture)
apptest init --repo /tmp/apps-android-wikipedia

# Small PR — 3 files, search keyboard fix (PR #6350)
apptest analyze --diff "9512546..4778ade" --repo /tmp/apps-android-wikipedia

# Large PR — 55 files, hybrid search feature (PR #6221)
apptest analyze --diff "af457ff^..af457ff" --repo /tmp/apps-android-wikipedia
```

`init` writes `.apptest/app-profile.yml` with pre-computed screens and dependency chains. `analyze` uses it for fast lookups and auto-updates it with any new screens from the PR. Both commands work without a profile — `analyze` falls back to runtime tracing.

## What It Does

1. **Scans** the codebase once (`apptest init`) to build a dependency profile at `.apptest/app-profile.yml`
2. **Parses** the git diff to extract all changed files
3. **Classifies** each file (UI layout, logic, test, infra) and the nature of code changes (new feature, bug fix, refactor, etc.)
4. **Traces** logic changes through dependency chains (API → Repository → ViewModel → Fragment) to identify affected screens — uses pre-computed profile for fast lookups when available, falls back to runtime tracing
5. **Gathers** full context: source code, layouts, strings, dependency chains
6. **Outputs** structured `analysis.json` for downstream test generation
7. **Auto-updates** the profile with any new screens or chain members found in the PR

## Configuration

Create an `apptest.yml` in your repo root:

```yaml
app:
  name: "MyApp"
  package: "com.example.myapp"
  platform: android

source:
  root: "app/src/main/java/com/example/myapp"
  layouts_dir: "app/src/main/res/layout"
  strings_file: "app/src/main/res/values/strings.xml"
  manifest: "app/src/main/AndroidManifest.xml"
  exclude_dirs:            # optional, these are the defaults
    - build
    - .gradle
    - test
    - androidTest

llm:
  provider: anthropic
  model: claude-sonnet-4-20250514
```

The `source_root` field is accepted as an alias for `root`.

## Output Format

The analysis produces `analysis.json` with four change categories:

```json
{
  "app_name": "MyApp",
  "app_package": "com.example.myapp",
  "diff_ref": "HEAD~1..HEAD",
  "total_changed_files": 12,
  "ui_changes": [
    {
      "file": "app/src/main/res/layout/fragment_search.xml",
      "diff": "...",
      "type": "ui_layout",
      "affected_screen": "app/src/main/java/.../SearchFragment.kt",
      "related_strings": {"search_hint": "Search..."},
      "layout_info": {"referenced_ids": [...], "view_types": [...]}
    }
  ],
  "logic_changes": [
    {
      "file": "app/src/main/java/.../SearchRepository.kt",
      "diff": "...",
      "full_source": "...",
      "type": "logic_repository",
      "change_nature": "bug_fix",
      "dependency_chain": ["SearchRepository.kt", "SearchViewModel.kt", "SearchFragment.kt"],
      "affected_screens": ["app/.../SearchFragment.kt"],
      "trace_confidence": "high",
      "screen_context": [{"screen_file": "...", "screen_source": "...", "layout": "..."}]
    }
  ],
  "test_changes": [...],
  "infra_changes": [...],
  "all_activities": ["com.example.myapp.MainActivity", ...]
}
```

## Project Structure

```
apptest/
├── cli.py                          # Click CLI entry point (init + analyze commands)
├── config.py                       # YAML config loader
├── scanner/                        # One-time codebase scanning (apptest init)
│   ├── project_scanner.py          # Single-pass scan: screens, architecture, chains
│   └── profile_manager.py          # Load/save/merge app-profile.yml, fast lookups
├── analyzer/                       # Per-PR analysis (apptest analyze)
│   ├── diff_parser.py              # Parse git diffs into ChangedFile objects
│   ├── change_classifier.py        # Classify files and diff nature
│   ├── dependency_tracer.py        # Trace logic files to screen consumers
│   ├── context_builder.py          # Build per-type context and output JSON
│   ├── profile_updater.py          # Auto-update profile from PR changes
│   ├── manifest_parser.py          # Parse AndroidManifest.xml
│   ├── layout_parser.py            # Parse layout XML files
│   ├── strings_parser.py           # Parse strings.xml
│   └── screen_mapper.py            # [Deprecated] Old screen-centric mapper
└── tests/
    ├── test_scanner.py             # 24 tests for project scanner
    ├── test_profile_manager.py     # 17 tests for profile YAML lifecycle
    ├── test_profile_updater.py     # 9 tests for profile auto-update
    ├── test_change_classifier.py   # 33 tests for file/diff classification
    ├── test_dependency_tracer.py   # 12 tests with mock repo fixtures
    ├── test_diff_parser.py         # 5 tests for diff parsing
    ├── test_screen_mapper.py       # 10 tests (deprecated module)
    ├── test_manifest_parser.py     # 6 tests for manifest parsing
    ├── test_layout_parser.py       # 5 tests for layout parsing
    ├── test_strings_parser.py      # 4 tests for string parsing
    ├── test_integration_wikipedia.py  # Integration tests (real Wikipedia repo)
    ├── test_integration_init.py    # Init integration tests (real Wikipedia repo)
    └── fixtures/
        ├── mock_repo/              # Minimal Android project for scanner/tracer tests
        │   ├── settings.gradle
        │   ├── app/build.gradle
        │   ├── app/src/main/AndroidManifest.xml
        │   ├── app/src/main/res/layout/   # fragment_search.xml, activity_page.xml
        │   ├── app/src/main/res/values/strings.xml
        │   └── app/src/main/java/org/wikipedia/  # Kotlin source files
        ├── sample_diff.txt
        ├── sample_name_status.txt
        ├── AndroidManifest.xml
        ├── strings.xml
        └── fragment_search.xml
```

## Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest apptest/tests/ -v

# Run a specific test module
pytest apptest/tests/test_change_classifier.py -v
```

## Pipeline Overview

```
Git Repo
  │
  ├─ apptest init ──────► project_scanner.scan_project()
  │   (one-time)                 │
  │                        .apptest/app-profile.yml
  │
  ├─ git diff ──────────► diff_parser.parse_diff()
  │                              │
  │                        list[ChangedFile]
  │                              │
  ├─ AndroidManifest.xml ► manifest_parser.parse_manifest()
  │                              │
  │                        list[ActivityInfo]
  │                              │
  ├─ app-profile.yml ───► profile_manager.load_effective_profile()
  │   (if exists)                │
  │                        profile (auto + overrides)
  │                              │
  └──────────────────────► context_builder.build_context(profile=...)
                                 │
                           ┌─────┴──────┐
                           │  classify   │  change_classifier
                           │  each file  │
                           └─────┬──────┘
                                 │
                           ┌─────┴──────┐
                           │profile hit? │  profile_manager.lookup_affected_screens()
                           │  yes → fast │  dependency_tracer.trace_to_screen()
                           │  no → trace │
                           └─────┬──────┘
                                 │
                           AnalysisResult
                                 │
                     ┌───────────┴───────────┐
                     │                       │
               analysis.json    profile_updater.update_profile_from_analysis()
```
