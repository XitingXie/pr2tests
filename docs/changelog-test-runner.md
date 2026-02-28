# Changelog: LLM-Driven Test Runner (ADB + Gemini Vision)

**Date:** 2026-02-27
**Scope:** `apptest/runner/`, `apptest/cli.py`, tests

## Why

The `apptest generate` step produces `tests.json` with natural-language test steps, but there was no way to actually **execute** them on a real device. The pipeline stopped at "here's what to test" — this change completes it into "here are the test results with screenshots and action logs." The runner uses ADB for device control and Gemini 2.0 Flash (vision) to interpret screenshots and decide actions, creating an autonomous LLM-in-the-loop test execution system.

## What Changed

### 1. New `apptest/runner/` package (7 files)

#### `schemas.py` — Data structures
- `ActionType` enum: 12 action types (tap, type, swipe_up/down, back, home, enter, launch, wait, done, assert_pass, assert_fail).
- `Action`: single device action with coordinates, text, reasoning.
- `StepResult`: per-step outcome with action log and timing.
- `TestRunResult`: per-test outcome with step list. Includes `__test__ = False` to prevent pytest collection.
- `RunSummary`: aggregate results across all tests.
- `to_execution_results()`: converts `RunSummary` to the existing `TestExecutionResult` format from `reporter/report_schema.py`, bridging runner output to the reporting pipeline.

#### `adb.py` — ADB device primitives
- `ADBDevice` class wrapping subprocess calls. Constructor takes `serial` (default `"emulator-5554"`).
- **Screenshots:** `screenshot_bytes()` returns raw PNG via `adb exec-out screencap -p` (no disk I/O); `screenshot(path)` also saves to file.
- **Input:** `tap(x,y)`, `type_text(text)` (with space escaping), `swipe(x1,y1,x2,y2,duration)`, `swipe_up()`, `swipe_down()`, `press_back()`, `press_home()`, `press_enter()`.
- **App management:** `launch_app(package)` via monkey, `force_stop(package)`, `clear_app_data(package)`.
- **Device info:** `get_screen_size()` parses `wm size` output, `is_keyboard_shown()` checks `dumpsys input_method`.
- **Connection:** `is_connected()` checks `adb get-state`, `wait_for_device(timeout)` polls with deadline.

#### `step_parser.py` — Natural language step parser
- `parse_test_steps(description)`: splits on numbered lines (`1. ... 2. ...`) into `ParsedStep(index, text, is_verification)`.
- Verification detected by 8 prefix keywords: verify, check, assert, confirm, ensure, validate, expect, should.
- Fallback: single unnumbered description becomes one action step.

#### `prompts.py` — Vision prompts
- `ACTION_PROMPT`: screenshot + step text + resolution → JSON with action type, coordinates, text, reasoning. Includes rule to skip onboarding/setup screens by tapping "Skip" or "Get started."
- `VERIFICATION_PROMPT`: screenshot + assertion text → JSON with passed/confidence/reasoning.
- Both instruct the LLM to return only JSON, no markdown fences. Temperature 0.1.

#### `vision.py` — Gemini vision integration
- `decide_action()`: sends screenshot PNG + action prompt to Gemini via `genai.types.Part.from_bytes()`, parses response into `Action`. Unknown action types default to `WAIT`.
- `verify_step()`: sends screenshot + verification prompt, returns `(passed, confidence, reasoning)`.
- `_call_vision()`: core multimodal call. API key from config or `GEMINI_API_KEY` env var.
- `_parse_json()`: reuses the fence-stripping + brace-finding pattern from `generator/test_generator.py`.

#### `executor.py` — Main execution loop
- **Per-test flow:** `force_stop` + `clear_app_data` → parse steps → for each step: action loop or verification.
- **Action steps:** Loop up to 15 times: screenshot → `decide_action()` → if `done` break → execute via ADB → wait 1.5s. "Open the app" / "launch the app" detected as special case (just `launch_app`).
- **Verification steps:** Wait 1s → screenshot → `verify_step()` → pass/fail.
- **Stuck detection:** If 3 consecutive screenshots are byte-identical, inject `press_back()` as recovery.
- **Screenshot saving:** Every screenshot saved to `output_dir/screenshots/{test_id}_step{n}_action{n}.png`.
- `run_all_tests()`: orchestrates all tests from `tests.json`, writes `results.json` with full action logs.

### 2. CLI command: `apptest run`
- **Options:** `--tests` (default `.apptest/tests.json`), `--output` (default `.apptest/results`), `--config`, `--device` (default `emulator-5554`), `--package` (overrides config).
- Prints per-test pass/fail summary with failure reasons.

### 3. Unit tests
- `test_step_parser.py`: 12 tests — numbered steps, verification detection (8 prefixes), single step, no-numbers fallback, empty input, mixed formatting, order preservation, case insensitivity, mid-word verification not matched.
- `test_runner.py`: 21 tests across 6 classes — JSON parsing (clean, fenced, surrounding text, malformed, array extraction), action decoding (tap, type, done, unknown→wait), verification (pass/fail/malformed→fail), launch detection, full executor with mocked ADB+vision, `to_execution_results` conversion.

## E2E Results (Wikipedia Android)

Ran against `pr6350-search-keyboard` tests (4 test cases) on `Medium_Phone_API_35` emulator with `org.wikipedia.alpha`.

**Default mode** (no `--clear-data`, onboarding pre-completed):

| Test | Status | Steps | Navigate actions | Notes |
|------|--------|-------|-----------------|-------|
| test_001 | **PASS** | 4/4 | 5 | Search no-results term, keyboard verified |
| test_002 | **PASS** | 4/4 | 7 | Search valid term, keyboard absence verified |
| test_003 | FAIL | 4/6 | 2 | "Enter another search term" got stuck (15 actions) |
| test_004 | FAIL | 3/4 | 11 | Keyboard hidden (correct failure — online mode) |

**Key improvement:** Removing per-test `clear_app_data` dropped "Navigate to Search" from 8-10 actions to 2-7 actions, allowing tests to progress further. test_003 now passes step4 ("clear the search term") and only fails on step5.

## Lessons Learned

- **Don't clear app data between tests.** `clear_app_data` resets the app to first-run state, requiring 4-8 actions just to dismiss the setup wizard before any test logic runs. Switching to `force_stop` only (preserving data) cut navigation actions from 8-10 to 2-5. Added `--clear-data` flag for when a clean slate is needed.
- **Stuck detection is essential.** The agent sometimes taps an element that doesn't navigate (e.g., tapping Continue but the screen didn't change), creating an infinite loop. Byte-comparing 3 consecutive screenshots and injecting `press_back()` breaks the loop reliably.
- **`adb exec-out screencap -p` is much faster than pull-from-device.** Returning PNG bytes directly via stdout avoids writing to `/sdcard/`, pulling, and cleaning up — saving ~500ms per screenshot.
- **The `type_text` space escaping matters.** ADB `input text` treats spaces as argument separators; `%s` is the escape. Without this, multi-word inputs silently truncate.

## Potential Issues

- **Action budget vs. app complexity:** 15 actions may not be enough for apps with longer onboarding flows or complex navigation hierarchies. Could make this configurable.
- **Gemini Flash accuracy on coordinate targeting:** The model sometimes aims at the edge of buttons rather than center. Adding explicit "aim for CENTER" in the prompt helps but doesn't eliminate all mis-taps.
- **No test parallelism:** Tests run sequentially on a single device. Could parallelize across multiple emulators.
- **No retry on Gemini API failures:** A rate limit or network error fails the step immediately.

## Future Improvements

- Make `MAX_ACTIONS_PER_STEP` configurable via CLI or config
- Add `select_all` + clear action for text fields before retyping
- Support test filtering (`--test-id test_001`)
- Add retry logic for transient Gemini API failures
- Parallelize tests across multiple emulator instances
- Wire `to_execution_results()` into the `apptest report` pipeline to replace mock tests with real results
- Add `select_all` action type for text field selection (useful for "clear the search term" scenarios)
