# Plan: LLM-Driven Test Runner with ADB + Gemini Vision

## Context

The generator produces `tests.json` with natural-language test steps (e.g. "1. Open the app. 2. Navigate to Search. 3. Type 'asdfjkl'. 4. Verify keyboard is displayed."). We need to actually **execute** these tests on a real Android emulator using ADB for device control and Gemini 2.0 Flash (vision) to interpret screenshots and decide actions.

**Current state:** Android SDK is installed. Available AVDs: `Medium_Phone_API_35`, `phone1`. Wikipedia Android is NOT installed yet. Gemini API key is configured.

## Execution Flow

For each test case, the runner parses numbered steps and classifies them as **action steps** or **verification steps**.

### Action Steps (e.g. "Navigate to the Search screen")

Loop up to 15 times per step:

```
┌─────────────────────────────────────────┐
│  Take screenshot via ADB                │
│  (adb exec-out screencap -p → PNG bytes)│
└──────────────┬──────────────────────────┘
               ▼
┌─────────────────────────────────────────┐
│  Send screenshot + step text to Gemini  │
│  "Given this screen, how do I perform:  │
│   'Navigate to the Search screen'?"     │
└──────────────┬──────────────────────────┘
               ▼
┌─────────────────────────────────────────┐
│  Gemini returns JSON:                   │
│  {"action":"tap","x":540,"y":200,       │
│   "reasoning":"Tap search icon"}        │
│                                         │
│  OR {"action":"done"} if step is done   │
└──────────────┬──────────────────────────┘
               ▼
┌─────────────────────────────────────────┐
│  Execute action via ADB:                │
│  adb shell input tap 540 200            │
│  Wait 1.5s for UI to settle             │
└──────────────┬──────────────────────────┘
               ▼
          Loop back to screenshot
          (until "done" or 15 attempts)
```

### Verification Steps (e.g. "Verify that the keyboard is displayed")

Single LLM call:

```
┌─────────────────────────────────────────┐
│  Take screenshot                        │
└──────────────┬──────────────────────────┘
               ▼
┌─────────────────────────────────────────┐
│  Send screenshot + verification text    │
│  "Is the keyboard displayed?"           │
└──────────────┬──────────────────────────┘
               ▼
┌─────────────────────────────────────────┐
│  Gemini returns:                        │
│  {"passed":true,"confidence":"high",    │
│   "reasoning":"Keyboard visible at      │
│    bottom of screen"}                   │
└──────────────┬──────────────────────────┘
               ▼
         passed=true → PASS
         passed=false → FAIL (test stops)
```

The LLM acts as the "eyes" (interprets screenshots), ADB acts as the "hands" (executes taps/types/swipes). The loop continues until the LLM says the step is accomplished or we hit the max attempts limit.

## Step 0: Start Emulator & Install Wikipedia

### 0a. Start the emulator (if not already running)

The `ADBDevice` class and CLI `run` command will check `adb devices` first. If no device is connected, we start one:

```bash
# List available AVDs
~/Library/Android/sdk/emulator/emulator -list-avds

# Start emulator in background (headless or with GUI)
~/Library/Android/sdk/emulator/emulator -avd Medium_Phone_API_35 &

# Wait for boot
adb wait-for-device
adb shell getprop sys.boot_completed  # wait until "1"
```

The runner's `ADBDevice.is_connected()` checks device state. The CLI will error with a clear message if no device is found, telling the user to start an emulator.

### 0b. Install Wikipedia Android

Clone the Wikipedia Android repo and build a debug APK:

```bash
git clone https://github.com/wikimedia/apps-android-wikipedia.git /tmp/wiki-android
cd /tmp/wiki-android
./gradlew assembleDevDebug
adb install app/build/outputs/apk/dev/debug/app-dev-debug.apk
```

If build fails due to SDK version mismatch, install the required SDK platform first (`sdkmanager "platforms;android-35"`). Alternatively, download a pre-built APK from GitHub releases.

## Step 1: Create `apptest/runner/` Package

### `apptest/runner/__init__.py` — Empty init

### `apptest/runner/schemas.py` — Data structures

```python
class ActionType(str, Enum):
    TAP = "tap"
    TYPE = "type"
    SWIPE_UP = "swipe_up"
    SWIPE_DOWN = "swipe_down"
    BACK = "back"
    HOME = "home"
    ENTER = "enter"
    LAUNCH = "launch"
    WAIT = "wait"
    DONE = "done"
    ASSERT_PASS = "assert_pass"
    ASSERT_FAIL = "assert_fail"

@dataclass
class Action:
    action_type: ActionType
    x: int = 0; y: int = 0; text: str = ""; reasoning: str = ""; duration_ms: int = 0

@dataclass
class StepResult:
    step_index: int; step_text: str; status: str  # "passed"|"failed"|"error"
    actions: list[Action]; failure_reason: str = ""; duration_ms: int = 0

@dataclass
class TestRunResult:
    test_id: str; status: str  # "passed"|"failed"|"skipped"|"error"
    steps: list[StepResult]; total_duration_ms: int = 0; failure_reason: str = ""

@dataclass
class RunSummary:
    started_at: str; completed_at: str; device_serial: str; app_package: str
    total_tests: int; passed: int; failed: int; skipped: int; errored: int
    results: list[TestRunResult]
```

Maps to existing `TestExecutionResult` in `reporter/report_schema.py` via a `to_execution_results()` converter.

### `apptest/runner/adb.py` — ADB device primitives

`ADBDevice` class wrapping subprocess calls:
- `screenshot_bytes() -> bytes` — `adb exec-out screencap -p` (returns raw PNG, no disk I/O)
- `screenshot(path) -> bytes` — same but also saves to file
- `tap(x, y)`, `type_text(text)`, `swipe(x1,y1,x2,y2,duration)`, `swipe_up()`, `swipe_down()`
- `press_back()`, `press_home()`, `press_enter()`
- `launch_app(package)`, `force_stop(package)`, `clear_app_data(package)`
- `get_screen_size() -> (w, h)`, `is_keyboard_shown() -> bool`, `is_connected() -> bool`
- `wait_for_device(timeout=30)` — `adb wait-for-device` with timeout

Constructor takes `serial` (default `"emulator-5554"`). All methods raise `RuntimeError` with clear messages if the device is not connected.

### `apptest/runner/step_parser.py` — Parse natural language steps

Split description on numbered lines (`1. ... 2. ...`) into `ParsedStep(index, text, is_verification)`. Verification detected by prefix words: verify, check, assert, confirm, ensure, etc.

### `apptest/runner/prompts.py` — Two vision prompts

**ACTION_PROMPT**: Given screenshot + step text + screen resolution → return `{"action": "tap", "x": 540, "y": 1200, "text": "", "reasoning": "..."}`. Actions: tap, type, swipe_up, swipe_down, back, enter, wait, done.

**VERIFICATION_PROMPT**: Given screenshot + step text → return `{"passed": true, "confidence": "high", "reasoning": "..."}`.

Both instruct the LLM to return only JSON, no fences. Temperature 0.1 for deterministic output.

### `apptest/runner/vision.py` — Gemini vision integration

- `decide_action(screenshot_png, step_text, ..., config) -> Action` — Sends image + ACTION_PROMPT to Gemini via `genai.types.Part.from_bytes()`, parses response into Action.
- `verify_step(screenshot_png, step_text, ..., config) -> (passed, confidence, reasoning)` — Sends image + VERIFICATION_PROMPT, returns bool result.
- `_call_vision(prompt, image_png, config) -> str` — Core Gemini multimodal call.
- JSON parsing reuses the fence-stripping + brace-finding pattern from `generator/test_generator.py`.

### `apptest/runner/executor.py` — Main execution loop

**Per-test flow:**
1. `force_stop` + `clear_app_data` (reset between tests)
2. Parse steps from description via `step_parser`
3. For each step:
   - **Action step**: Loop up to 15 times: screenshot → `decide_action()` → if `done` break → execute action via ADB → wait 1.5s → repeat. "Open the app" detected as special case (just `launch_app`).
   - **Verification step**: Wait 1s → screenshot → `verify_step()` → pass/fail.
4. If any step fails, test fails immediately (no further steps).

**Stuck detection:** If 3 consecutive screenshots are identical bytes, inject `press_back()` as recovery.

**Key functions:**
- `execute_test(test_case, device, config, ...) -> TestRunResult`
- `run_all_tests(tests_path, config, ...) -> RunSummary` — orchestrates all tests, writes `results.json`
- `to_execution_results(summary) -> list[TestExecutionResult]` — converts to report-compatible format

## Step 2: Add `apptest run` CLI Command

In `apptest/cli.py`:

```
apptest run --tests .apptest/tests.json --output .apptest/results --config apptest.yml --device emulator-5554
```

Options: `--tests` (input), `--output` (results dir), `--config`, `--device` (serial), `--package` (override). Prints per-test pass/fail summary.

## Step 3: Unit Tests

### `apptest/tests/test_step_parser.py`
- Numbered steps parsed correctly
- Verification steps detected (verify, check, assert prefixes)
- Edge cases: single step, no numbers, mixed formatting

### `apptest/tests/test_runner.py`
- Action parsing from JSON (valid, fenced, malformed)
- Verification parsing (passed/failed/malformed)
- Launch step detection
- `execute_test` with mocked ADB + mocked vision (end-to-end unit test)
- `to_execution_results` conversion

## Step 4: End-to-End Verification

1. Install Wikipedia on emulator (step 0)
2. Run: `apptest run --tests .apptest/integration/pr6350-search-keyboard/tests.json --output .apptest/integration/pr6350-search-keyboard/results`
3. Inspect `results.json` — verify pass/fail status, screenshots saved, step-by-step action log
4. Run unit tests: `pytest apptest/tests/test_step_parser.py apptest/tests/test_runner.py -v`

## Files Modified

| File | Change |
|------|--------|
| `apptest/runner/__init__.py` | New — empty |
| `apptest/runner/schemas.py` | New — ActionType, Action, StepResult, TestRunResult, RunSummary |
| `apptest/runner/adb.py` | New — ADBDevice class |
| `apptest/runner/step_parser.py` | New — parse_test_steps() |
| `apptest/runner/prompts.py` | New — ACTION_PROMPT, VERIFICATION_PROMPT |
| `apptest/runner/vision.py` | New — decide_action(), verify_step() |
| `apptest/runner/executor.py` | New — execute_test(), run_all_tests() |
| `apptest/cli.py` | Add `run` command |
| `apptest/tests/test_step_parser.py` | New — step parsing tests |
| `apptest/tests/test_runner.py` | New — runner unit tests |
