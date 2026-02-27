"""Parse AndroidManifest.xml to extract activity declarations."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

ANDROID_NS = "http://schemas.android.com/apk/res/android"


@dataclass
class ActivityInfo:
    name: str  # Fully qualified, e.g. "org.wikipedia.search.SearchActivity"
    exported: bool = False
    intent_filters: list[dict] = field(default_factory=list)
    is_launcher: bool = False


def _resolve_class_name(name: str, package: str) -> str:
    """Resolve a possibly-shortened class name to fully qualified."""
    if name.startswith("."):
        return package + name
    if "." not in name:
        return package + "." + name
    return name


def _parse_intent_filters(activity_elem: ET.Element) -> list[dict]:
    """Extract intent-filter actions, categories, and data from an activity element."""
    filters = []
    for intent_filter in activity_elem.findall("intent-filter"):
        f: dict = {"actions": [], "categories": [], "data": []}
        for action in intent_filter.findall("action"):
            name = action.get(f"{{{ANDROID_NS}}}name", "")
            if name:
                f["actions"].append(name)
        for category in intent_filter.findall("category"):
            name = category.get(f"{{{ANDROID_NS}}}name", "")
            if name:
                f["categories"].append(name)
        for data in intent_filter.findall("data"):
            d = {}
            for attr in ("scheme", "host", "path", "mimeType"):
                val = data.get(f"{{{ANDROID_NS}}}{attr}", "")
                if val:
                    d[attr] = val
            if d:
                f["data"].append(d)
        filters.append(f)
    return filters


def parse_manifest(
    manifest_path: str | Path,
    namespace: str | None = None,
) -> list[ActivityInfo]:
    """Parse AndroidManifest.xml and return activity info.

    Args:
        manifest_path: Path to AndroidManifest.xml.
        namespace: App namespace (e.g. "org.wikipedia"). Used to resolve
            shorthand class names when the manifest has no package attribute
            (modern AGP uses namespace in build.gradle instead).
    """
    tree = ET.parse(manifest_path)
    root = tree.getroot()

    package = root.get("package", "") or namespace or ""

    activities = []
    # Handle both namespaced and non-namespaced manifest formats
    for activity in root.iter("activity"):
        name_attr = activity.get(f"{{{ANDROID_NS}}}name", "")
        if not name_attr:
            continue

        fq_name = _resolve_class_name(name_attr, package)
        exported_str = activity.get(f"{{{ANDROID_NS}}}exported", "")
        intent_filters = _parse_intent_filters(activity)

        # Exported defaults to true if intent-filters are present
        exported = exported_str.lower() == "true" if exported_str else bool(intent_filters)

        is_launcher = any(
            "android.intent.action.MAIN" in f.get("actions", [])
            and "android.intent.category.LAUNCHER" in f.get("categories", [])
            for f in intent_filters
        )

        activities.append(ActivityInfo(
            name=fq_name,
            exported=exported,
            intent_filters=intent_filters,
            is_launcher=is_launcher,
        ))

    return activities
