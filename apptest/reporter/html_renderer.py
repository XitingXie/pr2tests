"""Render self-contained HTML dashboard from ReportData.

Uses Python f-strings with helper functions per section — no Jinja2 dependency.
Each ``_render_*()`` returns an HTML string fragment; ``render_report()`` composes them.
"""

import json
from dataclasses import asdict
from pathlib import Path

from .report_schema import (
    AggregateMetrics,
    AnalyzerSummary,
    GeneratedTest,
    PRSummary,
    ReportData,
    ReportIndexEntry,
    TestExecutionResult,
)


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """\
:root {
    --bg: #f8f9fa;
    --card-bg: #ffffff;
    --text: #212529;
    --text-muted: #6c757d;
    --border: #dee2e6;
    --green: #28a745;
    --blue: #007bff;
    --red: #dc3545;
    --yellow: #ffc107;
    --gray: #6c757d;
    --purple: #6f42c1;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.6;
    max-width: 1200px; margin: 0 auto; padding: 24px;
}
h1 { font-size: 1.8rem; margin-bottom: 4px; }
h2 { font-size: 1.3rem; margin: 32px 0 16px; border-bottom: 2px solid var(--border); padding-bottom: 8px; }
h3 { font-size: 1.1rem; margin: 16px 0 8px; }
.subtitle { color: var(--text-muted); font-size: 0.9rem; margin-bottom: 24px; }
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin: 24px 0; }
.metric-card {
    background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px;
    padding: 20px; text-align: center;
}
.metric-card .value { font-size: 2.2rem; font-weight: 700; }
.metric-card .label { color: var(--text-muted); font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px; }
table { width: 100%; border-collapse: collapse; margin: 16px 0; background: var(--card-bg); border-radius: 8px; overflow: hidden; }
th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border); }
th { background: #f1f3f5; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px; cursor: pointer; user-select: none; }
th:hover { background: #e9ecef; }
tr:last-child td { border-bottom: none; }
.badge {
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 0.75rem; font-weight: 600; color: #fff;
}
.badge-ui { background: var(--green); }
.badge-logic { background: var(--blue); }
.badge-test { background: var(--yellow); color: #212529; }
.badge-infra { background: var(--gray); }
.badge-passed { background: var(--green); }
.badge-failed { background: var(--red); }
.badge-skipped { background: var(--yellow); color: #212529; }
.badge-error { background: var(--red); }
.badge-high { background: var(--red); }
.badge-medium { background: var(--yellow); color: #212529; }
.badge-low { background: var(--gray); }
.collapsible { cursor: pointer; user-select: none; }
.collapsible::before { content: "\\25B6 "; font-size: 0.8em; }
.collapsible.open::before { content: "\\25BC "; }
.collapse-content { display: none; margin-left: 16px; margin-bottom: 16px; }
.collapse-content.show { display: block; }
.chain { font-family: monospace; font-size: 0.85rem; color: var(--text-muted); }
.chain-arrow { color: var(--blue); }
.step-table { font-size: 0.9rem; }
.trigger-info { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin: 16px 0; }
.trigger-info dt { font-weight: 600; display: inline; }
.trigger-info dd { display: inline; margin: 0 16px 0 4px; }
.date-filter {
    background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px;
    padding: 16px; margin: 16px 0; display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
}
.date-filter label { font-weight: 600; font-size: 0.9rem; }
.date-filter input[type="date"] {
    padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px;
    font-size: 0.9rem; font-family: inherit;
}
.date-filter .filter-info { color: var(--text-muted); font-size: 0.85rem; margin-left: auto; }
.date-filter button {
    padding: 6px 14px; border: 1px solid var(--border); border-radius: 6px;
    background: var(--card-bg); cursor: pointer; font-size: 0.85rem; font-family: inherit;
}
.date-filter button:hover { background: #e9ecef; }
.hidden-by-filter { display: none !important; }
footer { margin-top: 48px; padding-top: 16px; border-top: 1px solid var(--border); color: var(--text-muted); font-size: 0.8rem; text-align: center; }
"""

# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------

_JS = """\
document.addEventListener('DOMContentLoaded', function() {
    // Collapsible sections
    document.querySelectorAll('.collapsible').forEach(function(el) {
        el.addEventListener('click', function() {
            this.classList.toggle('open');
            var content = this.nextElementSibling;
            if (content) content.classList.toggle('show');
        });
    });

    // Table sorting
    document.querySelectorAll('th[data-sort]').forEach(function(th) {
        th.addEventListener('click', function() {
            var table = this.closest('table');
            var tbody = table.querySelector('tbody');
            var rows = Array.from(tbody.querySelectorAll('tr'));
            var idx = Array.from(this.parentNode.children).indexOf(this);
            var type = this.dataset.sort;
            var asc = this.dataset.dir !== 'asc';
            this.dataset.dir = asc ? 'asc' : 'desc';

            rows.sort(function(a, b) {
                var av = a.children[idx].textContent.trim();
                var bv = b.children[idx].textContent.trim();
                if (type === 'num') { av = parseFloat(av) || 0; bv = parseFloat(bv) || 0; }
                if (av < bv) return asc ? -1 : 1;
                if (av > bv) return asc ? 1 : -1;
                return 0;
            });

            rows.forEach(function(row) { tbody.appendChild(row); });
        });
    });

    // Date range filter
    var report = JSON.parse(document.getElementById('report-data').textContent);
    var fromInput = document.getElementById('filter-from');
    var toInput = document.getElementById('filter-to');
    var resetBtn = document.getElementById('filter-reset');
    var filterInfo = document.getElementById('filter-info');

    if (fromInput && toInput) {
        // Set initial values from PR date range
        var dates = report.pr_summaries.map(function(pr) {
            return pr.date.substring(0, 10);
        }).sort();
        if (dates.length) {
            fromInput.value = dates[0];
            toInput.value = dates[dates.length - 1];
            fromInput.min = dates[0];
            toInput.max = dates[dates.length - 1];
        }

        function applyDateFilter() {
            var from = fromInput.value;
            var to = toInput.value;
            var visibleRefs = new Set();

            // Determine which PR refs are in range
            report.pr_summaries.forEach(function(pr) {
                var d = pr.date.substring(0, 10);
                if ((!from || d >= from) && (!to || d <= to)) {
                    visibleRefs.add(pr.ref);
                }
            });

            // Filter PR table rows
            document.querySelectorAll('[data-pr-ref]').forEach(function(el) {
                var ref = el.dataset.prRef;
                if (visibleRefs.has(ref)) {
                    el.classList.remove('hidden-by-filter');
                } else {
                    el.classList.add('hidden-by-filter');
                }
            });

            // Filter test execution rows (keyed by pr_ref embedded in test_id)
            document.querySelectorAll('[data-exec-pr]').forEach(function(el) {
                var ref = el.dataset.execPr;
                if (visibleRefs.has(ref)) {
                    el.classList.remove('hidden-by-filter');
                } else {
                    el.classList.add('hidden-by-filter');
                }
            });

            // Recompute metrics from visible PRs
            var totalPrs = 0, totalFiles = 0, screensSet = {}, testsGen = 0;
            var passed = 0, failed = 0, skipped = 0;

            report.pr_summaries.forEach(function(pr) {
                if (!visibleRefs.has(pr.ref)) return;
                totalPrs++;
                totalFiles += pr.files_changed;
            });

            report.analyzer_results.forEach(function(a) {
                if (!visibleRefs.has(a.pr_ref)) return;
                a.affected_screens.forEach(function(s) { screensSet[s] = 1; });
            });

            report.generated_tests.forEach(function(t) {
                if (!visibleRefs.has(t.pr_ref)) return;
                testsGen++;
            });

            report.execution_results.forEach(function(e) {
                // Match test to PR via generated_tests lookup
                var test = report.generated_tests.find(function(t) { return t.test_id === e.test_id; });
                if (!test || !visibleRefs.has(test.pr_ref)) return;
                if (e.status === 'passed') passed++;
                else if (e.status === 'failed') failed++;
                else skipped++;
            });

            var totalExec = passed + failed + skipped;
            var passRate = totalExec > 0 ? (passed / totalExec * 100).toFixed(1) : '0.0';
            var screensAffected = Object.keys(screensSet).length;

            // Update metric cards
            var cards = document.querySelectorAll('.metric-card .value');
            if (cards.length >= 5) {
                cards[0].textContent = totalPrs;
                cards[1].textContent = totalFiles;
                cards[2].textContent = screensAffected;
                cards[3].textContent = testsGen;
                cards[4].textContent = passRate + '%';
                var pr = parseFloat(passRate);
                cards[4].style.color = pr >= 80 ? 'var(--green)' : pr >= 50 ? 'var(--yellow)' : 'var(--red)';
            }

            // Update filter info
            if (filterInfo) {
                filterInfo.textContent = 'Showing ' + totalPrs + ' of ' + report.pr_summaries.length + ' PRs';
            }
        }

        fromInput.addEventListener('change', applyDateFilter);
        toInput.addEventListener('change', applyDateFilter);
        if (resetBtn) {
            resetBtn.addEventListener('click', function() {
                if (dates.length) {
                    fromInput.value = dates[0];
                    toInput.value = dates[dates.length - 1];
                } else {
                    fromInput.value = '';
                    toInput.value = '';
                }
                applyDateFilter();
            });
        }
    }
});
"""


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def _render_header(report: ReportData) -> str:
    return f"""\
<h1>{_esc(report.app_name)} — Test Report</h1>
<p class="subtitle">
    Generated {_esc(report.generated_at)} &middot;
    Version: {_esc(report.version_info)} &middot;
    Report ID: {_esc(report.report_id)}
</p>
<div class="trigger-info">
    <dl>
        <dt>Trigger:</dt><dd>{_esc(report.trigger.mode)}</dd>
        <dt>Range:</dt><dd><code>{_esc(report.trigger.commit_range)}</code></dd>
        <dt>Description:</dt><dd>{_esc(report.trigger.description)}</dd>
    </dl>
</div>
<div class="date-filter">
    <label for="filter-from">From:</label>
    <input type="date" id="filter-from">
    <label for="filter-to">To:</label>
    <input type="date" id="filter-to">
    <button id="filter-reset">Reset</button>
    <span class="filter-info" id="filter-info"></span>
</div>
"""


def _render_metrics(m: AggregateMetrics) -> str:
    pass_color = "var(--green)" if m.pass_rate >= 80 else "var(--yellow)" if m.pass_rate >= 50 else "var(--red)"
    return f"""\
<h2>Overview</h2>
<div class="metrics">
    <div class="metric-card">
        <div class="value">{m.total_prs}</div>
        <div class="label">PRs Analyzed</div>
    </div>
    <div class="metric-card">
        <div class="value">{m.total_files_changed}</div>
        <div class="label">Files Changed</div>
    </div>
    <div class="metric-card">
        <div class="value">{m.screens_affected}</div>
        <div class="label">Screens Affected</div>
    </div>
    <div class="metric-card">
        <div class="value">{m.tests_generated}</div>
        <div class="label">Tests Generated</div>
    </div>
    <div class="metric-card">
        <div class="value" style="color: {pass_color}">{m.pass_rate}%</div>
        <div class="label">Pass Rate</div>
    </div>
</div>
"""


def _render_pr_table(prs: list[PRSummary]) -> str:
    if not prs:
        return "<h2>PR Summary</h2><p>No PRs analyzed.</p>"

    rows = ""
    for pr in prs:
        cats = pr.change_categories
        badges = ""
        for cat, count in sorted(cats.items()):
            if count > 0:
                badges += f'<span class="badge badge-{cat}">{cat}: {count}</span> '
        rows += f"""\
<tr data-pr-ref="{_esc(pr.ref)}">
    <td><code>{_esc(pr.ref)}</code></td>
    <td>{_esc(pr.title)}</td>
    <td>{_esc(pr.author)}</td>
    <td>{pr.files_changed}</td>
    <td>+{pr.insertions} / -{pr.deletions}</td>
    <td>{badges}</td>
</tr>
"""
    return f"""\
<h2>PR Summary</h2>
<table>
<thead><tr>
    <th data-sort="str">Ref</th>
    <th data-sort="str">Title</th>
    <th data-sort="str">Author</th>
    <th data-sort="num">Files</th>
    <th data-sort="str">Changes</th>
    <th>Categories</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>
"""


def _render_analyzer_details(summaries: list[AnalyzerSummary]) -> str:
    if not summaries:
        return "<h2>Analyzer Details</h2><p>No analysis results.</p>"

    sections = ""
    for s in summaries:
        # Change breakdown
        breakdown = (
            f"UI: {s.ui_count}, Logic: {s.logic_count}, "
            f"Test: {s.test_count}, Infra: {s.infra_count}"
        )

        # Natures
        natures = ", ".join(f"{k}: {v}" for k, v in sorted(s.change_natures.items())) or "none"

        # Confidences
        confs = ", ".join(f"{k}: {v}" for k, v in sorted(s.trace_confidences.items())) or "none"

        # Screens
        screen_list = ""
        for screen in s.affected_screens:
            screen_list += f"<li><code>{_esc(screen)}</code></li>"

        # Chains
        chains_html = ""
        for chain in s.dependency_chains:
            parts = f' <span class="chain-arrow">&rarr;</span> '.join(_esc(c) for c in chain)
            chains_html += f'<div class="chain">{parts}</div>'

        sections += f"""\
<div data-pr-ref="{_esc(s.pr_ref)}">
<h3 class="collapsible">{_esc(s.pr_ref)} — {s.total_files} files</h3>
<div class="collapse-content">
    <p><strong>Change breakdown:</strong> {breakdown}</p>
    <p><strong>Change natures:</strong> {natures}</p>
    <p><strong>Trace confidences:</strong> {confs}</p>
    <p><strong>Affected screens:</strong></p>
    <ul>{screen_list}</ul>
    {f'<p><strong>Dependency chains:</strong></p>{chains_html}' if chains_html else ''}
</div>
</div>
"""
    return f"<h2>Analyzer Details</h2>{sections}"


def _render_test_generation(tests: list[GeneratedTest]) -> str:
    if not tests:
        return "<h2>Generated Tests</h2><p>No tests generated.</p>"

    # Group tests by screen
    by_screen: dict[str, list[GeneratedTest]] = {}
    for t in tests:
        by_screen.setdefault(t.screen, []).append(t)

    sections = ""
    for screen, screen_tests in by_screen.items():
        screen_name = Path(screen).stem
        test_cards = ""
        for t in screen_tests:
            step_rows = ""
            for step in t.steps:
                step_rows += f"""\
<tr>
    <td>{step.order}</td>
    <td>{_esc(step.action)}</td>
    <td><code>{_esc(step.target)}</code></td>
    <td>{_esc(step.value)}</td>
    <td>{_esc(step.expected)}</td>
</tr>
"""
            test_cards += f"""\
<div style="margin: 8px 0;" data-pr-ref="{_esc(t.pr_ref)}">
    <strong>{_esc(t.test_name)}</strong>
    <span class="badge badge-{t.priority}">{t.priority}</span>
    <p style="color: var(--text-muted); font-size: 0.85rem;">{_esc(t.description)}</p>
    <table class="step-table">
    <thead><tr><th>#</th><th>Action</th><th>Target</th><th>Value</th><th>Expected</th></tr></thead>
    <tbody>{step_rows}</tbody>
    </table>
</div>
"""
        sections += f"""\
<h3 class="collapsible">{_esc(screen_name)} ({len(screen_tests)} test{'s' if len(screen_tests) != 1 else ''})</h3>
<div class="collapse-content">{test_cards}</div>
"""
    return f"<h2>Generated Tests</h2>{sections}"


def _render_execution(
    executions: list[TestExecutionResult],
    test_pr_map: dict[str, str],
) -> str:
    if not executions:
        return "<h2>Test Execution</h2><p>No execution results.</p>"

    rows = ""
    for e in executions:
        pr_ref = test_pr_map.get(e.test_id, "")
        rows += f"""\
<tr data-pr-ref="{_esc(pr_ref)}" data-exec-pr="{_esc(pr_ref)}">
    <td><code>{_esc(e.test_id)}</code></td>
    <td><span class="badge badge-{e.status}">{e.status}</span></td>
    <td>{e.duration_ms}ms</td>
    <td>{e.steps_completed}/{e.steps_total}</td>
    <td>{_esc(e.failure_reason)}</td>
</tr>
"""
    return f"""\
<h2>Test Execution</h2>
<table>
<thead><tr>
    <th data-sort="str">Test ID</th>
    <th data-sort="str">Status</th>
    <th data-sort="num">Duration</th>
    <th data-sort="str">Steps</th>
    <th>Failure Reason</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>
"""


def _esc(text: str) -> str:
    """HTML-escape a string."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def render_report(report: ReportData) -> str:
    """Render a complete self-contained HTML dashboard."""
    embedded_json = json.dumps(asdict(report), indent=2)
    # Escape </script> inside JSON to prevent premature tag close
    embedded_json = embedded_json.replace("</", "<\\/")

    # Build test_id → pr_ref lookup for execution rows
    test_pr_map = {t.test_id: t.pr_ref for t in report.generated_tests}

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(report.app_name)} — Test Report {_esc(report.report_id)}</title>
<style>{_CSS}</style>
</head>
<body>
{_render_header(report)}
{_render_metrics(report.metrics)}
{_render_pr_table(report.pr_summaries)}
{_render_analyzer_details(report.analyzer_results)}
{_render_test_generation(report.generated_tests)}
{_render_execution(report.execution_results, test_pr_map)}
<footer>
    Generated by apptest &middot; {_esc(report.generated_at)}
</footer>
<script type="application/json" id="report-data">
{embedded_json}
</script>
<script>{_JS}</script>
</body>
</html>
"""


def write_report_html(report: ReportData, output_dir: Path) -> Path:
    """Render and write the HTML report to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "report.html"
    path.write_text(render_report(report))
    return path


# ---------------------------------------------------------------------------
# Index page
# ---------------------------------------------------------------------------

def render_index(entries: list[ReportIndexEntry], app_name: str) -> str:
    """Render the historical report index as HTML."""
    rows = ""
    for e in entries:
        pass_color = "badge-passed" if e.pass_rate >= 80 else "badge-skipped" if e.pass_rate >= 50 else "badge-failed"
        rows += f"""\
<tr>
    <td><a href="{_esc(e.report_path)}">{_esc(e.report_id)}</a></td>
    <td>{_esc(e.generated_at)}</td>
    <td>{e.total_prs}</td>
    <td>{e.screens_affected}</td>
    <td>{e.tests_generated}</td>
    <td><span class="badge {pass_color}">{e.pass_rate}%</span></td>
</tr>
"""
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(app_name)} — Report History</title>
<style>{_CSS}</style>
</head>
<body>
<h1>{_esc(app_name)} — Report History</h1>
<p class="subtitle">All generated reports</p>
<table>
<thead><tr>
    <th data-sort="str">Report</th>
    <th data-sort="str">Generated</th>
    <th data-sort="num">PRs</th>
    <th data-sort="num">Screens</th>
    <th data-sort="num">Tests</th>
    <th data-sort="num">Pass Rate</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>
<footer>Generated by apptest</footer>
<script>{_JS}</script>
</body>
</html>
"""
