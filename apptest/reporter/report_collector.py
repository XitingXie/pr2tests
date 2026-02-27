"""Git-based PR/commit collection for reports.

Collects commit metadata in three modes:
- manual: explicit commit range
- daily: commits since a date
- count: last N commits
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path

from .report_schema import PRSummary


_STATE_FILE = ".apptest/report-state.json"


def _git(args: list[str], repo: str | Path) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git"] + args,
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _parse_log_entry(entry: str) -> PRSummary | None:
    """Parse a single formatted git log entry into a PRSummary.

    Expected format (fields separated by \\x00):
        hash\\x00subject\\x00author\\x00date\\x00numstat_lines
    """
    parts = entry.split("\x00")
    if len(parts) < 4:
        return None

    ref = parts[0].strip()
    title = parts[1].strip()
    author = parts[2].strip()
    date = parts[3].strip()

    # Parse --numstat output for insertions/deletions/file count
    numstat = parts[4].strip() if len(parts) > 4 else ""
    files_changed = 0
    insertions = 0
    deletions = 0
    for line in numstat.splitlines():
        line = line.strip()
        if not line:
            continue
        cols = line.split("\t")
        if len(cols) >= 3:
            files_changed += 1
            ins = cols[0]
            dels = cols[1]
            insertions += int(ins) if ins != "-" else 0
            deletions += int(dels) if dels != "-" else 0

    if not ref:
        return None

    return PRSummary(
        ref=ref,
        title=title,
        author=author,
        date=date,
        files_changed=files_changed,
        insertions=insertions,
        deletions=deletions,
    )


_LOG_FORMAT = "%h%x00%s%x00%aN%x00%aI"
_ENTRY_SEPARATOR = "---ENTRY---"


def _run_log(repo: str | Path, extra_args: list[str]) -> list[PRSummary]:
    """Run git log with format and numstat, parse into PRSummary list."""
    # Use a two-pass approach: first get metadata, then get numstat per commit
    log_output = _git(
        ["log"] + extra_args + [f"--format={_ENTRY_SEPARATOR}{_LOG_FORMAT}"],
        repo,
    )
    if not log_output:
        return []

    # Split into entries and get refs
    entries = [e.strip() for e in log_output.split(_ENTRY_SEPARATOR) if e.strip()]
    summaries: list[PRSummary] = []
    for entry in entries:
        parts = entry.split("\x00")
        if len(parts) < 4:
            continue
        ref = parts[0].strip()
        title = parts[1].strip()
        author = parts[2].strip()
        date = parts[3].strip()
        if not ref:
            continue

        # Get numstat for this specific commit
        try:
            numstat = _git(["diff", "--numstat", f"{ref}~1..{ref}"], repo)
        except subprocess.CalledProcessError:
            # First commit or other edge case
            numstat = ""

        files_changed = 0
        insertions = 0
        deletions = 0
        for line in numstat.splitlines():
            line = line.strip()
            if not line:
                continue
            cols = line.split("\t")
            if len(cols) >= 3:
                files_changed += 1
                ins = cols[0]
                dels = cols[1]
                insertions += int(ins) if ins != "-" else 0
                deletions += int(dels) if dels != "-" else 0

        summaries.append(PRSummary(
            ref=ref,
            title=title,
            author=author,
            date=date,
            files_changed=files_changed,
            insertions=insertions,
            deletions=deletions,
        ))

    return summaries


def collect_prs_manual(repo: str | Path, commit_range: str) -> list[PRSummary]:
    """Collect PRs/commits in an explicit commit range.

    Args:
        repo: Path to git repository.
        commit_range: Git range like "abc123..def456".
    """
    return _run_log(repo, [commit_range])


def collect_prs_since(repo: str | Path, since_date: str) -> list[PRSummary]:
    """Collect PRs/commits since a date.

    Falls back to all commits (not just merges) if no merge commits found.

    Args:
        repo: Path to git repository.
        since_date: ISO date string like "2026-02-26".
    """
    # Try merge commits first
    summaries = _run_log(repo, ["--merges", "--first-parent", f"--since={since_date}"])
    if not summaries:
        # Fallback: treat each commit as a "PR" (squash-merge workflows)
        summaries = _run_log(repo, ["--first-parent", f"--since={since_date}"])
    return summaries


def collect_prs_last_n(repo: str | Path, n: int) -> list[PRSummary]:
    """Collect the last N PRs/commits.

    Falls back to all commits if no merge commits found.

    Args:
        repo: Path to git repository.
        n: Number of commits to collect.
    """
    summaries = _run_log(repo, ["--merges", "--first-parent", f"-n{n}"])
    if not summaries:
        summaries = _run_log(repo, ["--first-parent", f"-n{n}"])
    return summaries


def get_version_info(repo: str | Path) -> str:
    """Get a version string for the current HEAD."""
    return _git(["log", "-1", "--format=%h (%ci)"], repo)


def load_state(repo: str | Path) -> dict:
    """Load the report state file."""
    state_path = Path(repo) / _STATE_FILE
    if state_path.exists():
        return json.loads(state_path.read_text())
    return {}


def save_state(repo: str | Path, state: dict) -> None:
    """Save the report state file."""
    state_path = Path(repo) / _STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))


def update_state(repo: str | Path) -> None:
    """Update state with current timestamp and HEAD commit."""
    head = _git(["rev-parse", "--short", "HEAD"], repo)
    state = load_state(repo)
    state["last_report_timestamp"] = datetime.now().isoformat()
    state["last_reported_commit"] = head
    save_state(repo, state)
