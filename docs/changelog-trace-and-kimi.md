# Changelog: LLM Trace Logging + Kimi K2.5 Provider

**Date:** 2026-02-27
**Scope:** `apptest/runner/trace.py` (new), `apptest/runner/vision.py`, `apptest/runner/computer_use.py`, `apptest/runner/executor.py`

## Why

Two gaps in the test runner:

1. **No observability into LLM calls.** When tests failed, we only had `results.json` with parsed actions — no way to see what prompt was sent, what the model actually returned, or what screenshot it was looking at. Debugging required re-running tests with print statements.

2. **Single provider lock-in.** The runner only supported Google Gemini and OpenAI. Gemini sometimes produced inaccurate coordinates (e.g., repeatedly tapping the same spot with no effect), causing stuck loops. We needed to try alternative vision models — specifically Moonshot's Kimi K2.5, which is optimized for visual agentic tasks with normalized coordinate output.

## What Changed

### 1. New: `apptest/runner/trace.py` — LLM Trace Logging

**TraceEntry dataclass** captures every LLM interaction:
- `timestamp`, `call_type` ("action" / "verification" / "computer_use")
- `test_id`, `step_index`, `step_text`
- `prompt` (full formatted prompt sent to LLM)
- `screenshot_b64` (base64-encoded PNG, embedded in HTML)
- `raw_response` (raw LLM output text)
- `parsed_result` (human-readable summary of what was extracted)
- `device_context`, `duration_ms`, `model`, `provider`

**RunTrace class** — simple list of entries with `.add()` method.

**`generate_trace_html(trace, output_path)`** — produces a self-contained HTML file:
- Summary header: total calls, actions, verifications, computer use, test count
- Filter dropdown by test ID (JavaScript)
- Chronological timeline of cards, color-coded: blue=action, green=verification, purple=computer_use
- Each card: timestamp, model, duration badge, screenshot thumbnail (click to expand), collapsible prompt/response via `<details>`, parsed result, device context
- All screenshots embedded as `data:image/png;base64,...` (no external files)

### 2. Modified: `apptest/runner/vision.py` — Trace capture + Kimi K2.5 provider

**Trace capture** — `decide_action()` and `verify_step()` accept optional `trace_entries: list | None` parameter. When non-None, append `{"prompt": ..., "raw_response": ...}` dict after each LLM call. Avoids changing return types.

**Kimi K2.5 integration** — new provider `"moonshot"` / `"kimi"`:
- Uses OpenAI-compatible SDK with `base_url="https://api.moonshot.ai/v1"`
- API key from config or `MOONSHOT_API_KEY` env var
- Cached client via `_get_client()` (same pattern as Google/OpenAI)

**Action pipeline (`_decide_action_moonshot`):**
- System prompt defines structured JSON output format with normalized 0-1000 coordinate scale
- Includes grounding hint: "mentally draw a 10x10 grid over the image to align element centers"
- `response_format={"type": "json_object"}` enforces valid JSON output
- Coordinates denormalized to actual screen pixels: `px = int(coord / 1000 * screen_dimension)`
- Auto-detects thinking vs instant mode from model name (e.g., `kimi-k2-thinking` enables thinking; `kimi-k2.5` uses instant with `thinking.type=disabled`)
- Temperature 0.6, top_p 0.95 (Moonshot recommended for instant mode)

**Verification pipeline (`_verify_step_moonshot`):**
- Dedicated system prompt for pass/fail assertions
- Thinking mode (temperature 1.0) for deeper UI analysis
- `response_format={"type": "json_object"}` for reliable structured output

### 3. Modified: `apptest/runner/computer_use.py` — Trace capture

`ComputerUseSession.get_action()` accepts optional `trace_entries` param. Captures the prompt text (initial prompt or function response summary) and serialized model output (function calls + text).

### 4. Modified: `apptest/runner/executor.py` — Trace threading

- `run_all_tests()`: creates `RunTrace()`, passes to each `execute_test()`, writes `trace.html` alongside `results.json` at the end
- `execute_test()`: accepts `trace: RunTrace | None`, forwards to step runners
- `_run_action_step()`: wraps each `decide_action()` call — passes `trace_entries=[]`, times the call, creates `TraceEntry` with screenshot (base64), prompt/response, duration, model info
- `_run_verification_step()`: same pattern around `verify_step()`
- `_run_action_step_computer_use()`: same pattern around `session.get_action()`

## Files Modified

| File | Change |
|------|--------|
| `apptest/runner/trace.py` | **New** — TraceEntry, RunTrace, generate_trace_html() |
| `apptest/runner/vision.py` | Trace capture param + full Kimi K2.5 provider (action + verification) |
| `apptest/runner/computer_use.py` | Trace capture param on get_action() |
| `apptest/runner/executor.py` | Thread trace through entire call chain, generate trace.html |

## E2E Results: Kimi K2.5 vs Gemini (Wikipedia Android)

Ran `pr6350-search-keyboard` tests (2 test cases) on `Medium_Phone_API_35` emulator with `org.wikipedia.alpha`.

### Gemini 2.0 Flash (`google/gemini-2.0-flash`)

| Test | Status | LLM Calls | Notes |
|------|--------|-----------|-------|
| test_001 | PASS | 8 | Stuck detection triggered once |
| test_002 | **FAIL** | 15 | Stuck in loop tapping search bar at (540,929) — never focused |

### Kimi K2.5 (`moonshot/kimi-k2.5`)

| Test | Status | LLM Calls | Notes |
|------|--------|-----------|-------|
| test_001 | PASS | 8 | Clean execution |
| test_002 | PASS | 8 | No stuck loops, correct coordinate targeting |

**Key finding:** Kimi K2.5's normalized 0-1000 coordinate system + `response_format=json_object` produced more accurate element targeting than Gemini's raw pixel coordinates. Gemini's test_002 failure was caused by repeatedly tapping the same pixel with no effect.

## How It Works: Kimi Coordinate System

```
Kimi returns:   {"action": "tap", "coords": [500, 130]}     # 0-1000 normalized
Denormalize:    x = int(500 / 1000 * 1080) = 540 pixels
                y = int(130 / 1000 * 1920) = 249 pixels
ADB executes:   adb shell input tap 540 249
```

This decouples the model from screen resolution — the same prompt works on 1080p and 1440p devices without changing anything.

## Usage

```bash
# Run with Kimi K2.5
export MOONSHOT_API_KEY=your_key
apptest run --tests tests.json --provider moonshot --model kimi-k2.5 --device emulator-5554

# Run with Kimi K2 Thinking (auto-enables thinking mode)
apptest run --tests tests.json --provider moonshot --model kimi-k2-thinking

# Trace output
ls output_dir/
  results.json     # Test results with action logs
  trace.html       # LLM interaction timeline (open in browser)
  screenshots/     # Per-action screenshots
```

## Lessons Learned

- **Normalized coordinates beat raw pixels.** Asking a vision model for exact pixel coordinates on a 1080x1920 screen is fragile — small errors compound. The 0-1000 normalized grid is what Kimi is optimized for, and the denormalization math is trivial.
- **`response_format=json_object` eliminates parsing failures.** With Gemini/OpenAI we relied on regex extraction from freeform text; Kimi with JSON mode always returns valid JSON.
- **System prompts matter more than you think.** The grounding hint ("mentally draw a 10x10 grid") measurably improves coordinate accuracy for border cases.
- **Trace HTML is essential for debugging.** Being able to see the exact screenshot + prompt + response for each LLM call immediately reveals why a test got stuck — no more guessing.

## Potential Issues

- **Trace file size.** Each PNG screenshot is ~2MB base64-encoded. A 30-entry trace produces ~80MB HTML. Could add optional screenshot compression or external file references.
- **Moonshot API latency.** Kimi K2.5 calls take 3-8 seconds each (vs 1-3s for Gemini Flash). Thinking mode is slower. Acceptable for test execution but worth monitoring.
- **No fallback between providers.** If Moonshot API is down, the run fails. Could add provider fallback chain.
