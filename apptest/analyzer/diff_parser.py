"""Parse git diffs into structured ChangedFile objects."""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ChangedFile:
    path: str
    status: str  # added, modified, deleted, renamed
    diff_content: str
    language: str  # kt, java, xml, etc.


_STATUS_MAP = {
    "A": "added",
    "M": "modified",
    "D": "deleted",
    "R": "renamed",
}

# Files we care about for Android analysis
_RELEVANT_EXTENSIONS = {".kt", ".java", ".xml"}

# Paths to exclude
_EXCLUDE_PATTERNS = [
    r"/test/",
    r"/androidTest/",
    r"/build/",
    r"\.gradle",
    r"/generated/",
]


def _detect_language(path: str) -> str:
    suffix = Path(path).suffix.lstrip(".")
    return suffix if suffix else "unknown"


def _is_relevant_file(path: str) -> bool:
    """Check if a file is relevant for Android UI analysis."""
    ext = Path(path).suffix
    if ext not in _RELEVANT_EXTENSIONS:
        return False
    for pattern in _EXCLUDE_PATTERNS:
        if re.search(pattern, path):
            return False
    return True


def _parse_name_status(output: str) -> dict[str, str]:
    """Parse `git diff --name-status` output into {path: status} map."""
    result = {}
    for line in output.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        raw_status = parts[0]
        # Handle rename status like R100
        status_char = raw_status[0]
        status = _STATUS_MAP.get(status_char, "modified")
        # For renames, use the new path (parts[2])
        path = parts[2] if status == "renamed" and len(parts) > 2 else parts[1]
        result[path] = status
    return result


def _split_diff_by_file(diff_output: str) -> dict[str, str]:
    """Split a unified diff into per-file chunks."""
    file_diffs: dict[str, str] = {}
    current_file = None
    current_lines: list[str] = []

    for line in diff_output.splitlines(keepends=True):
        if line.startswith("diff --git"):
            # Save previous file
            if current_file:
                file_diffs[current_file] = "".join(current_lines)
            # Extract path from "diff --git a/path b/path"
            match = re.match(r"diff --git a/.+ b/(.+)", line)
            current_file = match.group(1) if match else None
            current_lines = [line]
        else:
            current_lines.append(line)

    # Save last file
    if current_file:
        file_diffs[current_file] = "".join(current_lines)

    return file_diffs


def parse_diff_from_output(
    name_status_output: str,
    diff_output: str,
    filter_relevant: bool = True,
) -> list[ChangedFile]:
    """Parse pre-computed git diff outputs into ChangedFile objects.

    Args:
        name_status_output: Output from `git diff --name-status <ref>`.
        diff_output: Output from `git diff <ref>`.
        filter_relevant: If True, only include files relevant for Android analysis.
    """
    statuses = _parse_name_status(name_status_output)
    file_diffs = _split_diff_by_file(diff_output)

    results = []
    for path, status in statuses.items():
        if filter_relevant and not _is_relevant_file(path):
            continue
        results.append(ChangedFile(
            path=path,
            status=status,
            diff_content=file_diffs.get(path, ""),
            language=_detect_language(path),
        ))
    return results


def parse_diff(
    repo_path: str | Path,
    diff_ref: str = "HEAD~1..HEAD",
    filter_relevant: bool = True,
) -> list[ChangedFile]:
    """Run git diff on a repo and return structured ChangedFile objects.

    Args:
        repo_path: Path to the git repository.
        diff_ref: Git diff reference (e.g., "HEAD~1..HEAD" or a commit range).
        filter_relevant: If True, only include files relevant for Android analysis.
    """
    repo_path = Path(repo_path)

    # Get file list with statuses
    name_status = subprocess.run(
        ["git", "diff", "--name-status", diff_ref],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )

    # Get full diff content
    diff = subprocess.run(
        ["git", "diff", diff_ref],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )

    return parse_diff_from_output(name_status.stdout, diff.stdout, filter_relevant)
