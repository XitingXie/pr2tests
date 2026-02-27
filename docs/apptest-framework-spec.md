# AppTest: AI-Powered Test Generation & Execution Framework

## Project Overview

AppTest is a CLI tool that integrates into CI pipelines to automatically generate and execute test cases for Android apps. It reads PR diffs, understands what changed using LLM reasoning, generates natural language test cases, and executes them on real devices or emulators.

The tool is designed as a CI plugin that runs in the customer's infrastructure. Source code never leaves their environment. Only relevant code context is sent to the LLM API for test generation.

## Core Architecture

```
apptest CLI (runs in customer's CI)
  │
  ├── analyze   → reads PR diff, extracts relevant source context
  ├── generate  → sends context to LLM, receives test cases
  ├── execute   → runs tests on device via ADB
  └── report    → posts results to PR comment, outputs JSON
```

### What Runs Where

**Customer's CI environment:**
- apptest CLI (thin client)
- Source code (never leaves their infra)
- Git diff computation (local)
- Test execution on their devices/emulators
- Screenshots and logs

**LLM API (Anthropic):**
- Receives: relevant code snippets, PR context (NOT the full repo)
- Returns: generated test cases, action decisions during execution

## Technology Stack

- **Language:** Python 3.11+
- **CLI framework:** Click
- **Device interaction:** ADB (via subprocess or pure-adb-python)
- **UI inspection:** UIAutomator (hierarchy dump via ADB)
- **OCR:** PaddleOCR (for elements missing from hierarchy)
- **LLM:** Anthropic Claude API (claude-sonnet-4-20250514)
- **Distribution:** pip package (`pip install apptest`)
- **Config format:** YAML

## Project Structure

```
apptest/
├── cli.py                  # Click CLI entry point
├── config.py               # YAML config loader
├── analyzer/
│   ├── diff_parser.py      # Parse git diffs, extract changed files
│   ├── screen_mapper.py    # Map changed files to affected screens
│   ├── context_builder.py  # Gather relevant source context
│   ├── manifest_parser.py  # Parse AndroidManifest.xml
│   ├── layout_parser.py    # Parse layout XML files
│   ├── strings_parser.py   # Parse strings.xml
│   └── nav_graph_parser.py # Parse Jetpack Navigation graphs
├── generator/
│   ├── test_generator.py   # LLM-based test case generation
│   └── prompts.py          # Prompt templates
├── executor/
│   ├── device.py           # ADB device connection and management
│   ├── primitives.py       # Low-level ADB actions (tap, swipe, type, etc.)
│   ├── ui_inspector.py     # UIAutomator hierarchy dump and parsing
│   ├── ocr.py              # PaddleOCR integration for missing elements
│   ├── element_finder.py   # Merge hierarchy + OCR, find elements
│   ├── planner.py          # LLM-based goal decomposition
│   ├── step_executor.py    # Execute individual goals on device
│   └── screenshot.py       # Screenshot capture and management
├── knowledge/
│   ├── knowledge_base.py   # Per-app knowledge storage and retrieval
│   └── screen_identifier.py # Deterministic screen state identification
├── reporter/
│   ├── json_reporter.py    # Output results as JSON
│   ├── github_reporter.py  # Post results as GitHub PR comment
│   └── gitlab_reporter.py  # Post results as GitLab MR note
└── tests/
    ├── test_analyzer.py
    ├── test_generator.py
    ├── test_executor.py
    └── fixtures/           # Sample diffs, hierarchies, test data
```

## Configuration

The user places an `apptest.yml` in their repo root:

```yaml
app:
  name: "Wikipedia"
  package: "org.wikipedia"
  platform: android

source:
  screens_dir: "app/src/main/java/org/wikipedia/ui"
  layouts_dir: "app/src/main/res/layout"
  strings_file: "app/src/main/res/values/strings.xml"
  nav_graph: "app/src/main/res/navigation/nav_graph.xml"
  manifest: "app/src/main/AndroidManifest.xml"

llm:
  provider: anthropic
  model: claude-sonnet-4-20250514
  # API key read from ANTHROPIC_API_KEY env var

test_data:
  # Credentials and data for test execution
  # Values with ${} are read from environment variables
  username: "${TEST_USERNAME}"
  password: "${TEST_PASSWORD}"

execution:
  device: "emulator"
  timeout_per_test: 120  # seconds
  screenshot_on_failure: true
  reset_app_between_tests: true

report:
  format: json
  output: ".apptest/results.json"
  # Optional: post to PR
  github_token: "${GITHUB_TOKEN}"
```

## CLI Commands

### `apptest analyze`

Reads a PR diff and extracts relevant context for test generation.

```bash
apptest analyze --diff "HEAD~1..HEAD" --repo . --config apptest.yml
```

**What it does:**

1. Run `git diff` to get changed files
2. Parse the diff to identify which files changed and how
3. Map changed files to affected screens:
   - Files ending in `Activity.kt/java` or `Fragment.kt/java` → direct screen mapping
   - Files ending in `ViewModel.kt/java` → trace to their Fragment/Activity consumer
   - Files ending in `Repository.kt/java` → trace to ViewModel → Fragment/Activity
   - Layout XML files → direct screen mapping via filename convention
   - String resource changes → find which layouts/screens reference those string IDs
4. For each affected screen, gather context:
   - The diff for the changed file
   - Full content of the Activity/Fragment
   - Associated layout XML
   - Relevant string resources
   - Navigation graph connections (what screens link to/from this one)
5. Parse AndroidManifest.xml for the full Activity inventory
6. Output analysis to `.apptest/analysis.json`

**Output format (`.apptest/analysis.json`):**

```json
{
  "pr_info": {
    "diff_ref": "HEAD~1..HEAD",
    "changed_files": ["app/src/.../SearchFragment.kt", "app/src/.../res/layout/fragment_search.xml"],
    "timestamp": "2025-02-27T10:00:00Z"
  },
  "affected_screens": [
    {
      "name": "SearchFragment",
      "file": "app/src/main/java/org/wikipedia/search/SearchFragment.kt",
      "layout": "fragment_search.xml",
      "diff": "... the actual diff content ...",
      "full_source": "... full file content ...",
      "layout_content": "... layout XML ...",
      "relevant_strings": {
        "search_hint": "Search Wikipedia",
        "search_no_results": "No results found"
      },
      "nav_connections": {
        "incoming": ["MainFragment"],
        "outgoing": ["ArticleFragment"]
      }
    }
  ],
  "all_activities": [
    "org.wikipedia.main.MainActivity",
    "org.wikipedia.page.PageActivity",
    "org.wikipedia.settings.SettingsActivity"
  ]
}
```

### `apptest generate`

Takes the analysis output and generates natural language test cases using the LLM.

```bash
apptest generate --analysis .apptest/analysis.json --output .apptest/tests.json
```

**What it does:**

1. Load the analysis JSON
2. Load any existing knowledge base for this app
3. Build a prompt with:
   - The PR diff and affected screen context
   - String resources (especially error messages — they reveal error states)
   - Navigation connections (what screens are adjacent)
   - Knowledge base entries for affected screens
4. Call the LLM to generate test cases
5. Parse and validate the response
6. Output test cases to `.apptest/tests.json`

**Prompt template (in `prompts.py`):**

```python
TEST_GENERATION_PROMPT = """
You are a QA engineer generating test cases for a mobile app update.

## What Changed

{diff_summary}

## Affected Screens

{affected_screens_detail}

## String Resources (including error messages)

{relevant_strings}

## Navigation Context

{nav_connections}

## What We Know From Previous Testing

{knowledge_base_summary}

## Instructions

Generate test cases that cover:
1. Happy path for any new or modified features
2. Error cases — use the string resources to identify what error states exist
3. Edge cases (empty input, boundary values, rapid interactions)
4. Regression — verify existing functionality on modified screens still works

For each test case, provide:
- A natural language description that reads like instructions to a human tester
- What aspect of the change it covers
- Priority (high/medium/low)
- Any test data requirements

Write test descriptions as concrete, actionable steps. Not "test the search feature" 
but "open the app, tap the search bar, type 'Albert Einstein', verify search results 
appear showing a Wikipedia article about Albert Einstein."

Respond as JSON array:
[
  {{
    "id": "test_001",
    "description": "step by step natural language test description",
    "covers": "what aspect of the change this tests",
    "priority": "high|medium|low",
    "test_data": {{"key": "value"}} 
  }}
]
"""
```

**Output format (`.apptest/tests.json`):**

```json
{
  "generated_at": "2025-02-27T10:05:00Z",
  "pr_ref": "HEAD~1..HEAD",
  "tests": [
    {
      "id": "test_001",
      "description": "Open the app, tap the search bar, type 'Albert Einstein', verify search results appear with an article titled 'Albert Einstein'",
      "covers": "basic search functionality after search UI changes",
      "priority": "high",
      "test_data": {}
    }
  ]
}
```

### `apptest execute`

Runs generated tests on a device or emulator.

```bash
apptest execute --tests .apptest/tests.json --device emulator-5554 --app org.wikipedia
```

**What it does for each test:**

1. Reset app state (`adb shell pm clear <package>`)
2. Launch the app (`adb shell am start -n <package>/<main_activity>`)
3. Wait for app to be ready
4. Call the LLM planner to decompose the test description into goals
5. For each goal, run the execution loop:
   a. Dump UI hierarchy via UIAutomator
   b. Run OCR on screenshot to find elements missing from hierarchy
   c. Merge both element sources
   d. Check if goal is already achieved (success criteria met)
   e. Check knowledge base for known action
   f. If unknown, call LLM with current screen elements + goal to decide next action
   g. Execute the action via ADB
   h. Record what happened for the knowledge base
6. Capture screenshot on pass or fail
7. Record result

**The execution loop in detail:**

```python
def execute_goal(device, goal, test_data, knowledge_base, max_steps=15):
    """
    Execute a single goal on the device.
    
    Args:
        device: ADB device connection
        goal: dict with 'description' and 'success_criteria'
        test_data: dict of test parameters
        knowledge_base: AppKnowledge instance
        max_steps: safety limit to prevent infinite loops
    
    Returns:
        GoalResult with success, actions taken, screenshots
    """
    actions_taken = []
    
    for step in range(max_steps):
        # 1. Observe current state
        hierarchy = dump_ui_hierarchy(device)
        screenshot_path = capture_screenshot(device)
        ocr_results = run_ocr(screenshot_path)
        elements = merge_hierarchy_and_ocr(hierarchy, ocr_results)
        
        # 2. Check if goal is achieved
        if check_success_criteria(goal['success_criteria'], elements, hierarchy):
            knowledge_base.record_success(goal, actions_taken)
            return GoalResult(success=True, actions=actions_taken)
        
        # 3. Check knowledge base for known action
        known_action = knowledge_base.lookup(
            goal=goal['description'],
            current_screen=identify_screen(hierarchy),
            elements=elements
        )
        
        if known_action:
            execute_action(device, known_action)
            actions_taken.append(known_action)
            time.sleep(0.5)
            continue
        
        # 4. Ask LLM what to do
        action = llm_decide_action(
            goal=goal,
            elements=elements,
            hierarchy_activity=hierarchy.activity_name,
            test_data=test_data
        )
        
        execute_action(device, action)
        actions_taken.append(action)
        
        # 5. Record for knowledge base
        knowledge_base.record_action(
            goal=goal['description'],
            screen=identify_screen(hierarchy),
            action=action
        )
        
        time.sleep(0.5)
    
    return GoalResult(success=False, reason="max_steps_exceeded", actions=actions_taken)
```

### `apptest report`

Posts results to the PR and outputs structured results.

```bash
apptest report --results .apptest/results.json --github-pr 1234 --repo owner/repo
```

**GitHub PR comment format:**

```markdown
## 🧪 AppTest Results

**6 tests generated, 5 passed, 1 failed**

| Status | Test | Covers |
|--------|------|--------|
| ✅ | Search for 'Albert Einstein' and verify results | Search happy path |
| ✅ | Search with empty query and verify handling | Search edge case |
| ✅ | Search for nonsense string, verify no results message | Search error state |
| ❌ | Search, tap result, verify article loads | Search to article navigation |
| ✅ | Open settings from home screen | Regression - navigation |
| ✅ | Toggle dark mode in settings | Regression - settings |

### ❌ Failed: Search, tap result, verify article loads
**Failed at step:** "Tap the first search result"
**Reason:** Could not find tappable search result element after 15 attempts
**Screenshot:** [failure_screenshot.png]
```

## Device Interaction Layer

### Primitives (`primitives.py`)

All device interactions go through these functions. They are thin wrappers around ADB commands.

```python
"""
Low-level ADB device interaction primitives.
All coordinates are in screen pixels.
"""

def tap(device, x: int, y: int):
    """Tap at absolute screen coordinates."""
    device.shell(f"input tap {x} {y}")

def long_press(device, x: int, y: int, duration_ms: int = 1000):
    """Long press at coordinates."""
    device.shell(f"input swipe {x} {y} {x} {y} {duration_ms}")

def swipe(device, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300):
    """Swipe from (x1,y1) to (x2,y2)."""
    device.shell(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")

def swipe_up(device):
    """Scroll down by swiping up from center."""
    w, h = get_screen_size(device)
    swipe(device, w // 2, h * 3 // 4, w // 2, h // 4)

def swipe_down(device):
    """Scroll up by swiping down from center."""
    w, h = get_screen_size(device)
    swipe(device, w // 2, h // 4, w // 2, h * 3 // 4)

def type_text(device, text: str):
    """Type text into the currently focused field."""
    # Escape special characters for ADB
    escaped = text.replace(" ", "%s").replace("'", "\\'")
    device.shell(f"input text '{escaped}'")

def press_back(device):
    """Press the back button."""
    device.shell("input keyevent BACK")

def press_home(device):
    """Press the home button."""
    device.shell("input keyevent HOME")

def press_enter(device):
    """Press the enter/return key."""
    device.shell("input keyevent ENTER")

def get_screen_size(device) -> tuple[int, int]:
    """Get screen dimensions in pixels."""
    output = device.shell("wm size")
    # Output: "Physical size: 1080x2400"
    match = re.search(r"(\d+)x(\d+)", output)
    return int(match.group(1)), int(match.group(2))

def screenshot(device, local_path: str) -> str:
    """Capture screenshot and pull to local path."""
    device.shell("screencap -p /sdcard/apptest_screen.png")
    device.pull("/sdcard/apptest_screen.png", local_path)
    return local_path

def launch_app(device, package: str, activity: str = None):
    """Launch an app. If activity not specified, use monkey to launch main."""
    if activity:
        device.shell(f"am start -n {package}/{activity}")
    else:
        device.shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1")

def clear_app_data(device, package: str):
    """Clear all app data (resets to fresh install state)."""
    device.shell(f"pm clear {package}")

def force_stop(device, package: str):
    """Force stop the app."""
    device.shell(f"am force-stop {package}")

def is_keyboard_shown(device) -> bool:
    """Check if the soft keyboard is currently visible."""
    output = device.shell("dumpsys input_method | grep mInputShown")
    return "mInputShown=true" in output

def hide_keyboard(device):
    """Dismiss the soft keyboard if shown."""
    if is_keyboard_shown(device):
        device.shell("input keyevent BACK")

def get_current_activity(device) -> str:
    """Get the currently focused activity name."""
    output = device.shell("dumpsys activity activities | grep mResumedActivity")
    match = re.search(r"(\S+/\S+)", output)
    return match.group(1) if match else ""
```

### UI Inspector (`ui_inspector.py`)

Dumps and parses the UIAutomator hierarchy.

```python
"""
UIAutomator hierarchy dump and parsing.
Extracts interactive elements with their properties.
"""

import xml.etree.ElementTree as ET

class UIElement:
    """Represents a single UI element from the hierarchy."""
    def __init__(self, node):
        self.text = node.get("text", "")
        self.resource_id = node.get("resource-id", "")
        self.class_name = node.get("class", "")
        self.content_desc = node.get("content-desc", "")
        self.clickable = node.get("clickable") == "true"
        self.checkable = node.get("checkable") == "true"
        self.checked = node.get("checked") == "true"
        self.enabled = node.get("enabled") == "true"
        self.scrollable = node.get("scrollable") == "true"
        self.focusable = node.get("focusable") == "true"
        self.selected = node.get("selected") == "true"
        self.bounds = self._parse_bounds(node.get("bounds", ""))
        self.package = node.get("package", "")
    
    def _parse_bounds(self, bounds_str):
        """Parse '[0,0][1080,2400]' format into dict."""
        match = re.findall(r"\[(\d+),(\d+)\]", bounds_str)
        if len(match) == 2:
            return {
                "left": int(match[0][0]),
                "top": int(match[0][1]),
                "right": int(match[1][0]),
                "bottom": int(match[1][1])
            }
        return None
    
    def center(self) -> tuple[int, int]:
        """Get center coordinates of this element."""
        b = self.bounds
        return (b["left"] + b["right"]) // 2, (b["top"] + b["bottom"]) // 2
    
    @property
    def is_interactive(self) -> bool:
        """Determine if this element is likely interactive."""
        if self.clickable or self.checkable:
            return True
        interactive_classes = [
            "android.widget.Button", "android.widget.ImageButton",
            "android.widget.EditText", "android.widget.CheckBox",
            "android.widget.Switch", "android.widget.RadioButton",
            "android.widget.Spinner", "android.widget.ToggleButton",
        ]
        if self.class_name in interactive_classes:
            return True
        # Elements with content descriptions are often tappable
        if self.content_desc and self.enabled:
            return True
        return False
    
    def to_dict(self):
        return {
            "text": self.text,
            "resource_id": self.resource_id,
            "class": self.class_name,
            "content_desc": self.content_desc,
            "clickable": self.clickable,
            "checked": self.checked,
            "enabled": self.enabled,
            "bounds": self.bounds
        }


class UIHierarchy:
    """Parsed UI hierarchy for the current screen."""
    
    def __init__(self, xml_content):
        self.root = ET.fromstring(xml_content)
        self.elements = self._parse_all()
    
    def _parse_all(self):
        elements = []
        for node in self.root.iter("node"):
            elements.append(UIElement(node))
        return elements
    
    def get_interactive(self) -> list[UIElement]:
        """Get all interactive elements."""
        return [e for e in self.elements if e.is_interactive and e.enabled]
    
    def get_all(self) -> list[UIElement]:
        """Get all elements."""
        return self.elements
    
    def find_by_text(self, text: str, fuzzy: bool = False) -> UIElement | None:
        """Find element by text content."""
        for e in self.elements:
            if fuzzy:
                if text.lower() in e.text.lower():
                    return e
            else:
                if e.text == text:
                    return e
        return None
    
    def find_by_resource_id(self, resource_id: str) -> UIElement | None:
        """Find element by resource ID (exact or partial match)."""
        for e in self.elements:
            if resource_id in e.resource_id:
                return e
        return None
    
    def find_by_content_desc(self, desc: str, fuzzy: bool = False) -> UIElement | None:
        """Find element by content description."""
        for e in self.elements:
            if fuzzy:
                if desc.lower() in e.content_desc.lower():
                    return e
            else:
                if e.content_desc == desc:
                    return e
        return None
    
    @property
    def activity_name(self) -> str:
        """Get current activity from the hierarchy root."""
        # Activity is not in the hierarchy XML directly
        # Must be obtained separately via dumpsys
        return ""


def dump_hierarchy(device) -> UIHierarchy:
    """Dump and parse the current UI hierarchy."""
    device.shell("uiautomator dump /sdcard/apptest_ui.xml")
    device.pull("/sdcard/apptest_ui.xml", "/tmp/apptest_ui.xml")
    with open("/tmp/apptest_ui.xml") as f:
        xml_content = f.read()
    return UIHierarchy(xml_content)
```

### Element Finder (`element_finder.py`)

Merges UIAutomator hierarchy with OCR results to get complete element coverage.

```python
"""
Merge UI hierarchy elements with OCR results to find all interactive
elements on screen, including those missing from the hierarchy.

This is critical for apps using custom views, Jetpack Compose, Flutter,
or any framework where UIAutomator doesn't capture all elements.
"""

class MergedElement:
    """An element found from either hierarchy or OCR."""
    def __init__(self, source, text, bounds, center, element_type="unknown",
                 resource_id="", clickable="unknown", checked=None, enabled=True):
        self.source = source  # "hierarchy" or "ocr"
        self.text = text
        self.bounds = bounds
        self.center = center
        self.element_type = element_type
        self.resource_id = resource_id
        self.clickable = clickable
        self.checked = checked
        self.enabled = enabled
    
    def serialize_for_llm(self, index: int) -> str:
        """Format this element for inclusion in an LLM prompt."""
        parts = [f"[{index}]"]
        parts.append(f"type={self.element_type}")
        if self.text:
            parts.append(f'text="{self.text}"')
        if self.resource_id:
            parts.append(f"id={self.resource_id}")
        if self.checked is not None:
            parts.append(f"checked={self.checked}")
        parts.append(f"source={self.source}")
        parts.append(f"center=({self.center[0]},{self.center[1]})")
        return " ".join(parts)


def merge_hierarchy_and_ocr(hierarchy: UIHierarchy, ocr_results: list) -> list[MergedElement]:
    """
    Combine hierarchy elements with OCR results.
    OCR fills gaps where the hierarchy is incomplete.
    """
    merged = []
    matched_ocr_indices = set()
    
    # First: add all hierarchy elements
    for elem in hierarchy.get_interactive():
        merged.append(MergedElement(
            source="hierarchy",
            text=elem.text or elem.content_desc,
            bounds=elem.bounds,
            center=elem.center(),
            element_type=elem.class_name.split(".")[-1] if elem.class_name else "unknown",
            resource_id=elem.resource_id,
            clickable=elem.clickable,
            checked=elem.checked if elem.checkable else None,
            enabled=elem.enabled
        ))
        
        # Match against OCR results to avoid duplicates
        for i, ocr in enumerate(ocr_results):
            if i in matched_ocr_indices:
                continue
            if _texts_match(elem.text, ocr["text"]) and _bounds_overlap(elem.bounds, ocr["bounds"]):
                matched_ocr_indices.add(i)
    
    # Second: add OCR results that hierarchy missed
    for i, ocr in enumerate(ocr_results):
        if i not in matched_ocr_indices:
            bounds = ocr["bounds"]
            center = (
                (bounds["left"] + bounds["right"]) // 2,
                (bounds["top"] + bounds["bottom"]) // 2
            )
            merged.append(MergedElement(
                source="ocr",
                text=ocr["text"],
                bounds=bounds,
                center=center
            ))
    
    return merged


def serialize_elements_for_llm(elements: list[MergedElement]) -> str:
    """Serialize all elements into a string for LLM prompts."""
    lines = []
    for i, elem in enumerate(elements):
        lines.append(elem.serialize_for_llm(i))
    return "\n".join(lines)


def _texts_match(text1: str, text2: str) -> bool:
    """Fuzzy text match between hierarchy and OCR text."""
    if not text1 or not text2:
        return False
    t1 = text1.lower().strip()
    t2 = text2.lower().strip()
    return t1 == t2 or t1 in t2 or t2 in t1


def _bounds_overlap(bounds1: dict, bounds2: dict) -> bool:
    """Check if two bounding boxes overlap significantly."""
    if not bounds1 or not bounds2:
        return False
    x_overlap = max(0, min(bounds1["right"], bounds2["right"]) - max(bounds1["left"], bounds2["left"]))
    y_overlap = max(0, min(bounds1["bottom"], bounds2["bottom"]) - max(bounds1["top"], bounds2["top"]))
    overlap_area = x_overlap * y_overlap
    area1 = (bounds1["right"] - bounds1["left"]) * (bounds1["bottom"] - bounds1["top"])
    if area1 == 0:
        return False
    return overlap_area / area1 > 0.5
```

### LLM Action Decision

The executor calls the LLM to decide what action to take when the knowledge base has no known action. The prompt includes the real UI elements currently on screen:

```python
ACTION_DECISION_PROMPT = """
You are controlling an Android app via ADB. You need to accomplish this goal:
"{goal_description}"

Test data available:
{test_data_json}

Current screen:
- Activity: {current_activity}
- Keyboard visible: {keyboard_visible}

Interactive elements on screen right now:
{serialized_elements}

What is the single next action to take? Choose exactly one:
- tap(element_index) — tap an element from the list above
- type(text) — type text into the currently focused field
- swipe_up() — scroll down
- swipe_down() — scroll up  
- press_back() — press back button
- press_enter() — press enter key
- wait(seconds) — wait for content to load

Respond as JSON:
{{"action": "tap", "args": {{"element_index": 3}}, "reasoning": "brief explanation"}}

Important:
- Pick actions based on the ACTUAL elements listed above, not what you think should be there
- If you need to type text, make sure an input field is focused first (tap it)
- If the goal seems already achieved based on what you see, respond with:
  {{"action": "done", "args": {{}}, "reasoning": "goal appears achieved because..."}}
"""
```

### Success Criteria Checking

Check whether a goal has been achieved using deterministic methods first, then LLM fallback:

```python
SUCCESS_CHECK_PROMPT = """
You are verifying whether a test goal has been achieved.

Goal: "{goal_description}"
Success criteria: "{success_criteria}"

Current screen:
- Activity: {current_activity}

Elements on screen:
{serialized_elements}

Based on what is currently on screen, is the success criteria met?

Respond as JSON:
{{"met": true|false, "confidence": "high|medium|low", "reasoning": "brief explanation"}}
"""

def check_success(goal, elements, hierarchy, device):
    """
    Check if goal success criteria are met.
    Try deterministic checks first, fall back to LLM.
    """
    criteria = goal["success_criteria"]
    
    # Deterministic check: screen/activity name match
    current_activity = get_current_activity(device)
    if "screen is visible" in criteria.lower():
        screen_name = criteria.lower().split("screen is visible")[0].strip()
        if screen_name in current_activity.lower():
            return True
    
    # Deterministic check: element text presence
    if "verify" in criteria.lower() and "appears" in criteria.lower():
        # Extract what should appear
        for elem in elements:
            if any(keyword in elem.text.lower() for keyword in extract_keywords(criteria)):
                return True
    
    # Deterministic check: toggle/checkbox state
    if "toggle" in criteria.lower() and "on" in criteria.lower():
        for elem in elements:
            if elem.checked is True and "switch" in elem.element_type.lower():
                return True
    
    # Fall back to LLM for complex criteria
    prompt = SUCCESS_CHECK_PROMPT.format(
        goal_description=goal["description"],
        success_criteria=criteria,
        current_activity=current_activity,
        serialized_elements=serialize_elements_for_llm(elements)
    )
    response = call_llm(prompt)
    result = parse_json(response)
    return result.get("met", False)
```

## Knowledge Base

The knowledge base accumulates per-app knowledge across test runs. It stores facts about screens and actions, not a rigid navigation graph.

```python
"""
Per-app knowledge base that accumulates over test runs.
Stores natural language facts about screens and actions,
not graph edges. The LLM reasons over these facts at execution time.
"""

class KnowledgeBase:
    def __init__(self, app_package: str, storage_path: str = ".apptest/knowledge"):
        self.app_package = app_package
        self.storage_path = storage_path
        self.screens = {}   # screen_id -> screen knowledge
        self.actions = []   # recorded action outcomes
        self.patterns = []  # general app patterns
    
    def record_screen(self, screen_id: str, activity: str, description: str, 
                      key_elements: list[str]):
        """Record knowledge about a screen."""
        self.screens[screen_id] = {
            "activity": activity,
            "description": description,
            "key_elements": key_elements,
            "seen_count": self.screens.get(screen_id, {}).get("seen_count", 0) + 1,
            "last_seen": datetime.now().isoformat()
        }
    
    def record_action(self, goal: str, screen_id: str, action: dict, 
                      resulted_in_screen: str):
        """Record what happened when an action was taken."""
        self.actions.append({
            "goal": goal,
            "from_screen": screen_id,
            "action": action,
            "to_screen": resulted_in_screen,
            "timestamp": datetime.now().isoformat()
        })
    
    def record_success(self, goal: dict, actions_taken: list):
        """Record a successful goal completion for future replay."""
        # Store the sequence of actions that achieved this goal
        pass
    
    def lookup(self, goal: str, current_screen: str, elements: list) -> dict | None:
        """
        Look up a known action for this goal on this screen.
        Returns an action dict if a known path exists, None otherwise.
        """
        for record in reversed(self.actions):  # most recent first
            if record["from_screen"] == current_screen:
                # Check if the goal is similar
                if _goals_match(goal, record["goal"]):
                    # Verify the action's target element still exists on screen
                    if _action_still_valid(record["action"], elements):
                        return record["action"]
        return None
    
    def summarize(self) -> str:
        """Produce a text summary for inclusion in LLM prompts."""
        lines = []
        for screen_id, info in self.screens.items():
            lines.append(f"Screen: {info['description']} (activity: {info['activity']})")
            for elem in info['key_elements']:
                lines.append(f"  - {elem}")
        
        for pattern in self.patterns:
            lines.append(f"Pattern: {pattern}")
        
        return "\n".join(lines) if lines else "No prior knowledge about this app."
    
    def save(self):
        """Persist knowledge base to disk."""
        os.makedirs(self.storage_path, exist_ok=True)
        data = {
            "app_package": self.app_package,
            "screens": self.screens,
            "actions": self.actions,
            "patterns": self.patterns
        }
        path = os.path.join(self.storage_path, f"{self.app_package}.json")
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    
    @classmethod
    def load(cls, app_package: str, storage_path: str = ".apptest/knowledge"):
        """Load knowledge base from disk, or create empty one."""
        kb = cls(app_package, storage_path)
        path = os.path.join(storage_path, f"{app_package}.json")
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            kb.screens = data.get("screens", {})
            kb.actions = data.get("actions", [])
            kb.patterns = data.get("patterns", [])
        return kb
```

## Deterministic Screen Identification

Identify the current screen using deterministic signals from the UI hierarchy, not vision models.

```python
"""
Deterministic screen state identification.
Produces a stable hash from UI hierarchy signals.
No vision models, no LLM calls.
"""

import hashlib

def identify_screen(device, hierarchy: UIHierarchy) -> str:
    """
    Produce a deterministic screen identifier from hierarchy signals.
    Same screen state -> same ID, every time.
    """
    activity = get_current_activity(device)
    
    # Element type multiset (quantized to reduce sensitivity)
    type_counts = {}
    for elem in hierarchy.get_all():
        short_type = elem.class_name.split(".")[-1] if elem.class_name else "unknown"
        type_counts[short_type] = type_counts.get(short_type, 0) + 1
    
    # Quantize counts: 0, 1, few (2-5), many (6+)
    quantized = {}
    for t, count in sorted(type_counts.items()):
        if count == 0:
            q = "0"
        elif count == 1:
            q = "1"
        elif count <= 5:
            q = "few"
        else:
            q = "many"
        quantized[t] = q
    
    # Extract structural template: collapse repeated siblings
    template = extract_template(hierarchy)
    
    # Key identifiers
    nav_bar_title = ""
    for elem in hierarchy.get_all():
        if "toolbar" in elem.class_name.lower() or "actionbar" in elem.class_name.lower():
            if elem.text:
                nav_bar_title = elem.text
                break
    
    # Combine signals
    fingerprint = {
        "activity": activity,
        "nav_title": nav_bar_title,
        "type_distribution": quantized,
        "template": template,
        "has_keyboard": is_keyboard_shown(device)
    }
    
    # Hash to stable ID
    fingerprint_str = json.dumps(fingerprint, sort_keys=True)
    return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]


def extract_template(hierarchy: UIHierarchy) -> str:
    """
    Extract a structural template from the hierarchy.
    Collapses repeated siblings so that a list with 5 items
    and a list with 50 items produce the same template.
    """
    # Simplified: use the element type tree with repeated children collapsed
    # Full implementation would walk the XML tree recursively
    types_in_order = []
    prev_type = None
    repeat_count = 0
    
    for elem in hierarchy.get_all():
        short_type = elem.class_name.split(".")[-1] if elem.class_name else "?"
        if short_type == prev_type:
            repeat_count += 1
        else:
            if repeat_count > 1:
                types_in_order.append(f"{prev_type}*N")
            elif prev_type:
                types_in_order.append(prev_type)
            prev_type = short_type
            repeat_count = 1
    
    # Don't forget the last element
    if repeat_count > 1:
        types_in_order.append(f"{prev_type}*N")
    elif prev_type:
        types_in_order.append(prev_type)
    
    return "|".join(types_in_order[:30])  # truncate for sanity
```

## Testing with Wikipedia Android App

### Setup

```bash
# 1. Clone Wikipedia Android
git clone https://github.com/wikimedia/apps-android-wikipedia.git
cd apps-android-wikipedia

# 2. Create apptest config
cat > apptest.yml << 'EOF'
app:
  name: "Wikipedia"
  package: "org.wikipedia.dev"  # dev flavor
  platform: android

source:
  screens_dir: "app/src/main/java/org/wikipedia"
  layouts_dir: "app/src/main/res/layout"
  strings_file: "app/src/main/res/values/strings.xml"
  nav_graph: "app/src/main/res/navigation"
  manifest: "app/src/main/AndroidManifest.xml"

llm:
  provider: anthropic
  model: claude-sonnet-4-20250514

execution:
  device: "emulator"
  timeout_per_test: 120
  screenshot_on_failure: true
  reset_app_between_tests: true
EOF

# 3. Build the app
./gradlew assembleDevDebug

# 4. Start emulator and install
emulator -avd Pixel_6_API_33 &
adb install app/build/outputs/apk/dev/debug/app-dev-debug.apk
```

### Test with a Real PR

```bash
# Find a recent merged PR with meaningful changes
# Example: a PR that modified search functionality

# Check out the merge commit
git log --oneline --merges -20  # find a good one
git checkout <merge_commit>

# Run the full pipeline
apptest analyze --diff "HEAD~1..HEAD" --repo .
apptest generate
apptest execute --device emulator-5554 --app org.wikipedia.dev
apptest report --results .apptest/results.json
```

### Evaluation Criteria

For each PR tested, evaluate:

| Criteria | Question | Target |
|----------|----------|--------|
| Analysis accuracy | Did it correctly identify affected screens? | >90% |
| Test relevance | Are generated tests relevant to the change? | >80% |
| Test completeness | Did it miss important test scenarios? | <2 missed per PR |
| Test nonsense | Did it generate tests that don't make sense? | <1 per PR |
| Execution success | Did executable tests actually run to completion? | >70% |
| Correct verdicts | Did passing tests pass for the right reason? | >90% |
| Failure accuracy | Did failing tests fail for the right reason? | >80% |

### Development Phases

**Phase 1 (Weeks 1-2): Analyzer**
- Implement diff parsing, file mapping, context extraction
- Test on 20+ Wikipedia PRs
- Validate that affected screens are correctly identified
- No device needed yet

**Phase 2 (Weeks 3-4): Generator**
- Implement LLM test generation with prompt engineering
- Evaluate test quality on the same PRs
- Iterate on prompts until quality targets are met
- No device needed yet

**Phase 3 (Weeks 5-8): Executor**
- Implement device primitives and UI inspector
- Implement OCR integration for element coverage
- Implement the planner and step executor
- Get basic Wikipedia flows working: onboarding, search, article view
- Handle Wikipedia-specific challenges: onboarding flow, language selection

**Phase 4 (Weeks 9-12): Knowledge Base and Polish**
- Implement knowledge base accumulation and retrieval
- Implement deterministic screen identification
- Build the reporting layer (JSON + GitHub PR comments)
- Handle edge cases: popups, permission dialogs, loading states
- End-to-end testing across 50+ Wikipedia PRs

## CI Integration Examples

### GitHub Actions

```yaml
name: AppTest
on:
  pull_request:
    branches: [main]

jobs:
  apptest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # need full history for diff

      - name: Set up JDK
        uses: actions/setup-java@v4
        with:
          java-version: '17'
          distribution: 'temurin'

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install AppTest
        run: pip install apptest

      - name: Build APK
        run: ./gradlew assembleDevDebug

      - name: Enable KVM
        run: |
          echo 'KERNEL=="kvm", GROUP="kvm", MODE="0666"' | sudo tee /etc/udev/rules.d/99-kvm.rules
          sudo udevadm control --reload-rules
          sudo udevadm trigger

      - name: Start Emulator
        uses: reactivecircus/android-emulator-runner@v2
        with:
          api-level: 33
          script: |
            adb install app/build/outputs/apk/dev/debug/app-dev-debug.apk
            apptest analyze --diff "origin/main..HEAD"
            apptest generate
            apptest execute --device emulator-5554 --app org.wikipedia.dev
            apptest report --results .apptest/results.json --github-pr ${{ github.event.pull_request.number }} --repo ${{ github.repository }}
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### GitLab CI

```yaml
apptest:
  stage: test
  image: python:3.11
  services:
    - name: android-emulator:latest
  script:
    - pip install apptest
    - ./gradlew assembleDevDebug
    - apptest analyze --diff "origin/main..HEAD"
    - apptest generate
    - apptest execute --device emulator-5554 --app org.wikipedia.dev
    - apptest report --results .apptest/results.json
  artifacts:
    paths:
      - .apptest/results.json
      - .apptest/screenshots/
  variables:
    ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
```

### Generic (any CI)

```bash
#!/bin/bash
# apptest-ci.sh — works in any CI system

set -e

pip install apptest

# Build
./gradlew assembleDevDebug

# Analyze
apptest analyze --diff "origin/main..HEAD" --repo .

# Generate tests
apptest generate --analysis .apptest/analysis.json

# Execute (assumes emulator is already running)
apptest execute \
  --tests .apptest/tests.json \
  --device emulator-5554 \
  --app org.wikipedia.dev

# Report
apptest report --results .apptest/results.json

# Exit with test status
python -c "
import json
results = json.load(open('.apptest/results.json'))
failed = sum(1 for t in results['tests'] if not t['passed'])
exit(1 if failed else 0)
"
```

## Key Design Decisions

1. **CLI-first, not plugin-first.** A CLI runs in any CI system. Platform-specific plugins multiply engineering work. The customer writes 3-5 lines of CI config to integrate.

2. **Hierarchy + OCR, not vision models for element finding.** UIAutomator hierarchy is deterministic but incomplete. OCR is deterministic and catches what hierarchy misses. Together they provide complete element coverage without non-deterministic vision model calls.

3. **Goal-level planning, not action-level planning.** The LLM planner produces goals ("log in"), not actions ("tap the email field"). Action decisions happen at execution time with the real screen in front of the executor.

4. **Knowledge base as facts, not graph.** Store natural language facts about screens and actions. The LLM reasons over them. This is resilient to UI changes — if a button moves or gets renamed, the LLM adapts. A rigid graph would break.

5. **Deterministic screen identification.** Screen state is identified by hashing hierarchy signals (activity name, element type distribution, structural template). No vision models in the identification loop.

6. **LLM calls are minimized at execution time.** The knowledge base handles known screens and actions. LLM is called only for genuinely unknown situations. Over time, most execution becomes deterministic replay.

7. **Source code stays in customer's infra.** The CLI reads source locally, extracts only relevant context, and sends snippets to the LLM API. The full repo never leaves their environment.
