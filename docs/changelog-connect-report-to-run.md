# Changelog: Connect Report to Actual Run Results

## Why

The `report` command generated **mock** test and execution data via `_generate_mock_tests()` and `_generate_mock_execution()`. Meanwhile, the analyze → generate → run pipeline produces real data in a run directory (`tests.json`, `results.json`, `trace.html`). These two systems were disconnected. This change makes `report` use real run results when available, falling back to mocks when no run data exists.

## What Changed

### Files Modified

| File | Change |
|------|--------|
| `apptest/reporter/report_schema.py` | Added `trace_html_path: str = ""` field to `ReportData` |
| `apptest/reporter/report_builder.py` | Added `_tests_from_run()` and `_executions_from_run()` helpers. Modified `build_report()` to accept `run_dir` parameter and load real data from `tests.json` + `results.json` |
| `apptest/reporter/html_renderer.py` | Added `_render_trace_link()` for LLM trace log link. Updated `write_report_html()` to copy `trace.html` into report output directory |
| `apptest/cli.py` | Added `--run` option to `report` command with auto-discovery via `get_latest_run()` |

### How It Works

1. **CLI layer**: The `report` command accepts an optional `--run` path. When not provided, it auto-discovers the latest run via `get_latest_run()`. The resolved `run_dir` is printed and passed to `build_report()`.

2. **Report builder**: When `run_dir` is provided and contains both `tests.json` and `results.json`, real data is loaded via `_tests_from_run()` and `_executions_from_run()`. Mock generation is skipped. When no run data is available, the existing mock behavior is preserved.

3. **Data conversion**:
   - `_tests_from_run()` converts `GenerationResult`-format dicts into `GeneratedTest` objects, splitting each `TestCase.description` into step lines.
   - `_executions_from_run()` converts `RunSummary`-format dicts into `TestExecutionResult` objects, counting passed steps for `steps_completed`.

4. **Trace link**: If `trace.html` exists in the run directory, its path is stored on `ReportData.trace_html_path`. The HTML renderer shows a "View LLM Trace Log" link and copies the file into the report output directory.

## Backward Compatibility

- `build_report()` defaults `run_dir=None`, preserving the existing mock-based behavior.
- All 337 existing tests pass without modification.
- `apptest report --mode manual --range "..."` without a run directory still uses mocks.

## Potential Issues

- The step parsing in `_tests_from_run()` is line-based and may not capture structured step semantics as well as purpose-built test step parsers.
- If `tests.json` and `results.json` exist but are malformed, the report will fail rather than fall back to mocks. This is intentional — better to surface data issues than silently ignore them.

## Further Improvements

- Add a `--no-run` flag to explicitly skip run data loading.
- Parse `TestCase.description` more intelligently (e.g., recognize numbered steps, action keywords).
- Show per-step timing and screenshots from the run in the HTML report.
