"""Manage the historical report index (JSON + HTML)."""

import json
import shutil
from pathlib import Path

from .html_renderer import render_index
from .report_schema import ReportData, ReportIndexEntry


def load_index(output_dir: str | Path) -> list[ReportIndexEntry]:
    """Load the report index from index.json."""
    index_path = Path(output_dir) / "index.json"
    if not index_path.exists():
        return []

    raw = json.loads(index_path.read_text())
    entries: list[ReportIndexEntry] = []
    for item in raw:
        entries.append(ReportIndexEntry(
            report_id=item["report_id"],
            generated_at=item["generated_at"],
            total_prs=item["total_prs"],
            screens_affected=item["screens_affected"],
            tests_generated=item["tests_generated"],
            pass_rate=item["pass_rate"],
            report_path=item["report_path"],
            json_path=item["json_path"],
        ))
    return entries


def add_to_index(
    output_dir: str | Path,
    report: ReportData,
    report_html_path: str,
    report_json_path: str,
    max_reports: int = 30,
    app_name: str = "",
) -> list[ReportIndexEntry]:
    """Add a report to the index, apply retention, and re-render.

    Args:
        output_dir: Directory containing the index and report subdirectories.
        report: The report data to add.
        report_html_path: Relative path to the HTML report file.
        report_json_path: Relative path to the JSON report file.
        max_reports: Maximum number of reports to keep.
        app_name: App name for the index page title.

    Returns:
        Updated list of index entries.
    """
    output_dir = Path(output_dir)
    entries = load_index(output_dir)

    entry = ReportIndexEntry(
        report_id=report.report_id,
        generated_at=report.generated_at,
        total_prs=report.metrics.total_prs,
        screens_affected=report.metrics.screens_affected,
        tests_generated=report.metrics.tests_generated,
        pass_rate=report.metrics.pass_rate,
        report_path=report_html_path,
        json_path=report_json_path,
    )
    entries.append(entry)

    entries = apply_retention(entries, max_reports, output_dir)
    write_index(output_dir, entries, app_name or report.app_name)
    return entries


def apply_retention(
    entries: list[ReportIndexEntry],
    max_reports: int,
    output_dir: Path | None = None,
) -> list[ReportIndexEntry]:
    """Remove oldest entries beyond the retention limit.

    If output_dir is provided, also deletes the report directories from disk.
    """
    if len(entries) <= max_reports:
        return entries

    # Sort by generated_at ascending so oldest are first
    entries.sort(key=lambda e: e.generated_at)
    to_remove = entries[: len(entries) - max_reports]
    kept = entries[len(entries) - max_reports :]

    if output_dir:
        for old in to_remove:
            # Report files are in {output_dir}/{report_id}/
            report_dir = output_dir / old.report_id
            if report_dir.is_dir():
                shutil.rmtree(report_dir, ignore_errors=True)

    return kept


def write_index(
    output_dir: str | Path,
    entries: list[ReportIndexEntry],
    app_name: str,
) -> None:
    """Write both index.json and index.html."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    data = []
    for e in entries:
        data.append({
            "report_id": e.report_id,
            "generated_at": e.generated_at,
            "total_prs": e.total_prs,
            "screens_affected": e.screens_affected,
            "tests_generated": e.tests_generated,
            "pass_rate": e.pass_rate,
            "report_path": e.report_path,
            "json_path": e.json_path,
        })
    (output_dir / "index.json").write_text(json.dumps(data, indent=2))

    # HTML
    (output_dir / "index.html").write_text(render_index(entries, app_name))
