# Phase 1: Analyzer — Implementation Plan

## Goal
Build the `apptest analyze` command that reads a PR diff from the Wikipedia Android repo, identifies affected screens, and gathers relevant source context into a structured JSON output.

## Pre-step: Project Scaffolding

Create the Python package structure and tooling:

```
apptest/
├── __init__.py
├── cli.py                  # Click CLI entry point
├── config.py               # YAML config loader
├── analyzer/
│   ├── __init__.py
│   ├── diff_parser.py      # Parse git diffs
│   ├── screen_mapper.py    # Map changed files → affected screens
│   ├── context_builder.py  # Gather source context for each screen
│   ├── manifest_parser.py  # Parse AndroidManifest.xml
│   ├── layout_parser.py    # Parse layout XML files
│   └── strings_parser.py   # Parse strings.xml
├── tests/
│   ├── __init__.py
│   ├── test_diff_parser.py
│   ├── test_screen_mapper.py
│   ├── test_manifest_parser.py
│   ├── test_layout_parser.py
│   ├── test_strings_parser.py
│   └── fixtures/           # Sample diffs, XML files
└── pyproject.toml          # Package config (click, pyyaml, pytest)
```

**No nav_graph_parser.py** — Wikipedia Android has no XML nav graph. Navigation is Intent-based in code. We'll infer navigation connections from Intent/startActivity calls in context_builder instead.

## Step 1: `config.py` — YAML Config Loader

- Load `apptest.yml` from repo root
- Resolve `${ENV_VAR}` references in values
- Validate required fields exist
- Return a typed config dataclass

We'll create an `apptest.yml` tailored for Wikipedia Android:
```yaml
app:
  name: "Wikipedia"
  package: "org.wikipedia.dev"
  platform: android

source:
  root: "app/src/main/java/org/wikipedia"
  layouts_dir: "app/src/main/res/layout"
  strings_file: "app/src/main/res/values/strings.xml"
  manifest: "app/src/main/AndroidManifest.xml"

llm:
  provider: anthropic
  model: claude-sonnet-4-20250514
```

Note: `screens_dir` from the spec becomes `root` since Wikipedia organizes by feature package (search/, settings/, page/), not a flat screens directory.

## Step 2: `diff_parser.py` — Parse Git Diffs

Input: `git diff <ref>` output (run via subprocess)
Output: list of `ChangedFile` objects

```python
@dataclass
class ChangedFile:
    path: str              # e.g. "app/src/main/java/org/wikipedia/search/SearchFragment.kt"
    status: str            # added, modified, deleted, renamed
    diff_content: str      # the actual diff hunks
    language: str           # kt, java, xml
```

Logic:
- Run `git diff --name-status <ref>` to get file list + statuses
- Run `git diff <ref>` to get full diff content
- Parse diff output, split into per-file chunks
- Filter to relevant files (under app/src, not test files, not build files)

## Step 3: `manifest_parser.py` — Parse AndroidManifest.xml

Input: path to AndroidManifest.xml
Output: list of declared activities with metadata

```python
@dataclass
class ActivityInfo:
    name: str              # e.g. "org.wikipedia.search.SearchActivity"
    exported: bool
    intent_filters: list   # action/category/data from intent-filters
    is_launcher: bool
```

Logic:
- Parse XML with ElementTree
- Extract all `<activity>` elements
- Resolve fully-qualified names (handle `.SearchActivity` → `org.wikipedia.SearchActivity`)
- Identify launcher activity from intent-filter

## Step 4: `layout_parser.py` — Parse Layout XML Files

Input: path to a layout XML file
Output: structured representation of the layout

```python
@dataclass
class LayoutInfo:
    filename: str          # e.g. "fragment_search.xml"
    referenced_ids: list[str]      # @+id/search_input, etc.
    referenced_strings: list[str]  # @string/search_hint, etc.
    include_layouts: list[str]     # <include layout="@layout/..."/>
    view_types: list[str]          # EditText, RecyclerView, etc.
```

Logic:
- Parse XML, walk all elements
- Extract android:id, android:text, android:hint (string refs)
- Extract `<include>` references
- Collect view class names

## Step 5: `strings_parser.py` — Parse strings.xml

Input: path to strings.xml
Output: dict of string_name → string_value

Logic:
- Parse XML
- Extract all `<string name="...">value</string>` entries
- Handle basic XML entities
- Filter to only strings referenced by affected layouts/code (done in context_builder)

## Step 6: `screen_mapper.py` — Map Changed Files to Affected Screens

This is the core intelligence of the analyzer. Given a list of changed files, determine which screens are affected.

**Mapping rules** (adapted for Wikipedia's feature-package structure):

| Changed file pattern | Screen identification |
|---|---|
| `*Activity.kt/java` | Direct screen — the Activity itself |
| `*Fragment.kt/java` | Direct screen — find its host Activity |
| `*ViewModel.kt/java` | Trace to Fragment/Activity in same package |
| `*Repository.kt/java` | Trace to ViewModel in same package → then to screen |
| `res/layout/activity_*.xml` | Map to Activity by naming convention |
| `res/layout/fragment_*.xml` | Map to Fragment by naming convention |
| `res/layout/item_*.xml` | Find which Fragment/Activity inflates it (grep for the layout name) |
| `res/values/strings.xml` | Find which layouts reference changed string IDs, then map to screens |
| Other `.kt/.java` in a feature package | Check if the package contains an Activity/Fragment, associate |

**Fragment → Activity resolution:**
- Check for `SingleFragmentActivity` pattern (Wikipedia uses this heavily)
- Grep for class name usage in Activity files
- Check manifest for activity declarations in same package

## Step 7: `context_builder.py` — Gather Context for Each Affected Screen

For each affected screen identified by screen_mapper, gather:

1. **Diff content** — the actual changes for files in this screen's scope
2. **Full source** — complete content of the Activity/Fragment file
3. **Layout XML** — the associated layout file content
4. **Relevant strings** — string resources referenced in the layout or code
5. **Navigation connections** — inferred from:
   - `startActivity(Intent(...))` calls in the screen's code
   - Other screens that reference this screen via Intent
   - Fragment transactions referencing this Fragment

Output: the `analysis.json` structure from the spec.

## Step 8: `cli.py` — Wire It All Together

```bash
apptest analyze --diff "HEAD~1..HEAD" --repo /path/to/wikipedia --config apptest.yml
```

Pipeline:
1. Load config
2. Run diff_parser on the repo
3. Parse manifest (for Activity inventory)
4. Run screen_mapper on changed files
5. For each affected screen, run context_builder
6. Write `.apptest/analysis.json`

## Step 9: Tests

Unit tests for each module using real Wikipedia Android fixtures:

- **test_diff_parser.py** — parse sample git diff output
- **test_screen_mapper.py** — verify file→screen mapping for known Wikipedia patterns
- **test_manifest_parser.py** — parse Wikipedia's actual AndroidManifest.xml
- **test_layout_parser.py** — parse sample Wikipedia layout XMLs
- **test_strings_parser.py** — parse a subset of Wikipedia's strings.xml

## Step 10: Integration Test with Real Wikipedia PR

1. Clone `apps-android-wikipedia` repo
2. Pick a recent merged PR with meaningful UI changes
3. Run `apptest analyze` against it
4. Manually verify: did it correctly identify affected screens?
5. Manually verify: is the gathered context complete and relevant?

## Implementation Order

1. Scaffolding (pyproject.toml, package structure)
2. config.py + apptest.yml for Wikipedia
3. diff_parser.py + tests
4. manifest_parser.py + tests
5. layout_parser.py + tests
6. strings_parser.py + tests
7. screen_mapper.py + tests (depends on 3-6)
8. context_builder.py (depends on 3-7)
9. cli.py (wires everything together)
10. Clone Wikipedia repo + integration test on a real PR

## Key Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Wikipedia's feature-package layout doesn't match simple naming conventions | Use package-level grouping: all files in `org.wikipedia.search/` relate to the search screen |
| Fragment→Activity mapping is ambiguous | Use multiple signals: manifest, naming convention, SingleFragmentActivity pattern, grep |
| No XML nav graph means navigation context is sparse | Grep for Intent/startActivity patterns; accept that navigation context will be partial in Phase 1 |
| strings.xml is huge (~3000+ entries) | Only include strings referenced by affected layouts/code, not the full file |
| Mixed Compose + XML layouts | For Phase 1, focus on XML layouts. Compose screens won't have layout files but will still be identified by Activity/Fragment/ViewModel patterns |
