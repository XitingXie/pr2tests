"""Run directory management for isolating pipeline runs."""

import re
from datetime import datetime
from pathlib import Path

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """Convert app name to a filesystem-safe slug (lowercase, hyphens)."""
    return _SLUG_RE.sub("-", name.lower()).strip("-")


def build_run_id(app_name: str) -> str:
    """Generate a timestamped run ID like ``wikipedia_20260227-100500``."""
    slug = _slugify(app_name)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{slug}_{ts}"


def create_run_dir(app_name: str, base: Path = Path(".apptest/runs")) -> Path:
    """Create a new run directory and update the ``latest-run`` pointer.

    Returns the created directory path.
    """
    run_id = build_run_id(app_name)
    run_dir = base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Write latest-run pointer one level above runs/
    pointer = base.parent / "latest-run"
    pointer.write_text(run_id)

    return run_dir


def get_latest_run(base: Path = Path(".apptest")) -> Path | None:
    """Read the ``latest-run`` pointer and return the run directory path.

    Returns ``None`` if the pointer is missing or the directory doesn't exist.
    """
    pointer = base / "latest-run"
    if not pointer.exists():
        return None

    run_id = pointer.read_text().strip()
    if not run_id:
        return None

    run_dir = base / "runs" / run_id
    if not run_dir.is_dir():
        return None

    return run_dir
