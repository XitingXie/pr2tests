"""Trace logic files to their UI screens via grep-based search.

Walks dependency chains from changed logic files (ViewModels, Repositories,
APIs, etc.) to their terminal screen files (Activities / Fragments).
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TraceResult:
    """Result of tracing a file to its screen consumer(s)."""
    chain: list[str]            # Ordered path: [source_file, ..., screen_file]
    screen_files: list[str]     # Terminal screen files found
    confidence: str             # "high", "medium", "low"


_CODE_EXTENSIONS = {".kt", ".java"}
_DEFAULT_EXCLUDE = {"build", ".gradle", ".git", "test", "androidTest", ".idea", "generated"}

# Patterns that indicate a class is a screen host
_SCREEN_PATTERN = re.compile(r"(Activity|Fragment)\.(kt|java)$")

# Pattern to extract a class/interface/object declaration
_CLASS_DECL = re.compile(
    r"^\s*(?:abstract\s+|open\s+|data\s+|sealed\s+|internal\s+|private\s+)*"
    r"(?:class|interface|object)\s+(\w+)",
    re.MULTILINE,
)


def extract_class_name(file_path: str, repo_path: str) -> str:
    """Extract the primary class/interface name from a Kotlin/Java file.

    Falls back to the filename stem if the file can't be read or parsed.
    """
    full = Path(repo_path) / file_path
    stem = Path(file_path).stem

    if not full.exists():
        return stem

    try:
        content = full.read_text(errors="replace")
    except OSError:
        return stem

    match = _CLASS_DECL.search(content)
    return match.group(1) if match else stem


_CONSTRUCTOR_DEP_PATTERN = re.compile(
    r"@Inject\s+constructor\s*\(([^)]*)\)",
    re.DOTALL,
)
_PROPERTY_INJECT_PATTERN = re.compile(
    r"@Inject\s+(?:lateinit\s+)?var\s+\w+\s*:\s*(\w+)",
)
_CONSTRUCTOR_PARAM_TYPE = re.compile(
    r"(?:val|var)?\s*\w+\s*:\s*(\w+)",
)
_DEP_SUFFIXES = ("Repository", "Repo", "UseCase", "Interactor", "Api", "Service",
                 "Client", "DataSource", "ViewModel", "Manager", "Provider", "Factory")

_VM_REF_PATTERNS = [
    re.compile(r"by\s+viewModels\s*<\s*(\w+)\s*>"),
    re.compile(r"by\s+activityViewModels\s*<\s*(\w+)\s*>"),
    re.compile(r"by\s+hiltNavGraphViewModels\s*<\s*(\w+)\s*>"),
    re.compile(r"ViewModelProvider\s*\([^)]*\)\s*(?:\.\s*get\s*\(\s*|\[\s*)(\w+)"),
    re.compile(r":\s*(\w+ViewModel)\s+by"),
    re.compile(r"=\s*(\w+ViewModel)\s*\("),
]


def extract_constructor_dependencies(content: str) -> list[str]:
    """Parse @Inject constructor(...) and property injection for dependencies.

    Returns class names of constructor parameters and @Inject properties
    whose types end with common dependency suffixes (Repository, UseCase, Api, etc.).
    """
    deps: list[str] = []
    seen: set[str] = set()

    # @Inject constructor(...)
    m = _CONSTRUCTOR_DEP_PATTERN.search(content)
    if m:
        params_block = m.group(1)
        for pm in _CONSTRUCTOR_PARAM_TYPE.finditer(params_block):
            type_name = pm.group(1)
            if any(type_name.endswith(s) for s in _DEP_SUFFIXES) and type_name not in seen:
                seen.add(type_name)
                deps.append(type_name)

    # @Inject lateinit var foo: SomeRepository
    for pm in _PROPERTY_INJECT_PATTERN.finditer(content):
        type_name = pm.group(1)
        if any(type_name.endswith(s) for s in _DEP_SUFFIXES) and type_name not in seen:
            seen.add(type_name)
            deps.append(type_name)

    # Fallback: plain constructor parameters (no @Inject)
    if not deps:
        plain_ctor = re.search(r"class\s+\w+\s*(?:<[^>]*>)?\s*\(([^)]*)\)", content, re.DOTALL)
        if plain_ctor:
            params_block = plain_ctor.group(1)
            for pm in _CONSTRUCTOR_PARAM_TYPE.finditer(params_block):
                type_name = pm.group(1)
                if any(type_name.endswith(s) for s in _DEP_SUFFIXES) and type_name not in seen:
                    seen.add(type_name)
                    deps.append(type_name)

    return deps


def find_viewmodel_reference(content: str) -> str | None:
    """Find a ViewModel class reference in fragment/activity source code.

    Matches patterns like:
      - by viewModels<FooViewModel>()
      - by activityViewModels<BarViewModel>()
      - : FooViewModel by ...
      - = FooViewModel(...)
      - ViewModelProvider(...).get(FooViewModel::class.java)
    """
    for pattern in _VM_REF_PATTERNS:
        m = pattern.search(content)
        if m:
            return m.group(1)
    return None


def _should_skip_dir(dirname: str, exclude_dirs: set[str]) -> bool:
    return dirname in exclude_dirs or dirname.startswith(".")


def iter_source_files(
    search_root: Path,
    exclude_dirs: set[str] | None = None,
) -> list[Path]:
    """Walk search_root and collect all .kt/.java source files."""
    excl = exclude_dirs if exclude_dirs is not None else _DEFAULT_EXCLUDE
    results: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(search_root):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d, excl)]
        for fname in filenames:
            if Path(fname).suffix in _CODE_EXTENSIONS:
                results.append(Path(dirpath) / fname)
    return results


# Keep private alias for backward compat within module
_iter_source_files = iter_source_files


def find_consumers(
    class_name: str,
    repo_path: str,
    source_root: str,
    exclude_dirs: list[str] | None = None,
    target_types: list[str] | None = None,
    exclude_file: str | None = None,
    max_results: int = 20,
) -> list[str]:
    """Find source files that reference *class_name*.

    Args:
        class_name: The class/interface name to search for.
        repo_path: Absolute path to the repository root.
        source_root: Relative source root (e.g. "app/src/main/java/org/wikipedia").
        exclude_dirs: Directory basenames to skip.
        target_types: If given, only return files whose names match one of these
                      suffixes (e.g. ["Fragment", "Activity", "ViewModel"]).
        exclude_file: A file path (relative) to exclude from results.
        max_results: Cap the number of returned paths.

    Returns:
        List of file paths relative to repo_path.
    """
    excl = set(exclude_dirs) if exclude_dirs else _DEFAULT_EXCLUDE
    search_root = Path(repo_path) / source_root
    if not search_root.exists():
        return []

    repo = Path(repo_path)
    hits: list[str] = []

    for fpath in _iter_source_files(search_root, excl):
        rel = str(fpath.relative_to(repo))
        if exclude_file and rel == exclude_file:
            continue

        try:
            content = fpath.read_text(errors="replace")
        except OSError:
            continue

        if class_name in content:
            if target_types:
                stem = fpath.stem
                if not any(stem.endswith(t) for t in target_types):
                    continue
            hits.append(rel)
            if len(hits) >= max_results:
                break

    return hits


def _is_screen_file(path: str) -> bool:
    return bool(_SCREEN_PATTERN.search(path))


def _find_package_neighbor_screens(
    file_path: str,
    repo_path: str,
) -> list[str]:
    """Find Fragment/Activity files in the same directory as file_path."""
    full = Path(repo_path) / file_path
    parent = full.parent
    if not parent.exists():
        return []
    repo = Path(repo_path)
    screens: list[str] = []
    for fpath in parent.iterdir():
        if fpath.suffix in _CODE_EXTENSIONS and _is_screen_file(fpath.name):
            rel = str(fpath.relative_to(repo))
            if rel != file_path:
                screens.append(rel)
    return screens


def trace_to_screen(
    file_path: str,
    file_type: str,
    repo_path: str,
    source_root: str,
    exclude_dirs: list[str] | None = None,
) -> TraceResult:
    """Trace a changed file to its screen consumer(s) via dependency hops.

    Args:
        file_path: Relative path of the changed file.
        file_type: Classification category (from change_classifier).
        repo_path: Absolute path to the repository root.
        source_root: Relative source root directory.
        exclude_dirs: Directories to exclude from search.

    Returns:
        TraceResult with the dependency chain, screen files, and confidence.
    """
    result = _trace_by_type(file_path, file_type, repo_path, source_root, exclude_dirs)

    # Package-neighbor fallback: if no screens found, look in same directory
    if not result.screen_files:
        neighbor_screens = _find_package_neighbor_screens(file_path, repo_path)
        if neighbor_screens:
            return TraceResult(
                chain=[file_path, neighbor_screens[0]],
                screen_files=neighbor_screens,
                confidence="low",
            )

    return result


def _trace_by_type(
    file_path: str,
    file_type: str,
    repo_path: str,
    source_root: str,
    exclude_dirs: list[str] | None = None,
) -> TraceResult:
    """Type-specific trace logic (before package-neighbor fallback)."""
    excl = exclude_dirs or list(_DEFAULT_EXCLUDE)

    # Direct screen file — no tracing needed
    if file_type in ("logic_screen", "logic_dialog"):
        return TraceResult(
            chain=[file_path],
            screen_files=[file_path],
            confidence="high",
        )

    # Compose screen — treat as a UI host, but trace to Fragment/Activity host
    if file_type == "logic_compose_screen":
        class_name = extract_class_name(file_path, repo_path)
        screens = find_consumers(
            class_name, repo_path, source_root, excl,
            target_types=["Fragment", "Activity"],
            exclude_file=file_path,
        )
        if screens:
            return TraceResult(
                chain=[file_path] + screens[:1],
                screen_files=screens,
                confidence="high",
            )
        # Compose screen with no Fragment/Activity host — it's a screen itself
        return TraceResult(
            chain=[file_path],
            screen_files=[file_path],
            confidence="medium",
        )

    # Adapter / Callback — 1 hop to Fragment/Activity
    if file_type in ("logic_adapter", "logic_callback"):
        class_name = extract_class_name(file_path, repo_path)
        screens = find_consumers(
            class_name, repo_path, source_root, excl,
            target_types=["Fragment", "Activity"],
            exclude_file=file_path,
        )
        conf = "high" if screens else "low"
        return TraceResult(
            chain=[file_path] + screens[:1],
            screen_files=screens,
            confidence=conf,
        )

    # ViewModel — 1 hop to Fragment/Activity
    if file_type == "logic_viewmodel":
        class_name = extract_class_name(file_path, repo_path)
        screens = find_consumers(
            class_name, repo_path, source_root, excl,
            target_types=["Fragment", "Activity"],
            exclude_file=file_path,
        )
        conf = "high" if screens else "low"
        return TraceResult(
            chain=[file_path] + screens[:1],
            screen_files=screens,
            confidence=conf,
        )

    # Repository / DataSource / UseCase — 2 hops via ViewModel
    if file_type in ("logic_repository", "logic_datasource", "logic_usecase"):
        class_name = extract_class_name(file_path, repo_path)
        # Hop 1: find ViewModel consumers
        viewmodels = find_consumers(
            class_name, repo_path, source_root, excl,
            target_types=["ViewModel"],
            exclude_file=file_path,
        )
        all_screens: list[str] = []
        chain = [file_path]
        for vm_path in viewmodels:
            vm_class = extract_class_name(vm_path, repo_path)
            # Hop 2: find screen consumers of the ViewModel
            screens = find_consumers(
                vm_class, repo_path, source_root, excl,
                target_types=["Fragment", "Activity"],
                exclude_file=vm_path,
            )
            if screens:
                chain = [file_path, vm_path, screens[0]]
                all_screens.extend(screens)
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_screens = []
        for s in all_screens:
            if s not in seen:
                seen.add(s)
                unique_screens.append(s)
        conf = "high" if unique_screens else "low"
        if unique_screens and len(viewmodels) > 0:
            conf = "high" if len(unique_screens) <= 3 else "medium"
        return TraceResult(
            chain=chain,
            screen_files=unique_screens,
            confidence=conf,
        )

    # API — 3 hops: API → Repo → ViewModel → Screen
    if file_type == "logic_api":
        class_name = extract_class_name(file_path, repo_path)
        # Hop 1: find Repository consumers
        repos = find_consumers(
            class_name, repo_path, source_root, excl,
            target_types=["Repository", "Repo"],
            exclude_file=file_path,
        )
        all_screens: list[str] = []
        chain = [file_path]
        for repo_file in repos:
            repo_class = extract_class_name(repo_file, repo_path)
            # Hop 2: find ViewModel consumers
            viewmodels = find_consumers(
                repo_class, repo_path, source_root, excl,
                target_types=["ViewModel"],
                exclude_file=repo_file,
            )
            for vm_path in viewmodels:
                vm_class = extract_class_name(vm_path, repo_path)
                # Hop 3: find Screen consumers
                screens = find_consumers(
                    vm_class, repo_path, source_root, excl,
                    target_types=["Fragment", "Activity"],
                    exclude_file=vm_path,
                )
                if screens:
                    chain = [file_path, repo_file, vm_path, screens[0]]
                    all_screens.extend(screens)
        seen = set()
        unique_screens = [s for s in all_screens if not (s in seen or seen.add(s))]
        conf = "medium" if unique_screens else "low"
        return TraceResult(
            chain=chain,
            screen_files=unique_screens,
            confidence=conf,
        )

    # Model — broad search, prefer closest UI consumers
    if file_type == "logic_model":
        class_name = extract_class_name(file_path, repo_path)
        # Try direct screen consumers first
        direct_screens = find_consumers(
            class_name, repo_path, source_root, excl,
            target_types=["Fragment", "Activity"],
            exclude_file=file_path,
        )
        if direct_screens:
            return TraceResult(
                chain=[file_path, direct_screens[0]],
                screen_files=direct_screens,
                confidence="medium",
            )
        # Try via ViewModel
        viewmodels = find_consumers(
            class_name, repo_path, source_root, excl,
            target_types=["ViewModel"],
            exclude_file=file_path,
        )
        all_screens: list[str] = []
        chain = [file_path]
        for vm_path in viewmodels:
            vm_class = extract_class_name(vm_path, repo_path)
            screens = find_consumers(
                vm_class, repo_path, source_root, excl,
                target_types=["Fragment", "Activity"],
                exclude_file=vm_path,
            )
            if screens:
                chain = [file_path, vm_path, screens[0]]
                all_screens.extend(screens)
        seen = set()
        unique_screens = [s for s in all_screens if not (s in seen or seen.add(s))]
        conf = "medium" if unique_screens else "low"
        return TraceResult(
            chain=chain,
            screen_files=unique_screens,
            confidence=conf,
        )

    # Default fallback (logic_other, etc.)
    class_name = extract_class_name(file_path, repo_path)
    direct_screens = find_consumers(
        class_name, repo_path, source_root, excl,
        target_types=["Fragment", "Activity"],
        exclude_file=file_path,
    )
    if direct_screens:
        return TraceResult(
            chain=[file_path, direct_screens[0]],
            screen_files=direct_screens,
            confidence="medium",
        )
    # Try any consumers then look for screens
    any_consumers = find_consumers(
        class_name, repo_path, source_root, excl,
        exclude_file=file_path,
        max_results=5,
    )
    all_screens: list[str] = []
    chain = [file_path]
    for consumer in any_consumers:
        if _is_screen_file(consumer):
            all_screens.append(consumer)
            chain = [file_path, consumer]
    if all_screens:
        return TraceResult(
            chain=chain,
            screen_files=all_screens,
            confidence="low",
        )

    return TraceResult(
        chain=[file_path],
        screen_files=[],
        confidence="low",
    )
