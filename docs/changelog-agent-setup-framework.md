# Agent-Based Test Setup with LLM-Inferred Routing

## Why

The test framework conflated system-level setup with LLM-driven UI testing. Operations like "fresh install the app" or "set device language to Greek" are deterministic system operations, not UI actions — but they were being handled as text steps or fragile keyword matching in preconditions. This made tests unreliable and limited what setup could be expressed.

## What Changed

### New: `apptest/agents/` Package

- **`base.py`** — `SetupAgent` ABC defining the agent interface: `name`, `actions` dict, `execute()`, and `describe()` for LLM prompt injection.
- **`__init__.py`** — `AgentRegistry` with auto-discovery from three locations (bundled → project → user), `dispatch()` for ordered execution with shared context, and `prompt_description()` for LLM capability injection.
- **`app_agent.py`** — `AppAgent` with `clear_data`, `install`, `uninstall` actions.
- **`build_agent.py`** — `BuildAgent` with `checkout_and_build`, `checkout`, `build` actions. Outputs `apk_path` into shared context.
- **`device_agent.py`** — `DeviceAgent` with `set_locale`, `set_setting` actions.

### Modified: `apptest/runner/adb.py`

- Added `install()`, `uninstall()`, `set_locale()`, `set_setting()` methods for agent use.
- Added `long_press()`, `swipe_left()`, `swipe_right()` for new UI actions.

### Modified: `apptest/runner/schemas.py`

- Added `LONG_PRESS`, `DRAG`, `SWIPE_LEFT`, `SWIPE_RIGHT` to `ActionType` enum.
- Added `x2`, `y2` fields to `Action` dataclass for drag endpoints.

### Modified: `apptest/runner/executor.py`

- `execute_test()` accepts optional `AgentRegistry` and dispatches structured preconditions before launching the app.
- `run_all_tests()` auto-discovers agents and passes registry to each test.
- `_execute_action()` handles `LONG_PRESS`, `DRAG`, `SWIPE_LEFT`, `SWIPE_RIGHT`.

### Modified: `apptest/generator/prompts.py`

- Added `AGENT_CAPABILITIES` template for injecting agent descriptions into the LLM system prompt.
- Updated output format example to show structured preconditions (dicts with `agent`/`action`/`params`).

### Modified: `apptest/generator/test_generator.py`

- `TestCase.preconditions` now accepts both structured dicts and legacy strings.
- `_parse_test_cases()` converts legacy string preconditions to `{"agent": "unknown", "action": "note", "params": {"text": ...}}`.
- `generate_tests()` auto-discovers agents and injects capabilities into the prompt.

### Modified: `apptest/runner/prompts.py`

- Added `long_press`, `drag`, `swipe_left`, `swipe_right` to the available actions list.
- Updated response format to include `x2`/`y2` for drag.

### Modified: `apptest/runner/vision.py`

- Updated action parsing to include `x2`/`y2` fields.
- Updated Kimi action system prompt with new action types.
- Added `coords2` parsing for Kimi's normalized coordinate system.

### Modified: `apptest/runner/console_logger.py`

- Added `log()` method for general setup agent output.

### Modified: Test files

- Updated `test_step_parser.py` and `test_runner.py` to account for "Open the app" being auto-skipped by `_SKIP_KEYWORDS`.

## How It Works

1. **Test generation**: The LLM system prompt includes available agents and their actions. The LLM outputs structured preconditions: `[{"agent": "app", "action": "clear_data"}, ...]`.
2. **Test execution**: The executor dispatches preconditions to agents in order. Agents share a mutable context dict, so BuildAgent can produce `apk_path` and AppAgent reads it.
3. **Extensibility**: Custom agents are auto-discovered from `<project>/.apptest/agents/` or `~/.apptest/agents/` — no framework changes needed.

## Lessons Learned

- Auto-discovery via `importlib.util.spec_from_file_location` breaks relative imports. Bundled agents must be imported via the package (`importlib.import_module`), while external agents use `spec_from_file_location`.
- Existing tests assumed "Open the app" wouldn't be filtered by skip keywords. Tests needed updating after the step_parser changes were already in place.

## Potential Issues

- External agents loaded via `spec_from_file_location` must use absolute imports (`from apptest.agents.base import SetupAgent`) rather than relative imports.
- The `BuildAgent` assumes Gradle conventions for APK output paths — projects with non-standard build configurations may need a custom build agent.

## Further Improvements

- Add a `NetworkAgent` for proxy setup, WiFi toggling (offline mode testing).
- Add agent result validation (e.g., verify APK was actually installed).
- Add dry-run mode for preconditions to validate without executing.
