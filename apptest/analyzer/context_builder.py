"""Build analysis context organised by change type.

Classifies every changed file, traces logic changes through dependency
chains to their screen consumers, and gathers surrounding context
(full source, layouts, strings) for the LLM.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .change_classifier import ClassifiedFile, classify_changed_files
from .dependency_tracer import TraceResult, trace_to_screen
from .diff_parser import ChangedFile
from .layout_parser import LayoutInfo, parse_layout
from .manifest_parser import ActivityInfo
from .strings_parser import filter_strings, parse_strings


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class UIChangeContext:
    file: str
    diff: str
    type: str                           # "ui_layout", "ui_strings", ...
    content: str                        # Full file content
    affected_screens: list[str] = field(default_factory=list)  # Screens using this layout/resource
    related_strings: dict[str, str] = field(default_factory=dict)  # For ui_layout: resolved string refs
    layout_info: dict | None = None     # Parsed layout data (IDs, strings, includes, views)


@dataclass
class LogicChangeContext:
    file: str
    diff: str
    full_source: str
    type: str                           # "logic_viewmodel", "logic_repository", ...
    change_nature: str                  # "new_feature", "bug_fix", ...
    dependency_chain: list[str]
    affected_screens: list[str]
    trace_confidence: str
    screen_context: list[dict]          # [{screen_file, screen_source, layout, layout_file}]


@dataclass
class TestChangeContext:
    file: str
    diff: str
    note: str


@dataclass
class InfraChangeContext:
    file: str
    diff: str
    type: str


@dataclass
class AnalysisResult:
    app_name: str
    app_package: str
    diff_ref: str
    total_changed_files: int
    ui_changes: list[UIChangeContext] = field(default_factory=list)
    logic_changes: list[LogicChangeContext] = field(default_factory=list)
    test_changes: list[TestChangeContext] = field(default_factory=list)
    infra_changes: list[InfraChangeContext] = field(default_factory=list)
    all_activities: list[str] = field(default_factory=list)
    pr_number: int | None = None
    pr_title: str | None = None
    pr_url: str | None = None
    repo_url: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_layout_for_screen(screen_name: str, repo_path: Path, layouts_dir: str) -> Path | None:
    """Find layout XML matching a screen name by naming convention."""
    base = screen_name.removesuffix("Activity").removesuffix("Fragment")
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", base).lower()
    for prefix in ("fragment_", "activity_", "view_"):
        candidate = repo_path / layouts_dir / f"{prefix}{snake}.xml"
        if candidate.exists():
            return candidate
    return None


def _read_file(repo_path: Path, rel_path: str) -> str:
    """Read a file relative to repo root, returning empty string on error."""
    full = repo_path / rel_path
    if not full.exists():
        return ""
    try:
        return full.read_text(errors="replace")
    except OSError:
        return ""


def _layout_name_to_screen_hint(layout_name: str) -> str:
    """Convert e.g. 'fragment_search' to 'Search' for matching screens."""
    for prefix in ("fragment_", "activity_", "view_", "item_"):
        if layout_name.startswith(prefix):
            name = layout_name.removeprefix(prefix)
            return "".join(w.capitalize() for w in name.split("_"))
    return ""


def _find_screen_for_layout(layout_path: str, repo_path: Path, source_root: str) -> str | None:
    """Try to match a layout file to a screen file on disk."""
    stem = Path(layout_path).stem
    hint = _layout_name_to_screen_hint(stem)
    if not hint:
        return None
    source_dir = repo_path / source_root
    if not source_dir.exists():
        return None
    for suffix in ("Fragment", "Activity"):
        target = hint + suffix
        for fpath in source_dir.rglob(f"{target}.kt"):
            return str(fpath.relative_to(repo_path))
        for fpath in source_dir.rglob(f"{target}.java"):
            return str(fpath.relative_to(repo_path))
    return None


def _find_screens_for_layout(layout_path: str, repo_path: Path, source_root: str) -> list[str]:
    """Like _find_screen_for_layout but returns ALL matching screens."""
    stem = Path(layout_path).stem
    hint = _layout_name_to_screen_hint(stem)
    if not hint:
        return []
    source_dir = repo_path / source_root
    if not source_dir.exists():
        return []
    screens: list[str] = []
    for suffix in ("Fragment", "Activity"):
        target = hint + suffix
        for fpath in source_dir.rglob(f"{target}.kt"):
            rel = str(fpath.relative_to(repo_path))
            if rel not in screens:
                screens.append(rel)
        for fpath in source_dir.rglob(f"{target}.java"):
            rel = str(fpath.relative_to(repo_path))
            if rel not in screens:
                screens.append(rel)
    return screens


def _find_layouts_referencing_resource(
    name: str,
    resource_type: str,
    repo_path: Path,
    layouts_dir: str,
) -> list[str]:
    """Find layout XML files that reference a given resource name.

    Args:
        name: Resource name (e.g. "search_hint" for a string, "ic_search" for a drawable).
        resource_type: "string" or "drawable".
        repo_path: Absolute path to the repo root.
        layouts_dir: Relative path to the layout directory.

    Returns:
        List of layout file paths relative to repo_path.
    """
    layouts_path = repo_path / layouts_dir
    if not layouts_path.is_dir():
        return []

    results: list[str] = []
    for xml_file in sorted(layouts_path.glob("*.xml")):
        try:
            info = parse_layout(xml_file)
        except Exception:
            continue
        if resource_type == "string" and name in info.referenced_strings:
            results.append(str(xml_file.relative_to(repo_path)))
        elif resource_type == "drawable" and name in info.referenced_drawables:
            results.append(str(xml_file.relative_to(repo_path)))
    return results


def _trace_resource_to_screens(
    names: list[str],
    resource_type: str,
    repo_path: Path,
    source_root: str,
    layouts_dir: str,
) -> list[str]:
    """Two-hop trace: resource names → layouts → screens.

    Args:
        names: List of resource names to look up.
        resource_type: "string" or "drawable".
        repo_path: Absolute path to the repo root.
        source_root: Relative path to Java/Kotlin source root.
        layouts_dir: Relative path to the layout directory.

    Returns:
        De-duplicated list of screen file paths (relative to repo_path).
    """
    screens: list[str] = []
    for name in names:
        layout_paths = _find_layouts_referencing_resource(
            name, resource_type, repo_path, layouts_dir,
        )
        for lp in layout_paths:
            for screen in _find_screens_for_layout(lp, repo_path, source_root):
                if screen not in screens:
                    screens.append(screen)
    return screens


# ---------------------------------------------------------------------------
# Per-type context builders
# ---------------------------------------------------------------------------

def _build_ui_context(
    cf: ClassifiedFile,
    repo_path: Path,
    source_root: str,
    layouts_dir: str,
    all_strings: dict[str, str],
) -> UIChangeContext:
    content = _read_file(repo_path, cf.file.path)
    affected_screens: list[str] = []
    related_strings: dict[str, str] = {}
    layout_info: dict | None = None

    if cf.category == "ui_layout":
        # Direct name-based screen match (now multi-screen)
        affected_screens = _find_screens_for_layout(cf.file.path, repo_path, source_root)
        # Also find parent layouts that <include> this layout
        stem = Path(cf.file.path).stem
        layouts_path = repo_path / layouts_dir
        if layouts_path.is_dir():
            for xml_file in sorted(layouts_path.glob("*.xml")):
                try:
                    parent_info = parse_layout(xml_file)
                except Exception:
                    continue
                if stem in parent_info.include_layouts:
                    parent_screens = _find_screens_for_layout(
                        str(xml_file.relative_to(repo_path)), repo_path, source_root,
                    )
                    for s in parent_screens:
                        if s not in affected_screens:
                            affected_screens.append(s)

        full_path = repo_path / cf.file.path
        if full_path.exists():
            try:
                info = parse_layout(full_path)
                layout_info = {
                    "filename": info.filename,
                    "referenced_ids": info.referenced_ids,
                    "referenced_strings": info.referenced_strings,
                    "referenced_drawables": info.referenced_drawables,
                    "include_layouts": info.include_layouts,
                    "view_types": info.view_types,
                }
                related_strings = filter_strings(all_strings, set(info.referenced_strings))
            except Exception:
                pass

    elif cf.category == "ui_strings":
        # Parse the strings file to get changed string names, trace through layouts
        full_path = repo_path / cf.file.path
        if full_path.exists():
            try:
                string_names = list(parse_strings(full_path).keys())
                affected_screens = _trace_resource_to_screens(
                    string_names, "string", repo_path, source_root, layouts_dir,
                )
            except Exception:
                pass

    elif cf.category == "ui_drawable":
        # Extract drawable name from filename stem, trace through layouts
        drawable_name = Path(cf.file.path).stem
        affected_screens = _trace_resource_to_screens(
            [drawable_name], "drawable", repo_path, source_root, layouts_dir,
        )

    elif cf.category == "ui_resource":
        # Generic resource — try string names first, then drawable name as fallback
        full_path = repo_path / cf.file.path
        if full_path.exists():
            try:
                string_names = list(parse_strings(full_path).keys())
                if string_names:
                    affected_screens = _trace_resource_to_screens(
                        string_names, "string", repo_path, source_root, layouts_dir,
                    )
            except Exception:
                pass
        if not affected_screens:
            drawable_name = Path(cf.file.path).stem
            affected_screens = _trace_resource_to_screens(
                [drawable_name], "drawable", repo_path, source_root, layouts_dir,
            )

    return UIChangeContext(
        file=cf.file.path,
        diff=cf.file.diff_content,
        type=cf.category,
        content=content,
        affected_screens=affected_screens,
        related_strings=related_strings,
        layout_info=layout_info,
    )


_SCREEN_FANOUT_THRESHOLD = 5


def _narrow_screens(
    screen_files: list[str],
    pr_changed_files: set[str],
) -> list[str]:
    """When a file traces to too many screens, prefer PR-changed ones."""
    if len(screen_files) <= _SCREEN_FANOUT_THRESHOLD:
        return screen_files
    # Keep only screens that are also changed in this PR
    pr_screens = [s for s in screen_files if s in pr_changed_files]
    if pr_screens:
        return pr_screens
    # If none overlap, return a capped list
    return screen_files[:_SCREEN_FANOUT_THRESHOLD]


def _build_logic_context(
    cf: ClassifiedFile,
    repo_path: Path,
    source_root: str,
    layouts_dir: str,
    exclude_dirs: list[str],
    pr_changed_files: set[str] | None = None,
    profile: dict | None = None,
) -> LogicChangeContext:
    full_source = _read_file(repo_path, cf.file.path)

    # Fast path: try profile lookup first
    trace: TraceResult | None = None
    if profile is not None:
        from ..scanner.profile_manager import lookup_affected_screens
        profile_hits = lookup_affected_screens(cf.file.path, profile)
        if profile_hits:
            screen_files = [h["screen_file"] for h in profile_hits]
            chain = profile_hits[0].get("chain", [cf.file.path] + screen_files[:1])
            confidence = profile_hits[0].get("confidence", "medium")
            trace = TraceResult(
                chain=chain,
                screen_files=screen_files,
                confidence=confidence,
            )

    # Fallback: runtime tracing
    if trace is None:
        trace = trace_to_screen(
            file_path=cf.file.path,
            file_type=cf.category,
            repo_path=str(repo_path),
            source_root=source_root,
            exclude_dirs=exclude_dirs,
        )

    narrowed_screens = _narrow_screens(
        trace.screen_files, pr_changed_files or set()
    )

    screen_context: list[dict] = []
    for screen_file in narrowed_screens:
        ctx: dict = {
            "screen_file": screen_file,
            "screen_source": _read_file(repo_path, screen_file),
        }
        screen_name = Path(screen_file).stem
        layout_path = _find_layout_for_screen(screen_name, repo_path, layouts_dir)
        if layout_path:
            ctx["layout_file"] = str(layout_path.relative_to(repo_path))
            ctx["layout"] = layout_path.read_text(errors="replace")
        screen_context.append(ctx)

    return LogicChangeContext(
        file=cf.file.path,
        diff=cf.file.diff_content,
        full_source=full_source,
        type=cf.category,
        change_nature=cf.change_nature or "modification",
        dependency_chain=trace.chain,
        affected_screens=narrowed_screens,
        trace_confidence=trace.confidence,
        screen_context=screen_context,
    )


def _build_test_context(cf: ClassifiedFile) -> TestChangeContext:
    return TestChangeContext(
        file=cf.file.path,
        diff=cf.file.diff_content,
        note="Test change — may signal expected behaviour change.",
    )


def _build_infra_context(cf: ClassifiedFile) -> InfraChangeContext:
    return InfraChangeContext(
        file=cf.file.path,
        diff=cf.file.diff_content,
        type=cf.category,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_context(
    changed_files: list[ChangedFile],
    activities: list[ActivityInfo],
    repo_path: Path,
    source_root: str,
    layouts_dir: str,
    strings_file: str,
    exclude_dirs: list[str],
    app_name: str,
    app_package: str,
    diff_ref: str,
    profile: dict | None = None,
    pr_number: int | None = None,
    pr_title: str | None = None,
    pr_url: str | None = None,
) -> AnalysisResult:
    """Classify every changed file and build per-type context.

    Args:
        changed_files: All changed files from the diff (unfiltered).
        activities: Activity declarations from the manifest.
        repo_path: Absolute path to the repository root.
        source_root: Relative path to source root.
        layouts_dir: Relative path to layout XML directory.
        strings_file: Relative path to strings.xml.
        exclude_dirs: Directory names to exclude from tracing.
        app_name: App display name.
        app_package: App package name.
        diff_ref: Git diff reference used.
        profile: Optional app profile for fast screen lookups.
        pr_number: Optional PR number for metadata.
        pr_title: Optional PR title for metadata.
        pr_url: Optional PR URL for metadata.
    """
    # Pre-load strings.xml
    strings_path = repo_path / strings_file
    all_strings: dict[str, str] = {}
    if strings_path.exists():
        all_strings = parse_strings(strings_path)

    # Classify all files
    classified = classify_changed_files(changed_files)

    # Collect all changed file paths for PR-scoped screen narrowing
    pr_changed_files = {cf.path for cf in changed_files}

    # Auto-detect repo URL from git remote if not derivable from pr_url
    repo_url = None
    if pr_url:
        parts = pr_url.rstrip("/").split("/")
        pull_idx = next((i for i, p in enumerate(parts) if p == "pull"), -1)
        if pull_idx >= 3:
            repo_url = "/".join(parts[:pull_idx]) + ".git"
    if not repo_url:
        import subprocess
        try:
            git_out = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=repo_path, capture_output=True, text=True, timeout=5,
            )
            if git_out.returncode == 0:
                repo_url = git_out.stdout.strip()
        except Exception:
            pass

    result = AnalysisResult(
        app_name=app_name,
        app_package=app_package,
        diff_ref=diff_ref,
        total_changed_files=len(changed_files),
        all_activities=[a.name for a in activities],
        pr_number=pr_number,
        pr_title=pr_title,
        pr_url=pr_url,
        repo_url=repo_url,
    )

    for cf in classified:
        cat = cf.category

        if cat.startswith("ui_"):
            result.ui_changes.append(
                _build_ui_context(cf, repo_path, source_root, layouts_dir, all_strings)
            )
        elif cat.startswith("logic_"):
            result.logic_changes.append(
                _build_logic_context(
                    cf, repo_path, source_root, layouts_dir, exclude_dirs,
                    pr_changed_files, profile,
                )
            )
        elif cat == "test":
            result.test_changes.append(_build_test_context(cf))
        elif cat.startswith("infra_"):
            result.infra_changes.append(_build_infra_context(cf))
        # "other" category is silently skipped

    return result


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_analysis(result: AnalysisResult, output_dir: Path) -> Path:
    """Write the analysis result to a JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "analysis.json"

    data = asdict(result)

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    return output_path
