"""Auto-update the app profile from PR changes.

Patches the 'auto' section only — never touches 'overrides'.
Handles new screens, deleted files, and updated dependency chains.
"""

from pathlib import Path

from .change_classifier import classify_file
from .dependency_tracer import (
    extract_class_name,
    extract_constructor_dependencies,
    find_consumers,
    find_viewmodel_reference,
    iter_source_files,
)
from ..scanner.profile_manager import load_profile, save_profile
from ..scanner.project_scanner import detect_screen_type, is_screen_file


def update_profile_from_analysis(
    profile_path: str | Path,
    changed_files: list[str],
    repo_path: str | Path,
    source_root: str,
    exclude_dirs: list[str] | None = None,
) -> None:
    """Patch the profile's auto section based on changed files.

    Args:
        profile_path: Path to the repo root (profile at .apptest/app-profile.yml).
        changed_files: List of relative file paths that changed in the PR.
        repo_path: Absolute path to the repository root.
        source_root: Relative source root directory.
        exclude_dirs: Directories to exclude from search.
    """
    profile = load_profile(profile_path)
    if profile is None:
        return

    auto = profile.setdefault("auto", {})
    excl = exclude_dirs or ["build", ".gradle", "test", "androidTest"]
    repo = Path(repo_path)

    for file_path in changed_files:
        full = repo / file_path
        category = classify_file(file_path)

        if not full.exists():
            # File was deleted
            _remove_deleted_file(auto, file_path)
            continue

        if not category.startswith("logic_"):
            continue

        # Read the file content
        try:
            content = full.read_text(errors="replace")
        except OSError:
            continue

        # Check if this is a screen file
        if is_screen_file(content) or category in ("logic_screen", "logic_dialog", "logic_compose_screen"):
            _upsert_screen(auto, file_path, content, str(repo))

        # Update chains that reference this file
        class_name = extract_class_name(file_path, str(repo))
        _update_chains_for_file(auto, class_name, file_path, str(repo), source_root, excl)

    save_profile(profile_path, profile)


def _remove_deleted_file(auto: dict, file_path: str) -> None:
    """Remove a deleted file from screens and chains."""
    # Remove from screens
    auto["screens"] = [
        s for s in auto.get("screens", [])
        if s.get("file") != file_path
    ]

    # Remove from chains — remove the chain if screen was deleted
    auto["chains"] = [
        c for c in auto.get("chains", [])
        if c.get("screen_file") != file_path
    ]

    # Remove from chain members (for non-screen files)
    for chain in auto.get("chains", []):
        chain["members"] = [m for m in chain.get("members", []) if m != file_path]


def _upsert_screen(
    auto: dict,
    file_path: str,
    content: str,
    repo_path: str,
) -> None:
    """Add or update a screen entry in the auto section."""
    screens = auto.setdefault("screens", [])
    class_name = extract_class_name(file_path, repo_path)
    stype = detect_screen_type(content)
    if stype == "unknown":
        category = classify_file(file_path)
        type_map = {
            "logic_screen": "fragment" if "Fragment" in Path(file_path).stem else "activity",
            "logic_dialog": "dialog_fragment",
            "logic_compose_screen": "composable",
        }
        stype = type_map.get(category, "unknown")

    # Update existing or append
    for screen in screens:
        if screen.get("file") == file_path:
            screen["name"] = class_name
            screen["type"] = stype
            return

    screens.append({
        "name": class_name,
        "file": file_path,
        "type": stype,
    })


def _update_chains_for_file(
    auto: dict,
    class_name: str,
    file_path: str,
    repo_path: str,
    source_root: str,
    exclude_dirs: list[str],
) -> None:
    """Insert or update a file in relevant dependency chains."""
    chains = auto.get("chains", [])

    for chain in chains:
        members = chain.get("members", [])
        member_stems = {Path(m).stem for m in members if isinstance(m, str)}

        # If this class is already referenced in the chain, ensure the path is current
        if class_name in member_stems:
            for i, m in enumerate(members):
                if isinstance(m, str) and Path(m).stem == class_name:
                    members[i] = file_path
            continue

        # Check if this file should be inserted into the chain
        # (i.e., it's a new dependency of an existing chain member)
        screen_file = chain.get("screen_file", "")
        if not screen_file:
            continue

        # Check if any chain member depends on this class
        for member in members:
            if not isinstance(member, str):
                continue
            member_full = Path(repo_path) / member
            if not member_full.exists():
                continue
            try:
                member_content = member_full.read_text(errors="replace")
            except OSError:
                continue
            if class_name in member_content and member != file_path:
                # This chain member references our class — insert before it
                idx = members.index(member)
                members.insert(idx, file_path)
                break
