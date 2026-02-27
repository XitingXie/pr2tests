"""Classify changed files by type and classify diff nature.

Two pure functions with no file I/O — classification is based entirely on
file path patterns and diff content heuristics.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from .diff_parser import ChangedFile


@dataclass
class ClassifiedFile:
    """A ChangedFile with classification metadata."""
    file: ChangedFile
    category: str               # e.g. "ui_layout", "logic_viewmodel", "test", ...
    change_nature: str | None   # e.g. "new_feature", "bug_fix", ... (None for non-logic)


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------

_CODE_EXTENSIONS = {".kt", ".java"}
_LAYOUT_DIR_MARKER = "/res/layout/"
_STRINGS_FILENAME = "strings.xml"


def classify_file(path: str) -> str:
    """Classify a changed file by its path into a category string.

    Categories:
        ui_layout, ui_strings, ui_drawable, ui_resource,
        logic_screen, logic_compose_screen, logic_viewmodel,
        logic_repository, logic_datasource, logic_usecase, logic_api,
        logic_adapter, logic_model, logic_dialog, logic_callback,
        logic_abtest, logic_config, logic_compose_component,
        logic_extension, logic_util, logic_other,
        test, infra_build, infra_manifest, infra_config, other
    """
    p = Path(path)
    ext = p.suffix
    name = p.name
    path_lower = path.replace("\\", "/")

    # Test files
    if "/test/" in path_lower or "/androidTest/" in path_lower:
        return "test"

    # Build / infra files
    if ext in (".gradle", ".kts") or name in ("gradle.properties", "gradlew", "gradlew.bat"):
        return "infra_build"
    if "build.gradle" in name or "settings.gradle" in name:
        return "infra_build"
    if name == "AndroidManifest.xml":
        return "infra_manifest"
    if name in ("proguard-rules.pro", ".gitignore", "gradle-wrapper.properties"):
        return "infra_config"

    # XML resources
    if ext == ".xml":
        if _LAYOUT_DIR_MARKER in path_lower:
            return "ui_layout"
        if name == _STRINGS_FILENAME or "/res/values/" in path_lower:
            return "ui_strings"
        if "/res/drawable" in path_lower or "/res/mipmap" in path_lower:
            return "ui_drawable"
        if "/res/" in path_lower:
            return "ui_resource"
        return "other"

    # Non-XML resource files (images, etc.)
    if "/res/drawable" in path_lower or "/res/mipmap" in path_lower:
        return "ui_drawable"
    if "/res/" in path_lower:
        return "ui_resource"

    # Kotlin / Java source files
    if ext in _CODE_EXTENSIONS:
        return _classify_code_file(name, path)

    return "other"


def _classify_code_file(filename: str, path: str = "") -> str:
    """Sub-classify a .kt/.java file by its filename and path."""
    stem = Path(filename).stem
    path_lower = path.replace("\\", "/")

    # Screen files (direct UI hosts)
    if stem.endswith("Activity") or stem.endswith("Fragment"):
        return "logic_screen"

    # Dialog (UI host)
    if stem.endswith("Dialog") or stem.endswith("DialogFragment") or stem.endswith("BottomSheet"):
        return "logic_dialog"

    # Compose screen — files named *Screen.kt are Compose UI hosts
    if stem.endswith("Screen") or stem.endswith("ScreenDeck"):
        return "logic_compose_screen"

    # ViewModel
    if stem.endswith("ViewModel"):
        return "logic_viewmodel"

    # Repository
    if stem.endswith("Repository") or stem.endswith("Repo"):
        return "logic_repository"

    # DataSource
    if "DataSource" in stem:
        return "logic_datasource"

    # UseCase / Interactor
    if stem.endswith("UseCase") or stem.endswith("Interactor"):
        return "logic_usecase"

    # API / Service interfaces
    if stem.endswith("Api") or stem.endswith("Service") or stem.endswith("Client"):
        return "logic_api"

    # Adapter / ViewHolder (RecyclerView)
    if stem.endswith("Adapter") or stem.endswith("ViewHolder"):
        return "logic_adapter"

    # Model / Entity / DTO
    if stem.endswith("Model") or stem.endswith("Entity") or stem.endswith("Dto"):
        return "logic_model"

    # AB test / experiment
    if stem.endswith("AbTest") or stem.endswith("ABTest") or stem.endswith("AbCTest"):
        return "logic_abtest"

    # Callback / Listener interfaces
    if stem.endswith("Callback") or stem.endswith("Listener"):
        return "logic_callback"

    # Config / Prefs
    if stem in ("Prefs", "RemoteConfig", "AppConfig") or stem.endswith("Config"):
        return "logic_config"

    # Compose UI components (by path convention)
    if "/compose/components/" in path_lower or "/compose/theme/" in path_lower:
        return "logic_compose_component"

    # Extension files (by path convention)
    if "/extensions/" in path_lower:
        return "logic_extension"

    # Utility / Helper
    if stem.endswith("Util") or stem.endswith("Utils") or stem.endswith("Helper"):
        return "logic_util"

    # Compose views / UI components by name
    if stem.endswith("View") or stem.endswith("Views") or stem.endswith("CardView"):
        return "logic_compose_component"
    if stem.endswith("SkeletonLoader") or stem.endswith("Loader"):
        return "logic_compose_component"

    return "logic_other"


# ---------------------------------------------------------------------------
# Change-nature classification
# ---------------------------------------------------------------------------

_ERROR_KEYWORDS = re.compile(
    r"\b(try|catch|except|throw|throws|Exception|Error|finally|"
    r"IOException|IllegalState|IllegalArgument|RuntimeException)\b"
)
_FIX_KEYWORDS = re.compile(
    r"\b(fix|bug|crash|npe|null\s?pointer|workaround|hotfix|patch|issue)\b",
    re.IGNORECASE,
)
_PERF_KEYWORDS = re.compile(
    r"\b(cache|lazy|memo|throttle|debounce|optimize|performance|batch|pool)\b",
    re.IGNORECASE,
)
_VALIDATION_KEYWORDS = re.compile(
    r"\b(valid|require|check|assert|verify|constraint|sanitize|clamp)\b",
    re.IGNORECASE,
)


def classify_change_nature(diff_content: str) -> str:
    """Classify the nature of a code change from its unified diff content.

    Returns one of:
        new_feature, feature_removal, bug_fix, error_handling,
        refactor, performance, validation, modification
    """
    if not diff_content.strip():
        return "modification"

    added = 0
    removed = 0
    added_lines: list[str] = []
    removed_lines: list[str] = []

    for line in diff_content.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
            added_lines.append(line[1:])
        elif line.startswith("-"):
            removed += 1
            removed_lines.append(line[1:])

    all_change_text = "\n".join(added_lines + removed_lines)

    # Pure addition → new feature
    if added > 0 and removed == 0:
        return "new_feature"

    # Pure deletion → feature removal
    if removed > 0 and added == 0:
        return "feature_removal"

    # Bug fix signals (check before error_handling since fixes often touch error paths)
    if _FIX_KEYWORDS.search(all_change_text):
        return "bug_fix"

    # Error handling additions
    added_text = "\n".join(added_lines)
    if _ERROR_KEYWORDS.search(added_text) and added > removed:
        return "error_handling"

    # Performance changes
    if _PERF_KEYWORDS.search(all_change_text):
        return "performance"

    # Validation changes
    if _VALIDATION_KEYWORDS.search(added_text) and added > removed:
        return "validation"

    # Balanced edits → refactor
    if added > 0 and removed > 0:
        ratio = min(added, removed) / max(added, removed)
        if ratio > 0.6:
            return "refactor"

    return "modification"


# ---------------------------------------------------------------------------
# Batch helper
# ---------------------------------------------------------------------------

def classify_changed_files(changed_files: list[ChangedFile]) -> list[ClassifiedFile]:
    """Classify a list of ChangedFile objects."""
    results = []
    for cf in changed_files:
        category = classify_file(cf.path)
        nature: str | None = None
        if category.startswith("logic_"):
            nature = classify_change_nature(cf.diff_content)
        results.append(ClassifiedFile(file=cf, category=category, change_nature=nature))
    return results
