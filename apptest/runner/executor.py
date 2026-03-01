"""Main test execution loop: ADB + Gemini vision."""

import base64
import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ..agents import AgentRegistry
from ..config import LLMConfig
from .adb import ADBDevice
from .schemas import (
    Action,
    ActionType,
    RunSummary,
    StepResult,
    TestRunResult,
)
from .step_parser import parse_test_steps
from .computer_use import ComputerUseSession, is_computer_use_model
from .console_logger import ConsoleLogger
from .trace import RunTrace, TraceEntry, generate_trace_html
from .vision import decide_action, verify_step

logger = logging.getLogger(__name__)

MAX_ACTIONS_PER_STEP = 15
ACTION_WAIT_SECS = 1.5
VERIFY_WAIT_SECS = 1.0
STUCK_THRESHOLD = 3  # identical screenshots before recovery
VERIFICATION_FALLBACK_MODEL = "kimi-k2.5"

_LAUNCH_KEYWORDS = ("open the app", "launch the app", "start the app")


def execute_test(
    test_case: dict,
    device: ADBDevice,
    config: LLMConfig,
    app_package: str,
    output_dir: Path | None = None,
    trace: RunTrace | None = None,
    console: ConsoleLogger | None = None,
    registry: AgentRegistry | None = None,
    apk_path: str | None = None,
) -> TestRunResult:
    """Execute a single test case on the device.

    Args:
        test_case: Dict with at least "id" and "description" keys.
        device: Connected ADB device.
        config: LLM config for vision calls.
        app_package: Android package name (e.g. "org.wikipedia").
        output_dir: Optional directory to save screenshots.
        trace: Optional RunTrace to collect LLM interaction entries.
        console: Optional ConsoleLogger for real-time output.
        registry: Optional AgentRegistry for dispatching structured preconditions.
        apk_path: Optional path to APK file for install preconditions.

    Returns:
        TestRunResult with per-step details.
    """
    if console is None:
        console = ConsoleLogger(enabled=False)

    test_id = test_case.get("id", "unknown")
    description = test_case.get("description", "")
    logger.info("Running test: %s", test_id)
    console.test_start(test_id)

    start_time = time.monotonic()

    # Framework handles app lifecycle: stop, apply preconditions, launch.
    try:
        device.force_stop(app_package)
    except RuntimeError as e:
        logger.warning("Failed to stop app: %s", e)

    # Dispatch structured preconditions to setup agents
    preconditions = test_case.get("preconditions", [])
    structured = [p for p in preconditions if isinstance(p, dict)]
    legacy = [p for p in preconditions if isinstance(p, str)]

    if structured and registry:
        shared_context = {"app_package": app_package}
        if apk_path:
            shared_context["apk_path"] = apk_path
        setup_log = registry.dispatch(
            structured, device, shared_context,
        )
        for entry in setup_log:
            logger.info("  Setup: %s", entry)
            console.log(entry)

    # Legacy string preconditions: keyword-based clear data
    needs_clear = any(
        kw in p.lower()
        for p in legacy
        for kw in ("fresh", "clean", "clear data", "first launch", "first run")
    )
    if needs_clear:
        logger.info("  Precondition: clearing app data for %s", app_package)
        try:
            device.clear_app_data(app_package)
        except RuntimeError as e:
            logger.warning("Failed to clear app data: %s", e)

    try:
        device.launch_app(app_package)
        time.sleep(ACTION_WAIT_SECS)
    except RuntimeError as e:
        logger.warning("Failed to launch app: %s", e)

    # Parse steps
    parsed_steps = parse_test_steps(description)
    if not parsed_steps:
        return TestRunResult(
            test_id=test_id,
            status="error",
            failure_reason="No steps could be parsed from description",
            total_duration_ms=_elapsed_ms(start_time),
        )

    screen_w, screen_h = device.get_screen_size()

    step_results: list[StepResult] = []
    test_failed = False

    for step in parsed_steps:
        step_start = time.monotonic()
        logger.info("  Step %d: %s", step.index, step.text)
        console.step_start(step.index, step.text, step.is_verification)

        if step.is_verification:
            # Computer use model requires computer_use tool on every call,
            # so verification steps use a regular vision model instead.
            verify_config = config
            if is_computer_use_model(config.model):
                from copy import copy
                verify_config = copy(config)
                verify_config.provider = "moonshot"
                verify_config.model = VERIFICATION_FALLBACK_MODEL
            sr = _run_verification_step(
                step.index, step.text, device, verify_config, output_dir, test_id,
                trace=trace, console=console,
            )
        elif is_computer_use_model(config.model):
            sr = _run_action_step_computer_use(
                step.index, step.text, device, config,
                app_package, screen_w, screen_h, output_dir, test_id,
                trace=trace, console=console,
            )
        else:
            sr = _run_action_step(
                step.index, step.text, device, config,
                app_package, screen_w, screen_h, output_dir, test_id,
                trace=trace, console=console,
            )

        sr.duration_ms = _elapsed_ms(step_start)
        step_results.append(sr)

        if sr.status == "failed":
            test_failed = True
            break

    status = "failed" if test_failed else "passed"
    failure_reason = ""
    if test_failed:
        failed_step = next((s for s in step_results if s.status == "failed"), None)
        if failed_step:
            failure_reason = f"Step {failed_step.step_index}: {failed_step.failure_reason}"

    total_ms = _elapsed_ms(start_time)
    console.test_end(test_id, status, total_ms)

    return TestRunResult(
        test_id=test_id,
        status=status,
        steps=step_results,
        total_duration_ms=total_ms,
        failure_reason=failure_reason,
    )


def _run_action_step(
    step_index: int,
    step_text: str,
    device: ADBDevice,
    config: LLMConfig,
    app_package: str,
    screen_w: int,
    screen_h: int,
    output_dir: Path | None,
    test_id: str,
    trace: RunTrace | None = None,
    console: ConsoleLogger | None = None,
) -> StepResult:
    """Execute an action step by looping: screenshot → LLM → action."""
    if console is None:
        console = ConsoleLogger(enabled=False)

    actions: list[Action] = []

    # Special case: "open the app" / "launch the app"
    if any(kw in step_text.lower() for kw in _LAUNCH_KEYWORDS):
        device.launch_app(app_package)
        console.action_launch(app_package)
        time.sleep(ACTION_WAIT_SECS)
        actions.append(Action(
            action_type=ActionType.LAUNCH,
            reasoning=f"Launched {app_package}",
        ))
        return StepResult(
            step_index=step_index,
            step_text=step_text,
            status="passed",
            actions=actions,
        )

    prev_screenshots: list[bytes] = []
    stuck_count = 0

    for i in range(MAX_ACTIONS_PER_STEP):
        # Take screenshot
        png = device.screenshot_bytes()
        console.screenshot_taken()
        if output_dir:
            _save_screenshot(output_dir, test_id, step_index, i, png)

        # Stuck detection: 3 identical screenshots in a row
        if _is_stuck(png, prev_screenshots):
            stuck_count += 1
            logger.warning("  Stuck detected (count=%d), attempting recovery", stuck_count)

            # Fail fast after 3 stuck recoveries — we're in a loop
            if stuck_count >= 3:
                return StepResult(
                    step_index=step_index,
                    step_text=step_text,
                    status="failed",
                    actions=actions,
                    failure_reason="Stuck in recovery loop after 3 attempts",
                )

            # Check if we're still in the app — if not, relaunch
            fg = device.get_foreground_package()
            if fg and fg != app_package:
                logger.warning("  App not in foreground (%s), relaunching %s", fg, app_package)
                console.stuck_detected(f"app left foreground ({fg}), relaunching")
                device.launch_app(app_package)
                time.sleep(ACTION_WAIT_SECS)
                actions.append(Action(
                    action_type=ActionType.LAUNCH,
                    reasoning=f"Recovery: app left foreground ({fg}), relaunched",
                ))
            elif stuck_count == 1:
                # First stuck: try scrolling instead of back
                console.stuck_detected("scroll to reveal elements")
                device.swipe(screen_w // 2, screen_h * 2 // 3, screen_w // 2, screen_h // 3)
                time.sleep(ACTION_WAIT_SECS)
                actions.append(Action(
                    action_type=ActionType.SWIPE_UP,
                    reasoning="Recovery: stuck detected, trying scroll to reveal elements",
                ))
            else:
                # Second stuck: press back as escalation
                console.stuck_detected("escalated to back")
                device.press_back()
                time.sleep(ACTION_WAIT_SECS)
                actions.append(Action(
                    action_type=ActionType.BACK,
                    reasoning="Recovery: stuck detected (escalated to back)",
                ))
                # Back may have left the app — check and relaunch if needed
                fg = device.get_foreground_package()
                if fg and fg != app_package:
                    logger.warning("  Back left app (%s), relaunching %s", fg, app_package)
                    device.launch_app(app_package)
                    time.sleep(ACTION_WAIT_SECS)
                    actions.append(Action(
                        action_type=ActionType.LAUNCH,
                        reasoning=f"Recovery: back left app ({fg}), relaunched",
                    ))
            prev_screenshots.clear()
            continue

        prev_screenshots.append(png)
        if len(prev_screenshots) > STUCK_THRESHOLD:
            prev_screenshots.pop(0)

        # Gather device context (keyboard state) for the LLM
        device_context = _gather_device_context(device, step_text)

        # Build action history so LLM can avoid repeating failed actions
        if actions:
            recent = actions[-5:]
            history_lines = []
            for a in recent:
                if a.action_type == ActionType.TAP:
                    history_lines.append(f"  - tap at ({a.x},{a.y}): {a.reasoning}")
                elif a.action_type == ActionType.TYPE:
                    history_lines.append(f"  - type '{a.text}': {a.reasoning}")
                elif a.action_type in (ActionType.BACK, ActionType.LAUNCH):
                    history_lines.append(f"  - {a.action_type.value}: {a.reasoning}")
                else:
                    history_lines.append(f"  - {a.action_type.value}: {a.reasoning}")
            device_context += "\nPrevious actions this step:\n" + "\n".join(history_lines)
            device_context += "\nDo NOT repeat the same action if the screen did not change."

        # Ask LLM what to do — capture trace
        capture: list[dict] | None = [] if trace is not None else None
        call_start = time.monotonic()
        try:
            action = decide_action(
                png, step_text, screen_w, screen_h, len(actions), config,
                device_context=device_context,
                trace_entries=capture,
            )
        except Exception as e:
            logger.error("  Vision call failed: %s", e)
            return StepResult(
                step_index=step_index,
                step_text=step_text,
                status="failed",
                actions=actions,
                failure_reason=f"Vision call failed: {e}",
            )
        call_duration = _elapsed_ms(call_start)

        if trace is not None and capture:
            trace.add(TraceEntry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                call_type="action",
                test_id=test_id,
                step_index=step_index,
                step_text=step_text,
                prompt=capture[0]["prompt"],
                screenshot_b64=base64.b64encode(png).decode("ascii"),
                raw_response=capture[0]["raw_response"],
                parsed_result=f"{action.action_type.value}: {action.reasoning}",
                device_context=device_context,
                duration_ms=call_duration,
                model=config.model,
                provider=config.provider,
            ))

        actions.append(action)

        if action.action_type == ActionType.DONE:
            return StepResult(
                step_index=step_index,
                step_text=step_text,
                status="passed",
                actions=actions,
            )

        # Execute the action on device
        _execute_action(device, action, app_package)
        console.action_executed(
            action.action_type.value, x=action.x, y=action.y, text=action.text,
        )
        time.sleep(ACTION_WAIT_SECS)

        # Guard: if back/other action navigated us out of the app, relaunch
        if action.action_type in (ActionType.BACK, ActionType.HOME):
            fg = device.get_foreground_package()
            if fg and fg != app_package:
                logger.warning("  Left app after %s, relaunching", action.action_type.value)
                device.launch_app(app_package)
                time.sleep(ACTION_WAIT_SECS)
                actions.append(Action(
                    action_type=ActionType.LAUNCH,
                    reasoning=f"Auto-relaunch: {action.action_type.value} left app",
                ))

    # Exhausted max actions
    return StepResult(
        step_index=step_index,
        step_text=step_text,
        status="failed",
        actions=actions,
        failure_reason=f"Max actions ({MAX_ACTIONS_PER_STEP}) reached without completing step",
    )


def _run_action_step_computer_use(
    step_index: int,
    step_text: str,
    device: ADBDevice,
    config: LLMConfig,
    app_package: str,
    screen_w: int,
    screen_h: int,
    output_dir: Path | None,
    test_id: str,
    trace: RunTrace | None = None,
    console: ConsoleLogger | None = None,
) -> StepResult:
    """Execute an action step using Gemini computer use (structured tool calls)."""
    if console is None:
        console = ConsoleLogger(enabled=False)

    actions: list[Action] = []

    # Special case: "open the app" / "launch the app"
    if any(kw in step_text.lower() for kw in _LAUNCH_KEYWORDS):
        device.launch_app(app_package)
        console.action_launch(app_package)
        time.sleep(ACTION_WAIT_SECS)
        actions.append(Action(
            action_type=ActionType.LAUNCH,
            reasoning=f"Launched {app_package}",
        ))
        return StepResult(
            step_index=step_index,
            step_text=step_text,
            status="passed",
            actions=actions,
        )

    try:
        session = ComputerUseSession(step_text, screen_w, screen_h, config)
    except Exception as e:
        logger.error("  Failed to create computer use session: %s", e)
        return StepResult(
            step_index=step_index,
            step_text=step_text,
            status="failed",
            actions=actions,
            failure_reason=f"Failed to create computer use session: {e}",
        )

    # Initial screenshot
    png = device.screenshot_bytes()
    console.screenshot_taken()
    screenshot_counter = 0
    if output_dir:
        _save_screenshot(output_dir, test_id, step_index, screenshot_counter, png)
        screenshot_counter += 1

    prev_fn_names: list[str] | None = None

    for i in range(MAX_ACTIONS_PER_STEP):
        capture: list[dict] | None = [] if trace is not None else None
        call_start = time.monotonic()
        try:
            action_list, fn_names = session.get_action(
                png, prev_fn_names, trace_entries=capture,
            )
        except Exception as e:
            logger.error("  Computer use call failed: %s", e)
            return StepResult(
                step_index=step_index,
                step_text=step_text,
                status="failed",
                actions=actions,
                failure_reason=f"Computer use call failed: {e}",
            )
        call_duration = _elapsed_ms(call_start)

        if trace is not None and capture:
            parsed_summary = ", ".join(
                f"{a.action_type.value}: {a.reasoning}" for a in action_list
            )
            trace.add(TraceEntry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                call_type="computer_use",
                test_id=test_id,
                step_index=step_index,
                step_text=step_text,
                prompt=capture[0]["prompt"],
                screenshot_b64=base64.b64encode(png).decode("ascii"),
                raw_response=capture[0]["raw_response"],
                parsed_result=parsed_summary,
                device_context="",
                duration_ms=call_duration,
                model=config.model,
                provider=config.provider,
            ))

        # Execute all actions from this model response
        step_done = False
        for action in action_list:
            actions.append(action)

            if action.action_type == ActionType.DONE:
                step_done = True
                break

            _execute_action(device, action, app_package)
            console.action_executed(
                action.action_type.value, x=action.x, y=action.y, text=action.text,
            )
            time.sleep(0.5)

        if step_done:
            return StepResult(
                step_index=step_index,
                step_text=step_text,
                status="passed",
                actions=actions,
            )

        if not fn_names:
            break

        # Wait and take new screenshot after executing all sub-actions
        time.sleep(ACTION_WAIT_SECS)
        png = device.screenshot_bytes()
        console.screenshot_taken()
        if output_dir:
            _save_screenshot(output_dir, test_id, step_index, screenshot_counter, png)
            screenshot_counter += 1

        # Foreground guard after back/home
        last_action = actions[-1] if actions else None
        if last_action and last_action.action_type in (ActionType.BACK, ActionType.HOME):
            fg = device.get_foreground_package()
            if fg and fg != app_package:
                logger.warning("  Left app after %s, relaunching", last_action.action_type.value)
                device.launch_app(app_package)
                time.sleep(ACTION_WAIT_SECS)
                png = device.screenshot_bytes()
                if output_dir:
                    _save_screenshot(output_dir, test_id, step_index, screenshot_counter, png)
                    screenshot_counter += 1
                actions.append(Action(
                    action_type=ActionType.LAUNCH,
                    reasoning=f"Auto-relaunch: {last_action.action_type.value} left app",
                ))

        prev_fn_names = fn_names

    # Exhausted max actions
    return StepResult(
        step_index=step_index,
        step_text=step_text,
        status="failed",
        actions=actions,
        failure_reason=f"Max actions ({MAX_ACTIONS_PER_STEP}) reached without completing step",
    )


def _gather_device_context(device: ADBDevice, step_text: str) -> str:
    """Collect relevant device state for both action and verification steps.

    Always checks keyboard state because screenshots may not capture
    the software keyboard layer (especially after ``adb input text``).
    """
    parts = []

    try:
        kb_shown = device.is_keyboard_shown()
        parts.append(f"Soft keyboard shown: {kb_shown}")
    except Exception:
        pass

    return "; ".join(parts)


def _run_verification_step(
    step_index: int,
    step_text: str,
    device: ADBDevice,
    config: LLMConfig,
    output_dir: Path | None,
    test_id: str,
    trace: RunTrace | None = None,
    console: ConsoleLogger | None = None,
) -> StepResult:
    """Execute a verification step: screenshot → LLM assertion."""
    if console is None:
        console = ConsoleLogger(enabled=False)

    time.sleep(VERIFY_WAIT_SECS)
    png = device.screenshot_bytes()
    console.screenshot_taken()
    if output_dir:
        _save_screenshot(output_dir, test_id, step_index, 0, png)

    # Gather device context for assertions that depend on system state
    # (e.g., keyboard visibility) which may not be captured in screenshots.
    device_context = _gather_device_context(device, step_text)

    capture: list[dict] | None = [] if trace is not None else None
    call_start = time.monotonic()
    try:
        passed, confidence, reasoning = verify_step(
            png, step_text, config, device_context=device_context,
            trace_entries=capture,
        )
    except Exception as e:
        logger.error("  Verification call failed: %s", e)
        return StepResult(
            step_index=step_index,
            step_text=step_text,
            status="failed",
            failure_reason=f"Verification call failed: {e}",
        )
    call_duration = _elapsed_ms(call_start)

    if trace is not None and capture:
        result_str = "PASS" if passed else "FAIL"
        trace.add(TraceEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            call_type="verification",
            test_id=test_id,
            step_index=step_index,
            step_text=step_text,
            prompt=capture[0]["prompt"],
            screenshot_b64=base64.b64encode(png).decode("ascii"),
            raw_response=capture[0]["raw_response"],
            parsed_result=f"{result_str} [{confidence}]: {reasoning}",
            device_context=device_context,
            duration_ms=call_duration,
            model=config.model,
            provider=config.provider,
        ))

    action_type = ActionType.ASSERT_PASS if passed else ActionType.ASSERT_FAIL
    actions = [Action(
        action_type=action_type,
        reasoning=f"[{confidence}] {reasoning}",
    )]

    return StepResult(
        step_index=step_index,
        step_text=step_text,
        status="passed" if passed else "failed",
        actions=actions,
        failure_reason="" if passed else reasoning,
    )


def _execute_action(device: ADBDevice, action: Action, app_package: str) -> None:
    """Dispatch an Action to the appropriate ADB call.

    For tap actions, checks whether the software keyboard is covering the
    target coordinates.  If so, the keyboard is dismissed first and the tap
    proceeds after a short delay so the layout can settle.
    """
    t = action.action_type
    if t == ActionType.TAP:
        # Keyboard-aware tapping: if the keyboard covers the target, dismiss
        # it first so the tap hits the intended element, not the keyboard.
        try:
            if device.is_keyboard_shown():
                _, screen_h = device.get_screen_size()
                keyboard_top = int(screen_h * 0.55)
                if action.y > keyboard_top:
                    logger.debug(
                        "  Tap y=%d behind keyboard (top≈%d), dismissing keyboard first",
                        action.y, keyboard_top,
                    )
                    device.press_back()
                    time.sleep(0.5)
        except Exception:
            pass  # best-effort; proceed with tap
        device.tap(action.x, action.y)
    elif t == ActionType.TYPE:
        device.type_text(action.text)
    elif t == ActionType.SWIPE_UP:
        device.swipe_up()
    elif t == ActionType.SWIPE_DOWN:
        device.swipe_down()
    elif t == ActionType.SWIPE_LEFT:
        device.swipe_left()
    elif t == ActionType.SWIPE_RIGHT:
        device.swipe_right()
    elif t == ActionType.LONG_PRESS:
        device.long_press(action.x, action.y)
    elif t == ActionType.DRAG:
        device.swipe(action.x, action.y, action.x2, action.y2, duration_ms=500)
    elif t == ActionType.BACK:
        device.press_back()
    elif t == ActionType.HOME:
        device.press_home()
    elif t == ActionType.ENTER:
        device.press_enter()
    elif t == ActionType.LAUNCH:
        device.launch_app(app_package)
    elif t == ActionType.WAIT:
        time.sleep(1.0)
    # DONE, ASSERT_PASS, ASSERT_FAIL are not device actions


def _is_stuck(current: bytes, previous: list[bytes]) -> bool:
    """Return True if the last STUCK_THRESHOLD screenshots are identical."""
    if len(previous) < STUCK_THRESHOLD - 1:
        return False
    return all(s == current for s in previous[-(STUCK_THRESHOLD - 1):])


def _save_screenshot(
    output_dir: Path, test_id: str, step: int, action: int, png: bytes,
) -> None:
    """Save a screenshot to the output directory."""
    screenshots_dir = output_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    path = screenshots_dir / f"{test_id}_step{step}_action{action}.png"
    path.write_bytes(png)


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_all_tests(
    tests_path: str | Path,
    config: LLMConfig,
    app_package: str,
    device_serial: str = "emulator-5554",
    output_dir: str | Path | None = None,
    apk_path: str | None = None,
    clear_data: bool = False,
    verbose: bool = False,
) -> RunSummary:
    """Run all tests from a tests.json file.

    Args:
        tests_path: Path to tests.json (GenerationResult format).
        config: LLM config for vision calls.
        app_package: Android package name.
        device_serial: ADB device serial.
        output_dir: Optional directory for results and screenshots.
        clear_data: If True, clear app data once before all tests.
            Useful for a clean first run, but means the first test
            must navigate through any onboarding flow.
        verbose: If True, print real-time events to the console.

    Returns:
        RunSummary with all test results.
    """
    tests_path = Path(tests_path)
    with open(tests_path) as f:
        data = json.load(f)

    test_cases = data.get("tests", [])
    if not test_cases:
        raise ValueError(f"No tests found in {tests_path}")

    device = ADBDevice(serial=device_serial)
    device.wait_for_device()

    # Wake screen and dismiss lock screen (real devices may sleep)
    device.wake_and_unlock()

    # Ensure on-screen keyboard appears on emulators (hardware keyboard
    # makes Android hide the software keyboard by default).
    try:
        device.ensure_keyboard_visible()
    except RuntimeError as e:
        logger.warning("Failed to enable on-screen keyboard: %s", e)

    # Optional one-time data reset before the run
    if clear_data:
        logger.info("Clearing app data for %s", app_package)
        try:
            device.force_stop(app_package)
            device.clear_app_data(app_package)
        except RuntimeError as e:
            logger.warning("Failed to clear app data: %s", e)

    out_path = Path(output_dir) if output_dir else None
    started_at = datetime.now(timezone.utc).isoformat()

    console = ConsoleLogger(enabled=verbose)
    trace = RunTrace(on_add=console.on_trace_entry)

    # Extract PR metadata from tests.json for verbose header
    pr_number = data.get("pr_number")
    pr_title = data.get("pr_title")
    console.run_start(
        pr_number=pr_number,
        pr_title=pr_title,
        model=config.model,
        provider=config.provider,
        device_serial=device_serial,
        test_count=len(test_cases),
        app_package=app_package,
    )

    # Auto-discover setup agents from bundled + project + user directories
    registry = AgentRegistry.auto_discover(project_path=Path.cwd())

    results: list[TestRunResult] = []
    for tc in test_cases:
        result = execute_test(
            tc, device, config, app_package, out_path,
            trace=trace, console=console, registry=registry,
            apk_path=apk_path,
        )
        results.append(result)
        logger.info("  %s: %s", result.test_id, result.status)

    completed_at = datetime.now(timezone.utc).isoformat()

    summary = RunSummary(
        started_at=started_at,
        completed_at=completed_at,
        device_serial=device_serial,
        app_package=app_package,
        total_tests=len(results),
        passed=sum(1 for r in results if r.status == "passed"),
        failed=sum(1 for r in results if r.status == "failed"),
        skipped=sum(1 for r in results if r.status == "skipped"),
        errored=sum(1 for r in results if r.status == "error"),
        results=results,
    )

    # Write results.json if output dir specified
    if out_path:
        out_path.mkdir(parents=True, exist_ok=True)
        results_file = out_path / "results.json"
        with open(results_file, "w") as f:
            json.dump(asdict(summary), f, indent=2)
        logger.info("Results written to %s", results_file)

        # Write trace.html alongside results.json
        if trace.entries:
            trace_file = out_path / "trace.html"
            generate_trace_html(trace, str(trace_file))
            logger.info("Trace written to %s (%d entries)", trace_file, len(trace.entries))

    return summary
