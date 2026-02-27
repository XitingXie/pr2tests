# Design: Code-Diff-Centric Change Classification & Dependency Tracing

## Problem

The Phase 1 analyzer was UI-resource-centric: it mapped files to screens based on naming patterns (Activity/Fragment/ViewModel) and gathered layout/string context. This worked well when the PR directly changed screen files, but most real PRs change business logic (repositories, API layers, models) that affect UI indirectly.

**Gaps in the old approach:**
- Files not matching `*Activity`/`*Fragment`/`*ViewModel`/`*Repository` patterns were associated by package proximity only (no dependency chain)
- Test files and build files were filtered out entirely — the LLM never saw them
- No classification of *what kind* of change was made (bug fix vs. new feature vs. refactor)
- Output was always organized by screen, even when changes didn't map cleanly to screens

## Solution

Replace the screen-centric pipeline with a change-type-centric pipeline:

```
Old:  diff → filter → screen_mapper → context per screen
New:  diff → classify → trace → context per change type
```

### Key Design Decisions

**1. Classify first, gather context second**

Every changed file gets a category (`ui_layout`, `logic_viewmodel`, `test`, `infra_build`, etc.) and logic files get a change nature (`bug_fix`, `new_feature`, etc.). This determines what context to gather:
- UI files → parse layout, resolve strings
- Logic files → trace to screen, gather screen source + layout
- Test files → just the diff + a note
- Infra files → just the diff

**2. Include all files, not just .kt/.java/.xml**

The old diff parser filtered to only relevant Android extensions. The new pipeline calls `parse_diff(filter_relevant=False)` and lets the classifier decide what to do with each file. Test files, build files, and config files all appear in the output — the LLM uses them as signals.

**3. Grep-based dependency tracing (no build system needed)**

The tracer walks dependency chains by:
1. Extracting the class name from the changed file (parse the `class`/`interface`/`object` declaration)
2. Scanning all source files for text references to that class name
3. Filtering results by target type (e.g., "only ViewModel files" or "only Fragment/Activity files")
4. Repeating for multi-hop chains

This is O(n) per hop where n = number of source files. For a typical Android project (500-1000 source files), this completes in milliseconds.

**4. Confidence scoring for traces**

Each trace result includes a confidence level:
- **high**: Direct screen file, or ViewModel/Adapter with clear screen consumer
- **medium**: Multi-hop traces (API → Repo → VM → Screen), or model files with indirect references
- **low**: No screen consumer found, or ambiguous results

This lets downstream consumers (the LLM, or human reviewers) weight the trace results.

## Module Design

### change_classifier.py

Two pure functions:

```python
classify_file(path: str) → str
# Uses path patterns: extension, directory markers, filename suffixes
# Returns: "ui_layout", "logic_viewmodel", "test", "infra_build", etc.

classify_change_nature(diff_content: str) → str
# Uses keyword heuristics on diff lines
# Returns: "new_feature", "bug_fix", "refactor", etc.
```

Design choice: keyword-based heuristics over LLM classification. The classifier runs before the LLM sees anything, so it must be fast and deterministic. The heuristics are imperfect but good enough to route files to the right context builder.

### dependency_tracer.py

Three functions:

```python
extract_class_name(file_path, repo_path) → str
# Reads the file, regex-matches class/interface/object declaration
# Fallback: filename stem

find_consumers(class_name, repo_path, source_root, target_types?) → list[str]
# Scans all .kt/.java files for text references to class_name
# Optionally filters by filename suffix (e.g., only *ViewModel files)

trace_to_screen(file_path, file_type, repo_path, source_root) → TraceResult
# Routes to hop-count-specific logic based on file_type
# Returns: chain, screen_files, confidence
```

Design choice: text-based search rather than AST parsing. This avoids needing a Kotlin/Java parser, works across both languages, and handles most real-world patterns (constructor injection, property references, type annotations). False positives are possible (e.g., a comment mentioning a class name) but rare in practice.

### context_builder.py

Four per-type builders routed by category prefix:

```python
_build_ui_context()    # Parses layout, resolves strings, finds affected screen
_build_logic_context() # Reads full source, traces deps, gathers screen context
_build_test_context()  # Just the diff + informative note
_build_infra_context() # Just the diff + type
```

The main `build_context()` function classifies all files, then dispatches each to the appropriate builder.

## Migration from screen_mapper.py

The old `screen_mapper.py` is deprecated but retained:
- Its tests still pass (the module is unchanged)
- The `_extract_package()` utility function could be extracted to a shared module in the future
- The CLI no longer imports it

What the new modules replace:

| Old (screen_mapper) | New |
|---------------------|-----|
| Activity/Fragment pattern matching | `classify_file()` returns `logic_screen` |
| ViewModel/Repo → screen by package | `trace_to_screen()` with hop-based tracing |
| Layout → screen by naming convention | `_find_screen_for_layout()` in context_builder |
| Manifest fallback | Activity inventory in `AnalysisResult.all_activities` |

## Testing Strategy

- **change_classifier**: 33 pure unit tests, no I/O
- **dependency_tracer**: 12 tests using a mock Android project (`fixtures/mock_repo/`) with 8 Kotlin files forming a complete dependency chain
- **Existing tests**: All 30 existing tests continue to pass unchanged

## Future Improvements

1. **Indexed file search**: Build a one-time `{file → content}` index for `find_consumers` to avoid repeated file reads when tracing multiple changed files
2. **Compose support**: Add `logic_composable` category for `@Composable` functions
3. **Cross-module tracing**: Support multi-module Android projects where API interfaces live in a separate Gradle module
4. **LLM-enhanced classification**: Use the LLM as a second pass to refine change_nature when keyword heuristics are ambiguous
