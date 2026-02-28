# Architecture: AppTest

## Overview

AppTest is a CLI tool that reads PR diffs, classifies changes, traces them to affected screens, and produces structured analysis for test generation and execution. It consists of five modules: **scanner** (one-time codebase profiling), **analyzer** (per-PR analysis), **generator** (LLM test step generation), **runner** (device execution with vision LLMs), and **reporter** (HTML dashboard generation).

## Design Principles

1. **Change-type-centric, not screen-centric** — The output is organized by change category (UI, logic, test, infra), not by screen. This reflects reality: most PRs change business logic, not UI layouts directly.

2. **Dependency chain tracing** — Logic changes are traced through the standard Android dependency chain (API → Repository → ViewModel → Fragment/Activity) using grep-based text search. No build system or compiler needed.

3. **Classification before context gathering** — Files are classified first, then routed to type-specific context builders. This avoids the previous approach of forcing every file into a screen bucket.

4. **Stateless pure functions where possible** — `classify_file()` and `classify_change_nature()` are pure functions with no file I/O. The dependency tracer does I/O but is otherwise side-effect free.

## Module Dependency Graph

```
cli.py
  │
  ├── config.py
  ├── diff_parser.py
  ├── manifest_parser.py
  ├── scanner/
  │     ├── project_scanner.py   (scan_project — full codebase scan)
  │     └── profile_manager.py   (load/save/merge app-profile.yml)
  ├── analyzer/
  │     ├── profile_updater.py   (auto-update profile from PR changes)
  │     └── context_builder.py
  │           │
  │           ├── change_classifier.py   (classify_changed_files)
  │           ├── dependency_tracer.py   (trace_to_screen, extract_constructor_dependencies, ...)
  │           ├── layout_parser.py       (parse_layout)
  │           └── strings_parser.py      (parse_strings, filter_strings)
  ├── reporter/
  │     ├── report_schema.py     (ReportData, PRSummary, AnalyzerSummary, ...)
  │     ├── report_collector.py  (git-based PR collection)
  │     ├── report_builder.py    (orchestrate: analyze → mock tests → metrics)
  │     │     └── uses analyzer/context_builder.build_context()
  │     ├── html_renderer.py     (self-contained HTML with inline CSS/JS)
  │     └── report_index.py      (historical index JSON + HTML)
  │           └── uses html_renderer.render_index()
  └── profile_manager.py         (lookup_affected_screens — used by context_builder)
```

No circular dependencies. Each module imports only from modules below it in the graph.

## Data Flow

### `apptest init` (one-time scan)

```
repo_path
  │
  ├── _detect_project_structure()    ← settings.gradle, source/resource roots
  │
  ├── _single_pass_scan()           ← walk all sources once
  │     ├── classify_file()          (reuse from change_classifier)
  │     ├── is_screen_file()         (content-based screen detection)
  │     ├── detect architecture/DI   (keyword counting)
  │     └── extract_class_name()     (reuse from dependency_tracer)
  │
  ├── _detect_navigation()          ← XML nav graphs, Compose NavHost
  │
  └── _trace_all_chains()           ← per-screen backward tracing
        ├── find_viewmodel_reference()
        ├── extract_constructor_dependencies()
        └── find_consumers()
              │
        .apptest/app-profile.yml    ← YAML with auto + overrides sections
```

### `apptest analyze` (per-PR)

```
                    parse_diff(filter_relevant=False)
                            │
                      list[ChangedFile]
                            │
              ┌─────────────┼─────────────┐
              │             │             │
         classify_file  classify_change_nature
              │             │
              └──────┬──────┘
                     │
              list[ClassifiedFile]
                     │
          ┌──────────┼──────────┬──────────┐
          │          │          │          │
     ui_changes  logic_changes test     infra
          │          │
     parse_layout  ┌──────────────────┐
     filter_strings│ profile exists?  │
                   │  yes → lookup_affected_screens() (fast)
                   │  no  → trace_to_screen()         (runtime)
                   │  miss → fallback to trace_to_screen()
                   └──────────────────┘
                       │
                  screen_context
                       │
                  AnalysisResult
                       │
              ┌────────┴────────┐
              │                 │
        analysis.json    update_profile_from_analysis()
                         (patch auto section if profile exists)
```

## Key Data Structures

### ChangedFile (diff_parser)
Raw diff data for a single file. Fields: `path`, `status`, `diff_content`, `language`.

### ClassifiedFile (change_classifier)
A `ChangedFile` plus classification metadata: `category` (e.g. "logic_viewmodel") and `change_nature` (e.g. "bug_fix", only for logic files).

### TraceResult (dependency_tracer)
Result of tracing a logic file to its screen consumer(s): `chain` (ordered path from source to screen), `screen_files`, `confidence` ("high"/"medium"/"low").

### AnalysisResult (context_builder)
Final output containing `ui_changes[]`, `logic_changes[]`, `test_changes[]`, `infra_changes[]`, and `all_activities[]`.

## File Classification Categories

| Category | Pattern | Example |
|----------|---------|---------|
| `logic_screen` | `*Activity.kt`, `*Fragment.kt` | `SearchFragment.kt` |
| `logic_viewmodel` | `*ViewModel.kt` | `SearchViewModel.kt` |
| `logic_repository` | `*Repository.kt`, `*Repo.kt` | `SearchRepository.kt` |
| `logic_datasource` | `*DataSource*` | `LocalDataSource.kt` |
| `logic_usecase` | `*UseCase.kt`, `*Interactor.kt` | `GetResultsUseCase.kt` |
| `logic_api` | `*Api.kt`, `*Service.kt`, `*Client.kt` | `SearchApi.kt` |
| `logic_adapter` | `*Adapter.kt`, `*ViewHolder.kt` | `SearchAdapter.kt` |
| `logic_model` | `*Model.kt`, `*Entity.kt`, `*Dto.kt` | `SearchResultDto.kt` |
| `logic_other` | Other `.kt`/`.java` files | `SearchHelper.kt` |
| `ui_layout` | `res/layout/*.xml` | `fragment_search.xml` |
| `ui_strings` | `res/values/*.xml` | `strings.xml` |
| `ui_drawable` | `res/drawable/*`, `res/mipmap/*` | `icon.xml` |
| `ui_resource` | Other `res/*` | `fade_in.xml` |
| `test` | `test/`, `androidTest/` | `SearchTest.kt` |
| `infra_build` | `*.gradle`, `*.kts` | `build.gradle` |
| `infra_manifest` | `AndroidManifest.xml` | |
| `infra_config` | `proguard-rules.pro`, etc. | |

## Change Nature Classification

Heuristic-based classification from unified diff content:

| Nature | Signal |
|--------|--------|
| `new_feature` | Pure additions (no deletions) |
| `feature_removal` | Pure deletions (no additions) |
| `bug_fix` | Keywords: fix, bug, crash, npe, workaround |
| `error_handling` | Keywords: try, catch, Exception + net additions |
| `performance` | Keywords: cache, lazy, memo, throttle, optimize |
| `validation` | Keywords: require, check, assert, verify + net additions |
| `refactor` | Balanced additions/deletions (ratio > 0.6) |
| `modification` | Default fallback |

## Dependency Tracing Strategy

The tracer walks dependency chains using filename-based class name extraction + text search for references.

| File Type | Hops | Path | Confidence |
|-----------|------|------|------------|
| `logic_screen` | 0 | Direct — file IS the screen | high |
| `logic_viewmodel` | 1 | ViewModel → Fragment/Activity | high |
| `logic_adapter` | 1 | Adapter → Fragment/Activity | high |
| `logic_repository` | 2 | Repository → ViewModel → Screen | high |
| `logic_datasource` | 2 | DataSource → ViewModel → Screen | high |
| `logic_usecase` | 2 | UseCase → ViewModel → Screen | high |
| `logic_api` | 3 | API → Repository → ViewModel → Screen | medium |
| `logic_model` | 1-2 | Broad search, prefer closest UI consumer | medium |
| `logic_other` | 1-2 | Best effort: direct screen, then via any consumer | low |

Each hop uses `find_consumers(class_name, target_types)` which scans all `.kt`/`.java` files under the source root for text references to the class name.

## App Profile System

The profile system pre-computes dependency chains so `analyze` can do fast lookups instead of runtime tracing.

### Profile Location

Always at `{repo_path}/.apptest/app-profile.yml`. Not referenced from `apptest.yml`.

### Profile Structure

```yaml
auto:                           # Machine-maintained (regenerated by init, patched by analyze)
  project:
    modules: [app]
    source_roots: [app/src/main/java]
    architecture: mvvm
    di_framework: hilt
    navigation: {type: xml_nav_graph, ...}
  screens:
    - name: SearchFragment
      file: app/src/main/java/.../SearchFragment.kt
      type: fragment
  chains:
    - screen_name: SearchFragment
      screen_file: app/src/main/java/.../SearchFragment.kt
      confidence: high
      members: [SearchApi.kt, SearchRepository.kt, SearchViewModel.kt, SearchFragment.kt]
  updated_at: "2026-02-27T..."

overrides:                      # Human-curated (never auto-modified)
  reclassify: [...]
  ignore: [...]
  extra_screens: [...]
```

### Two-Layer Merge

`load_effective_profile()` merges `auto` + `overrides`:
- **reclassify**: override screen types for specific files
- **ignore**: remove screens/chains from effective view
- **extra_screens**: append manually-identified screens

### Scanner Package (`apptest/scanner/`)

| Module | Purpose |
|--------|---------|
| `project_scanner.py` | Single-pass codebase scan: detect structure, discover screens, trace chains |
| `profile_manager.py` | YAML lifecycle: load, save, merge overrides, fast chain lookup |

### Profile Updater (`apptest/analyzer/profile_updater.py`)

Auto-patches the `auto` section when `analyze` runs:
- Removes deleted files from screens and chains
- Upserts new screens discovered in the PR
- Inserts new chain members when a file is a dependency of existing chain members

### New Functions in `dependency_tracer.py`

| Function | Purpose |
|----------|---------|
| `extract_constructor_dependencies(content)` | Parse `@Inject constructor(...)` and property injection for Repository/UseCase/Api dependencies |
| `find_viewmodel_reference(content)` | Regex match ViewModel references (`by viewModels<...>`, etc.) |
| `iter_source_files(root, exclude)` | Public API for walking source files (was `_iter_source_files`) |

## Runner Module (`apptest/runner/`)

The runner executes generated tests on Android devices using ADB for device control and multimodal vision LLMs to interpret screenshots.

### Vision Providers

| Provider | Config | Coordinate System | Key Feature |
|----------|--------|-------------------|-------------|
| Google Gemini | `provider: google` | Raw pixels (0-width, 0-height) | Default, `GEMINI_API_KEY` |
| OpenAI | `provider: openai` | Raw pixels | GPT-4o etc., `OPENAI_API_KEY` |
| Moonshot Kimi K2.5 | `provider: moonshot` | Normalized 0-1000 | Best accuracy, `MOONSHOT_API_KEY` |

### Kimi K2.5 Integration

Kimi uses a different prompting strategy than Gemini/OpenAI:
- **System prompt** defines the JSON schema and action types
- **Normalized 0-1000 coordinates** — model returns `coords: [500, 130]`, denormalized to pixels: `x = int(500/1000 * screen_width)`
- **`response_format={"type": "json_object"}`** enforces valid JSON (no regex extraction needed)
- **Grounding hint**: "mentally draw a 10x10 grid over the image to align element centers"
- **Instant mode** (thinking disabled) for action steps; **Thinking mode** for verification

### LLM Trace Logging

Every LLM call is captured in a `RunTrace` with `TraceEntry` records containing the full prompt, screenshot (base64), raw response, parsed result, timing, and model info. At the end of a run, `generate_trace_html()` produces a self-contained HTML timeline at `{output_dir}/trace.html`.

### Data Flow

```
apptest run --tests tests.json --provider moonshot --model kimi-k2.5
  │
  ├── step_parser          ← parse numbered steps, detect verification prefixes
  │     │
  │     list[ParsedStep]
  │     │
  ├── executor             ← for each test: for each step: action loop or verification
  │     │
  │     ├── _run_action_step()
  │     │     └── vision.decide_action()  ← screenshot + prompt → LLM → Action
  │     │           ├── Google/OpenAI: raw pixel coords in response
  │     │           └── Moonshot: normalized 0-1000 → denormalize to pixels
  │     │
  │     ├── _run_verification_step()
  │     │     └── vision.verify_step()    ← screenshot + assertion → LLM → pass/fail
  │     │
  │     └── _run_action_step_computer_use()
  │           └── ComputerUseSession.get_action()  ← Gemini computer_use tool
  │     │
  │     RunTrace (accumulated across all tests)
  │     │
  └── output
        ├── results.json     ← TestRunResult per test, StepResult per step, Action log
        ├── trace.html       ← LLM interaction timeline (screenshots + prompts + responses)
        └── screenshots/     ← per-action PNGs
```

## Reporter Module (`apptest/reporter/`)

The reporter generates HTML dashboards from multi-PR analysis results.

### Data Flow

```
apptest report --mode <mode> [options]
  │
  ├── report_collector        ← git log in manual/daily/count mode
  │     │
  │     list[PRSummary]
  │     │
  ├── report_builder          ← for each PR: parse_diff + build_context (reuses analyzer)
  │     ├── _summarize_analysis()    ← compress AnalysisResult → AnalyzerSummary
  │     ├── _generate_mock_tests()   ← deterministic mock tests (Phase 2 placeholder)
  │     ├── _generate_mock_execution() ← ~80% pass/15% fail/5% skip (Phase 3 placeholder)
  │     └── _compute_metrics()       ← aggregate across all PRs
  │     │
  │     ReportData
  │     │
  ├── html_renderer           ← self-contained HTML (inline CSS/JS, date filter)
  │     │
  │     report.html + report.json
  │     │
  └── report_index            ← append to index, apply retention, re-render
        │
        index.html + index.json
```

### Key Data Structures (report_schema.py)

| Type | Purpose |
|------|---------|
| `TriggerInfo` | How the report was triggered (mode, range, description) |
| `PRSummary` | One commit/PR: ref, title, author, date, file stats |
| `AnalyzerSummary` | Compressed analysis: counts, screens, natures, confidences |
| `GeneratedTest` / `GeneratedTestStep` | Mock test cases per screen (Phase 2 placeholder) |
| `TestExecutionResult` | Mock execution results (Phase 3 placeholder) |
| `AggregateMetrics` | Roll-up: total PRs, files, screens, tests, pass rate |
| `ReportData` | Top-level container for a complete report |
| `ReportIndexEntry` | One row in the historical index |

### HTML Dashboard Features

- 5 metric cards (PRs, files, screens, tests, pass rate)
- Sortable PR summary table with category badges
- Collapsible per-PR analyzer details (change breakdown, screens, dependency chains)
- Collapsible per-screen test cases with step tables
- Test execution table with status badges and failure reasons
- Date-range filter that dynamically updates all sections and recomputes metrics
- Full ReportData JSON embedded as `<script type="application/json">` for programmatic extraction

### CI/CD Integration

A GitHub Actions workflow (`.github/workflows/dashboard.yml`) keeps the dashboard live:
- Triggers on push to `main` and daily schedule
- Restores previous reports from cache for accumulation
- Deploys to GitHub Pages for always-on access

## Configuration

`apptest.yml` provides:
- `source.root` — scopes the dependency tracer's search to avoid scanning build/generated dirs
- `source.exclude_dirs` — additional directories to skip (defaults: `["build", ".gradle", "test", "androidTest"]`)
- `source.layouts_dir` — for layout file discovery by naming convention
- `source.strings_file` — for string resource resolution

## Deprecated: screen_mapper.py

The previous `screen_mapper.py` used a 3-pass approach (identify screens → associate by package → fallback to manifest) that was screen-centric. It is superseded by:
- `change_classifier.py` (handles what screen_mapper's pattern matching did)
- `dependency_tracer.py` (handles what screen_mapper's package-based association did, but with actual dependency chain walking)

The module is retained for backward compatibility and its tests continue to pass.
