"""Gather full context for each affected screen and produce analysis.json."""

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .diff_parser import ChangedFile
from .layout_parser import LayoutInfo, parse_layout
from .screen_mapper import ScreenInfo
from .strings_parser import filter_strings, parse_strings


@dataclass
class NavigationConnection:
    target: str       # Target screen class name
    method: str       # "startActivity", "replace", etc.
    direction: str    # "outgoing" or "incoming"


@dataclass
class ScreenContext:
    screen_name: str
    qualified_name: str
    package: str
    host_activity: str | None
    diff_content: dict[str, str]          # path → diff hunks
    source_content: dict[str, str]        # path → full file content
    layout_content: dict[str, str]        # layout file → content
    layout_info: list[dict]               # parsed layout data
    relevant_strings: dict[str, str]      # string name → value
    navigation: list[dict]                # navigation connections
    changed_files: list[str]
    related_files: list[str]


@dataclass
class AnalysisResult:
    app_name: str
    app_package: str
    diff_ref: str
    total_changed_files: int
    affected_screens: list[ScreenContext]


_INTENT_PATTERN = re.compile(
    r"(?:startActivity|startActivityForResult)\s*\(\s*"
    r"(?:Intent\s*\(\s*(?:this|context|activity|requireContext\(\))\s*,\s*"
    r"(\w+)::class\.java\s*\))"
)

_FRAGMENT_TRANSACTION_PATTERN = re.compile(
    r"\.(?:replace|add)\s*\([^,]*,\s*(\w+Fragment)\s*[\(.]"
)


def _find_navigation_in_source(source: str) -> list[NavigationConnection]:
    """Find navigation targets (Intents and Fragment transactions) in source code."""
    connections = []

    for match in _INTENT_PATTERN.finditer(source):
        target = match.group(1)
        connections.append(NavigationConnection(
            target=target,
            method="startActivity",
            direction="outgoing",
        ))

    for match in _FRAGMENT_TRANSACTION_PATTERN.finditer(source):
        target = match.group(1)
        connections.append(NavigationConnection(
            target=target,
            method="fragmentTransaction",
            direction="outgoing",
        ))

    return connections


def build_context(
    screens: list[ScreenInfo],
    changed_files: list[ChangedFile],
    repo_path: Path,
    layouts_dir: str,
    strings_file: str,
    app_name: str,
    app_package: str,
    diff_ref: str,
) -> AnalysisResult:
    """Build full context for each affected screen.

    Args:
        screens: Screens identified by screen_mapper.
        changed_files: All changed files from the diff.
        repo_path: Path to the repository root.
        layouts_dir: Relative path to layout XML directory.
        strings_file: Relative path to strings.xml.
        app_name: App display name.
        app_package: App package name.
        diff_ref: Git diff reference used.
    """
    # Pre-load strings.xml if it exists
    strings_path = repo_path / strings_file
    all_strings: dict[str, str] = {}
    if strings_path.exists():
        all_strings = parse_strings(strings_path)

    # Index changed files by path
    changed_by_path = {cf.path: cf for cf in changed_files}

    screen_contexts = []
    for screen in screens:
        # 1. Diff content for changed files in this screen's scope
        diff_content: dict[str, str] = {}
        for path in screen.changed_files:
            if path in changed_by_path:
                diff_content[path] = changed_by_path[path].diff_content

        # 2. Full source content of the screen file and related files
        source_content: dict[str, str] = {}
        files_to_read = [screen.screen_file] + screen.related_files
        for path in files_to_read:
            if not path:
                continue
            full_path = repo_path / path
            if full_path.exists():
                source_content[path] = full_path.read_text(errors="replace")

        # 3. Layout content — from changed layout files or by convention
        layout_content: dict[str, str] = {}
        layout_infos: list[dict] = []
        layout_paths: list[Path] = []

        # Add explicitly associated layout files
        for lf in screen.layout_files:
            lp = repo_path / lf
            if lp.exists():
                layout_paths.append(lp)

        # Try to find layout by naming convention if none explicitly found
        if not layout_paths:
            base_name = screen.name.removesuffix("Activity").removesuffix("Fragment")
            # Convert PascalCase to snake_case
            snake = re.sub(r"(?<!^)(?=[A-Z])", "_", base_name).lower()
            for prefix in ("fragment_", "activity_"):
                candidate = repo_path / layouts_dir / f"{prefix}{snake}.xml"
                if candidate.exists():
                    layout_paths.append(candidate)
                    break

        for lp in layout_paths:
            layout_content[lp.name] = lp.read_text(errors="replace")
            try:
                info = parse_layout(lp)
                layout_infos.append({
                    "filename": info.filename,
                    "referenced_ids": info.referenced_ids,
                    "referenced_strings": info.referenced_strings,
                    "include_layouts": info.include_layouts,
                    "view_types": info.view_types,
                })
            except Exception:
                pass  # Layout parsing is best-effort

        # 4. Relevant strings — only those referenced by this screen's layouts/code
        referenced_string_names: set[str] = set()
        for info in layout_infos:
            referenced_string_names.update(info.get("referenced_strings", []))
        # Also scan source code for R.string.xxx references
        for content in source_content.values():
            for match in re.finditer(r"R\.string\.(\w+)", content):
                referenced_string_names.add(match.group(1))
        relevant_strings = filter_strings(all_strings, referenced_string_names)

        # 5. Navigation connections — from source code analysis
        navigation: list[dict] = []
        for content in source_content.values():
            for conn in _find_navigation_in_source(content):
                navigation.append({
                    "target": conn.target,
                    "method": conn.method,
                    "direction": conn.direction,
                })

        screen_contexts.append(ScreenContext(
            screen_name=screen.name,
            qualified_name=screen.qualified_name,
            package=screen.package,
            host_activity=screen.host_activity,
            diff_content=diff_content,
            source_content=source_content,
            layout_content=layout_content,
            layout_info=layout_infos,
            relevant_strings=relevant_strings,
            navigation=navigation,
            changed_files=screen.changed_files,
            related_files=screen.related_files,
        ))

    return AnalysisResult(
        app_name=app_name,
        app_package=app_package,
        diff_ref=diff_ref,
        total_changed_files=len(changed_files),
        affected_screens=screen_contexts,
    )


def write_analysis(result: AnalysisResult, output_dir: Path) -> Path:
    """Write the analysis result to a JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "analysis.json"

    # Convert to dict for JSON serialization
    data = {
        "app_name": result.app_name,
        "app_package": result.app_package,
        "diff_ref": result.diff_ref,
        "total_changed_files": result.total_changed_files,
        "affected_screens": [asdict(sc) for sc in result.affected_screens],
    }

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    return output_path
