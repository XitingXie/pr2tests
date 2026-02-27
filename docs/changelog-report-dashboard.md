# Changelog: `apptest report` — HTML Dashboard System

## Why

The analyzer pipeline (`apptest analyze`) outputs `analysis.json` but provides no way to visualize results across PRs over time. Teams need a periodic report/dashboard that collects PRs (manually, daily, or every N commits), runs the analyzer on each, and produces a self-contained HTML dashboard showing analyzer results, test steps generated, test execution results, and aggregate metrics.

## What Changed

### New Module: `apptest/reporter/`

| File | Purpose |
|------|---------|
| `report_schema.py` | 10 dataclasses (TriggerInfo, PRSummary, AnalyzerSummary, GeneratedTest, GeneratedTestStep, TestExecutionResult, AggregateMetrics, ReportData, ReportIndexEntry) |
| `report_collector.py` | Git-based PR collection in 3 modes: manual (commit range), daily (since date), count (last N). State tracking via `.apptest/report-state.json` |
| `report_builder.py` | Orchestration: analyze PRs → summarize → generate mock tests → mock execution → compute aggregate metrics |
| `html_renderer.py` | Self-contained HTML renderer with inline CSS/JS, metric cards, sortable tables, collapsible sections, embedded JSON |
| `report_index.py` | Historical index management (JSON + HTML) with retention policy |

### Modified Files

| File | Change |
|------|--------|
| `apptest/config.py` | Added `ReportConfig` dataclass with trigger_mode, trigger_count, output_dir, retention, include_mock_tests. Added to `Config` and `load_config()`. |
| `apptest/cli.py` | Added `report` command with `--mode`, `--range`, `--since`, `--count`, `--repo`, `--config`, `--output` options. |
| `apptest.yml` | Added commented-out `report:` section documenting available options. |

### New Tests (58 tests)

| File | Coverage |
|------|----------|
| `test_report_schema.py` | Serialization roundtrip, default factory isolation |
| `test_report_collector.py` | All 3 collection modes in real git repos, state management |
| `test_report_builder.py` | Analysis summarization, mock test/execution generation, metrics computation |
| `test_html_renderer.py` | HTML structure, self-containment, all sections, embedded JSON, XSS escaping |
| `test_report_index.py` | Load/save, retention, disk cleanup |

## How It Works

### CLI Usage

```bash
# Manual: analyze a specific commit range
apptest report --mode manual --range "abc..def" --repo /path/to/repo

# Daily: analyze commits since a date (defaults to yesterday)
apptest report --mode daily --since 2026-02-26

# Count: analyze the last N commits
apptest report --mode count --count 10
```

### Pipeline Flow

1. **Collect PRs** — git log in the specified mode → `list[PRSummary]`
2. **Analyze each PR** — reuses existing `parse_diff()` + `build_context()` pipeline
3. **Summarize** — compress `AnalysisResult` into `AnalyzerSummary` (drop large fields)
4. **Mock tests** — deterministic test generation per affected screen (Phase 2 placeholder)
5. **Mock execution** — ~80% pass / ~15% fail / ~5% skip distribution (Phase 3 placeholder)
6. **Compute metrics** — aggregate across all PRs
7. **Render HTML** — self-contained dashboard with inline CSS/JS
8. **Update index** — append to `index.json` + `index.html`, apply retention

### Output Structure

```
.apptest/reports/
├── index.json
├── index.html
├── report-20260227-100000/
│   ├── report.html    # Self-contained dashboard
│   └── report.json    # Machine-readable data
└── report-20260228-100000/
    ├── report.html
    └── report.json
```

### HTML Dashboard Sections

1. **Header** — app name, version, timestamp, trigger info
2. **Metrics cards** — 5 large-number cards (PRs, files, screens, tests, pass rate)
3. **PR summary table** — sortable, with color-coded category badges
4. **Analyzer details** — collapsible per-PR sections (change breakdown, screens, chains)
5. **Generated tests** — collapsible per-screen test cases with step tables
6. **Test execution** — pass/fail table with status badges, durations, failure reasons
7. **Embedded JSON** — full ReportData as `<script type="application/json">` for extraction

## Design Decisions

- **No Jinja2 dependency** — pure f-string rendering keeps the module self-contained
- **Deterministic mocks** — MD5-seeded from screen names for reproducible output
- **Squash-merge fallback** — collector falls back to all commits when no merge commits exist
- **HTML escaping** — `_esc()` helper + JSON `</script>` escaping prevents XSS
- **Dual index format** — JSON for programmatic access, HTML for human browsing

## Lessons Learned

- Embedding JSON in `<script type="application/json">` requires escaping `</` → `<\/` to prevent premature tag closure
- Pytest auto-collects classes named `Test*` even if they're dataclasses — the `TestExecutionResult` dataclass triggers a harmless warning

## Potential Issues

- Mock tests use simple deterministic seeding — real test generation (Phase 2) will need to replace `_generate_mock_tests()`
- The collector's numstat approach makes one extra `git diff --numstat` call per commit — could be slow for large ranges
- No concurrent PR analysis — each PR is analyzed sequentially

## Future Improvements

- Replace mock test generation with real Phase 2 test generator
- Replace mock execution with real Phase 3 test runner
- Add trend charts (pass rate over time) using embedded SVG or Canvas
- Parallel PR analysis for large report ranges
- Diff-based incremental reports (only analyze new PRs since last report)
