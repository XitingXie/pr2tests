"""Single-pass codebase scanner for building app profiles.

Walks the entire source tree once, detecting:
  - Project structure (modules, source roots, resource roots)
  - Screens (Activities, Fragments, Composables)
  - Architecture signals (MVVM, MVI, MVP, etc.)
  - DI signals (Hilt, Dagger, Koin)
  - Navigation patterns (NavGraph XML, Compose NavHost)
  - Dependency chains from each screen to its transitive dependencies
"""

import re
from pathlib import Path

from ..analyzer.change_classifier import classify_file
from ..analyzer.dependency_tracer import (
    extract_class_name,
    extract_constructor_dependencies,
    find_consumers,
    find_viewmodel_reference,
    iter_source_files,
)


# ---------------------------------------------------------------------------
# Content-based screen detection
# ---------------------------------------------------------------------------

_SCREEN_INDICATORS = [
    (re.compile(r":\s*Fragment\s*\("), "fragment"),
    (re.compile(r":\s*AppCompatActivity\s*\("), "activity"),
    (re.compile(r":\s*Activity\s*\("), "activity"),
    (re.compile(r":\s*ComponentActivity\s*\("), "activity"),
    (re.compile(r":\s*FragmentActivity\s*\("), "activity"),
    (re.compile(r":\s*DialogFragment\s*\("), "dialog_fragment"),
    (re.compile(r":\s*BottomSheetDialogFragment\s*\("), "bottom_sheet"),
    (re.compile(r"@Composable\s+fun\s+\w+Screen"), "composable"),
]

_ARCH_SIGNALS = {
    "ViewModel": "mvvm",
    "MutableStateFlow": "mvi",
    "MutableLiveData": "mvvm",
    "Presenter": "mvp",
    "Redux": "redux",
}

_DI_SIGNALS = {
    "@HiltAndroidApp": "hilt",
    "@AndroidEntryPoint": "hilt",
    "@HiltViewModel": "hilt",
    "@Inject": "dagger",
    "@Module": "dagger",
    "@Component": "dagger",
    "KoinComponent": "koin",
    "inject()": "koin",
}


def is_screen_file(content: str) -> bool:
    """Check if file content indicates a screen (Activity/Fragment/Composable)."""
    for pattern, _ in _SCREEN_INDICATORS:
        if pattern.search(content):
            return True
    return False


def detect_screen_type(content: str) -> str:
    """Detect the screen type from file content.

    Returns: fragment, activity, composable, dialog_fragment, bottom_sheet, or unknown.
    """
    for pattern, stype in _SCREEN_INDICATORS:
        if pattern.search(content):
            return stype
    # Fallback: check filename-based classification patterns
    return "unknown"


# ---------------------------------------------------------------------------
# Project structure detection
# ---------------------------------------------------------------------------

def _detect_project_structure(repo_path: str | Path) -> dict:
    """Parse settings.gradle(.kts) and discover modules, source roots, resource roots."""
    repo = Path(repo_path)
    structure: dict = {
        "modules": [],
        "source_roots": [],
        "resource_roots": [],
    }

    # Find settings.gradle or settings.gradle.kts
    for name in ("settings.gradle.kts", "settings.gradle"):
        settings = repo / name
        if settings.exists():
            content = settings.read_text(errors="replace")
            # Extract include(':app'), include(":lib:core"), etc.
            for m in re.finditer(r"""include\s*\(\s*['"]([^'"]+)['"]\s*\)""", content):
                module = m.group(1).lstrip(":").replace(":", "/")
                structure["modules"].append(module)
            # Also match include ':app' (Groovy single-arg)
            for m in re.finditer(r"""include\s+['"]([^'"]+)['"]""", content):
                module = m.group(1).lstrip(":").replace(":", "/")
                if module not in structure["modules"]:
                    structure["modules"].append(module)
            break

    if not structure["modules"]:
        # Fallback: look for app/build.gradle
        if (repo / "app" / "build.gradle").exists() or (repo / "app" / "build.gradle.kts").exists():
            structure["modules"] = ["app"]

    # Discover source and resource roots for each module
    for module in structure["modules"]:
        for variant in ("main",):
            src_root = repo / module / "src" / variant / "java"
            if src_root.exists():
                structure["source_roots"].append(str(src_root.relative_to(repo)))
            src_root_kt = repo / module / "src" / variant / "kotlin"
            if src_root_kt.exists():
                structure["source_roots"].append(str(src_root_kt.relative_to(repo)))
            res_root = repo / module / "src" / variant / "res"
            if res_root.exists():
                structure["resource_roots"].append(str(res_root.relative_to(repo)))

    return structure


# ---------------------------------------------------------------------------
# Single-pass scan
# ---------------------------------------------------------------------------

def _single_pass_scan(
    source_roots: list[str],
    repo_path: str | Path,
) -> tuple[list[dict], dict[str, int], dict[str, int]]:
    """Walk all source files once; collect screens, architecture signals, DI signals.

    Returns:
        (screens, arch_counts, di_counts)
    """
    repo = Path(repo_path)
    screens: list[dict] = []
    arch_counts: dict[str, int] = {}
    di_counts: dict[str, int] = {}
    seen_files: set[str] = set()

    for src_root in source_roots:
        search_root = repo / src_root
        if not search_root.exists():
            continue

        for fpath in iter_source_files(search_root):
            rel = str(fpath.relative_to(repo))
            if rel in seen_files:
                continue
            seen_files.add(rel)

            try:
                content = fpath.read_text(errors="replace")
            except OSError:
                continue

            # Classify the file
            category = classify_file(rel)

            # Collect architecture signals
            for keyword, arch in _ARCH_SIGNALS.items():
                if keyword in content:
                    arch_counts[arch] = arch_counts.get(arch, 0) + 1

            # Collect DI signals
            for keyword, di in _DI_SIGNALS.items():
                if keyword in content:
                    di_counts[di] = di_counts.get(di, 0) + 1

            # Detect screens
            stype = detect_screen_type(content)
            if stype != "unknown":
                class_name = extract_class_name(rel, str(repo))
                screens.append({
                    "name": class_name,
                    "file": rel,
                    "type": stype,
                    "category": category,
                })
            elif category in ("logic_screen", "logic_dialog", "logic_compose_screen"):
                # Fallback: file classified as screen by name but content didn't match
                class_name = extract_class_name(rel, str(repo))
                type_map = {
                    "logic_screen": "fragment" if "Fragment" in fpath.stem else "activity",
                    "logic_dialog": "dialog_fragment",
                    "logic_compose_screen": "composable",
                }
                screens.append({
                    "name": class_name,
                    "file": rel,
                    "type": type_map.get(category, "unknown"),
                    "category": category,
                })

    return screens, arch_counts, di_counts


# ---------------------------------------------------------------------------
# Navigation detection
# ---------------------------------------------------------------------------

def _detect_navigation(
    repo_path: str | Path,
    resource_roots: list[str],
) -> dict:
    """Check for navigation graph XML files and Compose NavHost references."""
    repo = Path(repo_path)
    nav_info: dict = {
        "type": "unknown",
        "nav_graphs": [],
        "has_compose_nav": False,
    }

    # Check XML navigation graphs
    for res_root in resource_roots:
        nav_dir = repo / res_root / "navigation"
        if nav_dir.exists():
            for f in nav_dir.glob("*.xml"):
                nav_info["nav_graphs"].append(str(f.relative_to(repo)))
            if nav_info["nav_graphs"]:
                nav_info["type"] = "xml_nav_graph"

    # Check for Compose Navigation (NavHost) in source files
    for res_root in resource_roots:
        # Source roots are parallel to resource roots
        src_dir = Path(str(repo / res_root).replace("/res", "/java"))
        if not src_dir.exists():
            src_dir = Path(str(repo / res_root).replace("/res", "/kotlin"))
        if src_dir.exists():
            for fpath in iter_source_files(src_dir):
                try:
                    content = fpath.read_text(errors="replace")
                except OSError:
                    continue
                if "NavHost" in content or "rememberNavController" in content:
                    nav_info["has_compose_nav"] = True
                    if nav_info["type"] == "unknown":
                        nav_info["type"] = "compose_navigation"
                    elif nav_info["type"] == "xml_nav_graph":
                        nav_info["type"] = "hybrid"
                    break

    return nav_info


# ---------------------------------------------------------------------------
# Chain tracing
# ---------------------------------------------------------------------------

def _trace_all_chains(
    screens: list[dict],
    repo_path: str | Path,
    source_roots: list[str],
    exclude_dirs: set[str] | None = None,
) -> list[dict]:
    """Build dependency chains per screen.

    For each screen, traces backward through ViewModel → Repository/UseCase → API
    using constructor dependency extraction and consumer search.
    """
    repo = str(repo_path)
    excl = list(exclude_dirs) if exclude_dirs else ["build", ".gradle", "test", "androidTest"]
    chains: list[dict] = []

    # Use the first source root for consumer search (broadest scope)
    # Fall back to module root if we have multiple source roots
    primary_source = source_roots[0] if source_roots else ""

    for screen in screens:
        screen_file = screen["file"]
        screen_name = screen["name"]
        full_path = Path(repo) / screen_file

        if not full_path.exists():
            continue

        try:
            content = full_path.read_text(errors="replace")
        except OSError:
            continue

        members: list[str] = [screen_file]
        confidence = "high"

        # Step 1: Find ViewModel reference in the screen
        vm_ref = find_viewmodel_reference(content)
        vm_file: str | None = None

        if vm_ref:
            # Find the ViewModel file
            vm_consumers = find_consumers(
                vm_ref, repo, primary_source, excl,
                max_results=5,
            )
            # The ViewModel file is the one whose class name matches
            for candidate in vm_consumers:
                if Path(candidate).stem == vm_ref:
                    vm_file = candidate
                    break
            if not vm_file:
                # Try finding it directly
                vm_hits = find_consumers(
                    vm_ref, repo, primary_source, excl,
                    exclude_file=screen_file,
                    max_results=5,
                )
                for h in vm_hits:
                    if vm_ref in Path(h).stem:
                        vm_file = h
                        break

        if not vm_file:
            # Fallback: search for ViewModel that references this screen's class
            vm_consumers = find_consumers(
                screen_name, repo, primary_source, excl,
                target_types=["ViewModel"],
                exclude_file=screen_file,
                max_results=3,
            )
            if not vm_consumers:
                # Try finding any ViewModel in same package
                package_dir = full_path.parent
                for f in package_dir.iterdir():
                    if f.suffix in (".kt", ".java") and "ViewModel" in f.stem:
                        vm_file = str(f.relative_to(Path(repo)))
                        break
            elif vm_consumers:
                vm_file = vm_consumers[0]

        if vm_file:
            members.append(vm_file)

            # Step 2: Extract ViewModel dependencies
            vm_full = Path(repo) / vm_file
            if vm_full.exists():
                try:
                    vm_content = vm_full.read_text(errors="replace")
                    deps = extract_constructor_dependencies(vm_content)
                    for dep_class in deps:
                        # Find the file for this dependency
                        dep_hits = find_consumers(
                            dep_class, repo, primary_source, excl,
                            max_results=5,
                        )
                        for dh in dep_hits:
                            if Path(dh).stem == dep_class:
                                members.append(dh)
                                break
                except OSError:
                    pass

        # Reverse: chain should go from deepest dependency to screen
        members_reversed = list(reversed(members))

        chains.append({
            "screen_name": screen_name,
            "screen_file": screen_file,
            "confidence": confidence,
            "members": members_reversed,
        })

    return chains


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def scan_project(
    repo_path: str | Path,
    config: dict | None = None,
) -> dict:
    """Full project scan — returns a profile 'auto' section.

    Args:
        repo_path: Absolute path to the repository root.
        config: Optional config dict with 'source_root', 'exclude_dirs'.
                If not provided, auto-detects from project structure.
    """
    repo = Path(repo_path)

    # Step 1: Detect project structure
    structure = _detect_project_structure(repo)

    # Use config overrides if provided
    source_roots = structure["source_roots"]
    resource_roots = structure["resource_roots"]
    exclude_dirs = {"build", ".gradle", ".git", "test", "androidTest", ".idea", "generated"}

    if config:
        if "source_root" in config:
            source_roots = [config["source_root"]]
        if "exclude_dirs" in config:
            exclude_dirs = set(config["exclude_dirs"])

    # Step 2: Single-pass scan
    screens, arch_counts, di_counts = _single_pass_scan(source_roots, repo)

    # Determine dominant architecture
    architecture = "unknown"
    if arch_counts:
        architecture = max(arch_counts, key=arch_counts.get)

    # Determine DI framework
    di_framework = "none"
    if di_counts:
        di_framework = max(di_counts, key=di_counts.get)

    # Step 3: Detect navigation
    nav_info = _detect_navigation(repo, resource_roots)

    # Step 4: Trace chains
    chains = _trace_all_chains(screens, repo, source_roots, exclude_dirs)

    return {
        "project": {
            "modules": structure["modules"],
            "source_roots": source_roots,
            "resource_roots": resource_roots,
            "architecture": architecture,
            "di_framework": di_framework,
            "navigation": nav_info,
        },
        "screens": screens,
        "chains": chains,
    }
