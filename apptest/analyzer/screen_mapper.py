"""Map changed files to affected screens.

.. deprecated::
    This module is superseded by ``change_classifier`` + ``dependency_tracer``.
    The classifier categorises every changed file, and the tracer walks
    dependency chains to reach screen files.  This module is retained for
    backward compatibility and will be removed in a future release.

Uses pattern matching, package grouping, and Fragment→Activity resolution
to determine which screens are affected by a set of file changes.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from .diff_parser import ChangedFile
from .manifest_parser import ActivityInfo


@dataclass
class ScreenInfo:
    """Represents an identified screen (Activity or Fragment)."""
    name: str                              # e.g. "SearchFragment", "PageActivity"
    qualified_name: str                    # e.g. "org.wikipedia.search.SearchFragment"
    package: str                           # e.g. "org.wikipedia.search"
    screen_file: str                       # Path to the main screen file
    host_activity: str | None = None       # For Fragments: the hosting Activity
    related_files: list[str] = field(default_factory=list)  # ViewModels, Repos, etc.
    changed_files: list[str] = field(default_factory=list)  # Which changed files affect this screen
    layout_files: list[str] = field(default_factory=list)   # Associated layout XML files


# Patterns for identifying screen-related files
_ACTIVITY_PATTERN = re.compile(r"(\w+Activity)\.(kt|java)$")
_FRAGMENT_PATTERN = re.compile(r"(\w+Fragment)\.(kt|java)$")
_VIEWMODEL_PATTERN = re.compile(r"(\w+ViewModel)\.(kt|java)$")
_REPOSITORY_PATTERN = re.compile(r"(\w+Repository)\.(kt|java)$")
_ACTIVITY_LAYOUT_PATTERN = re.compile(r"activity_(\w+)\.xml$")
_FRAGMENT_LAYOUT_PATTERN = re.compile(r"fragment_(\w+)\.xml$")
_ITEM_LAYOUT_PATTERN = re.compile(r"item_(\w+)\.xml$")


def _extract_package(path: str, source_root: str) -> str:
    """Extract Java/Kotlin package from file path.

    e.g. "app/src/main/java/org/wikipedia/search/SearchFragment.kt"
    with source_root "app/src/main/java/org/wikipedia"
    → "org.wikipedia.search"
    """
    # Normalize to forward slashes
    path = path.replace("\\", "/")
    source_root = source_root.rstrip("/")

    # Find the source root in the path
    idx = path.find(source_root)
    if idx == -1:
        return ""

    # Get the relative path from source root, minus the file name
    rel = path[idx + len(source_root):].lstrip("/")
    parts = rel.split("/")
    if len(parts) <= 1:
        # File is directly in source root
        package_from_root = source_root.replace("/", ".")
        # Strip common prefixes like "app.src.main.java."
        java_idx = package_from_root.find("java.")
        if java_idx != -1:
            return package_from_root[java_idx + 5:]
        return package_from_root

    # Package is source_root converted + subdirectories (minus filename)
    package_from_root = source_root.replace("/", ".")
    java_idx = package_from_root.find("java.")
    if java_idx != -1:
        base_package = package_from_root[java_idx + 5:]
    else:
        base_package = package_from_root

    sub_package = ".".join(parts[:-1])
    return f"{base_package}.{sub_package}"


def _class_name_from_path(path: str) -> str:
    """Extract class name from file path."""
    return Path(path).stem


def _layout_name_to_class_hint(layout_name: str, prefix: str) -> str:
    """Convert layout name to a class name hint.

    e.g. "fragment_search" with prefix "fragment_" → "Search"
    which hints at "SearchFragment" or "SearchActivity"
    """
    name = layout_name.removeprefix(prefix)
    # Convert snake_case to PascalCase
    return "".join(word.capitalize() for word in name.split("_"))


def _find_activity_for_fragment(
    fragment_name: str,
    fragment_package: str,
    activities: list[ActivityInfo],
    source_root: str,
) -> str | None:
    """Try to find the hosting Activity for a Fragment.

    Strategies:
    1. Look for Activity in the same package
    2. Look for SingleFragmentActivity pattern (ActivityName matches FragmentName)
    3. Check if fragment name minus "Fragment" + "Activity" exists
    """
    base_name = fragment_name.removesuffix("Fragment")

    # Strategy 1 & 2: Check for matching Activity in same package
    for activity in activities:
        if activity.name.startswith(fragment_package + "."):
            # Same package — good candidate
            activity_simple = activity.name.rsplit(".", 1)[-1]
            # Direct match: SearchFragment → SearchActivity
            if activity_simple == base_name + "Activity":
                return activity.name

    # Strategy 3: Check for any Activity in the same package
    for activity in activities:
        if activity.name.startswith(fragment_package + "."):
            return activity.name

    return None


def map_changed_files(
    changed_files: list[ChangedFile],
    activities: list[ActivityInfo],
    source_root: str,
    layouts_dir: str,
) -> list[ScreenInfo]:
    """Map changed files to affected screens.

    Args:
        changed_files: List of files changed in the diff.
        activities: Activity declarations from the manifest.
        source_root: Root path for source files (e.g. "app/src/main/java/org/wikipedia").
        layouts_dir: Path to layout XML directory (e.g. "app/src/main/res/layout").
    """
    # Index: package → list of screens in that package
    screens: dict[str, ScreenInfo] = {}
    # Track which files we've associated
    unassociated: list[ChangedFile] = []

    # First pass: identify direct screen files (Activities and Fragments)
    for cf in changed_files:
        filename = Path(cf.path).name

        # Activity file
        match = _ACTIVITY_PATTERN.search(filename)
        if match:
            class_name = match.group(1)
            package = _extract_package(cf.path, source_root)
            qname = f"{package}.{class_name}" if package else class_name
            screens[qname] = ScreenInfo(
                name=class_name,
                qualified_name=qname,
                package=package,
                screen_file=cf.path,
                changed_files=[cf.path],
            )
            continue

        # Fragment file
        match = _FRAGMENT_PATTERN.search(filename)
        if match:
            class_name = match.group(1)
            package = _extract_package(cf.path, source_root)
            qname = f"{package}.{class_name}" if package else class_name
            host = _find_activity_for_fragment(class_name, package, activities, source_root)
            screens[qname] = ScreenInfo(
                name=class_name,
                qualified_name=qname,
                package=package,
                screen_file=cf.path,
                host_activity=host,
                changed_files=[cf.path],
            )
            continue

        # Not a direct screen file — handle later
        unassociated.append(cf)

    # Second pass: associate non-screen files (ViewModels, Repos, layouts)
    still_unassociated = []
    for cf in unassociated:
        filename = Path(cf.path).name
        associated = False

        # ViewModel → find screen in same package
        if _VIEWMODEL_PATTERN.search(filename):
            package = _extract_package(cf.path, source_root)
            for screen in screens.values():
                if screen.package == package:
                    screen.related_files.append(cf.path)
                    if cf.path not in screen.changed_files:
                        screen.changed_files.append(cf.path)
                    associated = True
                    break

        # Repository → find screen in same package (via ViewModel chain)
        elif _REPOSITORY_PATTERN.search(filename):
            package = _extract_package(cf.path, source_root)
            for screen in screens.values():
                if screen.package == package:
                    screen.related_files.append(cf.path)
                    if cf.path not in screen.changed_files:
                        screen.changed_files.append(cf.path)
                    associated = True
                    break

        # Layout files
        elif cf.path.startswith(layouts_dir) or "/res/layout/" in cf.path:
            layout_match = _FRAGMENT_LAYOUT_PATTERN.search(filename)
            if layout_match:
                hint = _layout_name_to_class_hint(Path(filename).stem, "fragment_")
                for screen in screens.values():
                    if hint in screen.name:
                        screen.layout_files.append(cf.path)
                        if cf.path not in screen.changed_files:
                            screen.changed_files.append(cf.path)
                        associated = True
                        break

            if not associated:
                layout_match = _ACTIVITY_LAYOUT_PATTERN.search(filename)
                if layout_match:
                    hint = _layout_name_to_class_hint(Path(filename).stem, "activity_")
                    for screen in screens.values():
                        if hint in screen.name:
                            screen.layout_files.append(cf.path)
                            if cf.path not in screen.changed_files:
                                screen.changed_files.append(cf.path)
                            associated = True
                            break

        if not associated:
            still_unassociated.append(cf)

    # Third pass: associate remaining files by package
    for cf in still_unassociated:
        if cf.language not in ("kt", "java"):
            continue
        package = _extract_package(cf.path, source_root)
        for screen in screens.values():
            if screen.package == package:
                screen.related_files.append(cf.path)
                if cf.path not in screen.changed_files:
                    screen.changed_files.append(cf.path)
                break

    # If we found no screens but have changed files in feature packages,
    # try to create screens from manifest activities in matching packages
    if not screens:
        for cf in changed_files:
            if cf.language not in ("kt", "java"):
                continue
            package = _extract_package(cf.path, source_root)
            if not package:
                continue
            # Check if there's an Activity in this package
            for activity in activities:
                if activity.name.startswith(package + "."):
                    activity_simple = activity.name.rsplit(".", 1)[-1]
                    if activity.name not in screens:
                        screens[activity.name] = ScreenInfo(
                            name=activity_simple,
                            qualified_name=activity.name,
                            package=package,
                            screen_file="",  # We don't have the actual file in the diff
                            changed_files=[cf.path],
                            related_files=[cf.path],
                        )
                    else:
                        if cf.path not in screens[activity.name].changed_files:
                            screens[activity.name].changed_files.append(cf.path)
                    break

    return list(screens.values())
