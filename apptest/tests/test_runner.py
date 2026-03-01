"""Tests for the runner module (vision parsing, executor, schemas)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from apptest.config import LLMConfig
from apptest.runner.schemas import (
    Action,
    ActionType,
    RunSummary,
    StepResult,
    TestRunResult,
    to_execution_results,
)
from apptest.runner.vision import _parse_json


# ---------------------------------------------------------------------------
# _parse_json tests
# ---------------------------------------------------------------------------


class TestParseJson:
    """JSON parsing from vision LLM responses."""

    def test_clean_json(self):
        raw = '{"action": "tap", "x": 100, "y": 200, "reasoning": "tap button"}'
        data = _parse_json(raw)
        assert data["action"] == "tap"
        assert data["x"] == 100
        assert data["y"] == 200

    def test_json_with_fences(self):
        raw = '```json\n{"action": "swipe_up", "reasoning": "scroll down"}\n```'
        data = _parse_json(raw)
        assert data["action"] == "swipe_up"

    def test_json_with_surrounding_text(self):
        raw = 'Here is the action:\n{"action": "back", "reasoning": "go back"}\nDone.'
        data = _parse_json(raw)
        assert data["action"] == "back"

    def test_malformed_json_returns_empty(self):
        data = _parse_json("not json at all")
        assert data == {}

    def test_json_array_extracts_inner_object(self):
        # _parse_json finds the first { } pair, so it extracts from arrays too
        data = _parse_json('[{"action": "tap"}]')
        assert data["action"] == "tap"

    def test_verification_response(self):
        raw = '{"passed": true, "confidence": "high", "reasoning": "element visible"}'
        data = _parse_json(raw)
        assert data["passed"] is True
        assert data["confidence"] == "high"

    def test_verification_failed(self):
        raw = '{"passed": false, "confidence": "medium", "reasoning": "not found"}'
        data = _parse_json(raw)
        assert data["passed"] is False


# ---------------------------------------------------------------------------
# Action / decide_action tests
# ---------------------------------------------------------------------------


class TestDecideAction:
    """Mocked decide_action calls."""

    @patch("apptest.runner.vision._call_vision")
    def test_tap_action(self, mock_vision):
        from apptest.runner.vision import decide_action

        mock_vision.return_value = '{"action": "tap", "x": 540, "y": 1200, "reasoning": "tap search"}'
        config = LLMConfig(provider="google", model="gemini-2.0-flash", api_key="fake")

        action = decide_action(b"fake_png", "Tap search", 1080, 2400, 0, config)
        assert action.action_type == ActionType.TAP
        assert action.x == 540
        assert action.y == 1200

    @patch("apptest.runner.vision._call_vision")
    def test_type_action(self, mock_vision):
        from apptest.runner.vision import decide_action

        mock_vision.return_value = '{"action": "type", "text": "hello world", "reasoning": "type query"}'
        config = LLMConfig(provider="google", model="gemini-2.0-flash", api_key="fake")

        action = decide_action(b"fake_png", "Type hello", 1080, 2400, 0, config)
        assert action.action_type == ActionType.TYPE
        assert action.text == "hello world"

    @patch("apptest.runner.vision._call_vision")
    def test_done_action(self, mock_vision):
        from apptest.runner.vision import decide_action

        mock_vision.return_value = '{"action": "done", "reasoning": "step complete"}'
        config = LLMConfig(provider="google", model="gemini-2.0-flash", api_key="fake")

        action = decide_action(b"fake_png", "Already done", 1080, 2400, 0, config)
        assert action.action_type == ActionType.DONE

    @patch("apptest.runner.vision._call_vision")
    def test_unknown_action_defaults_to_wait(self, mock_vision):
        from apptest.runner.vision import decide_action

        mock_vision.return_value = '{"action": "unknown_action", "reasoning": "?"}'
        config = LLMConfig(provider="google", model="gemini-2.0-flash", api_key="fake")

        action = decide_action(b"fake_png", "Do something", 1080, 2400, 0, config)
        assert action.action_type == ActionType.WAIT


# ---------------------------------------------------------------------------
# verify_step tests
# ---------------------------------------------------------------------------


class TestVerifyStep:
    """Mocked verify_step calls."""

    @patch("apptest.runner.vision._call_vision")
    def test_passed(self, mock_vision):
        from apptest.runner.vision import verify_step

        mock_vision.return_value = '{"passed": true, "confidence": "high", "reasoning": "visible"}'
        config = LLMConfig(provider="google", model="gemini-2.0-flash", api_key="fake")

        passed, confidence, reasoning = verify_step(b"fake_png", "Check button", config)
        assert passed is True
        assert confidence == "high"

    @patch("apptest.runner.vision._call_vision")
    def test_failed(self, mock_vision):
        from apptest.runner.vision import verify_step

        mock_vision.return_value = '{"passed": false, "confidence": "medium", "reasoning": "not found"}'
        config = LLMConfig(provider="google", model="gemini-2.0-flash", api_key="fake")

        passed, confidence, reasoning = verify_step(b"fake_png", "Check missing", config)
        assert passed is False
        assert confidence == "medium"

    @patch("apptest.runner.vision._call_vision")
    def test_malformed_response_defaults_to_fail(self, mock_vision):
        from apptest.runner.vision import verify_step

        mock_vision.return_value = "not json"
        config = LLMConfig(provider="google", model="gemini-2.0-flash", api_key="fake")

        passed, confidence, reasoning = verify_step(b"fake_png", "Check something", config)
        assert passed is False
        assert confidence == "low"


# ---------------------------------------------------------------------------
# Launch step detection
# ---------------------------------------------------------------------------


class TestLaunchDetection:
    """Test detection of launch-the-app steps in executor."""

    def test_launch_keywords(self):
        from apptest.runner.executor import _LAUNCH_KEYWORDS

        assert "open the app" in _LAUNCH_KEYWORDS
        assert "launch the app" in _LAUNCH_KEYWORDS
        assert "start the app" in _LAUNCH_KEYWORDS

    def test_launch_detected_in_step(self):
        text = "Open the app"
        from apptest.runner.executor import _LAUNCH_KEYWORDS

        assert any(kw in text.lower() for kw in _LAUNCH_KEYWORDS)

    def test_non_launch_step(self):
        text = "Tap the search button"
        from apptest.runner.executor import _LAUNCH_KEYWORDS

        assert not any(kw in text.lower() for kw in _LAUNCH_KEYWORDS)


# ---------------------------------------------------------------------------
# execute_test with mocked ADB + vision
# ---------------------------------------------------------------------------


class TestExecuteTest:
    """End-to-end executor with mocked dependencies."""

    @patch("apptest.runner.executor.verify_step")
    @patch("apptest.runner.executor.decide_action")
    def test_full_test_pass(self, mock_decide, mock_verify):
        from apptest.runner.executor import execute_test

        # "Open the app" is now auto-skipped by step_parser,
        # so only 2 steps remain: tap + verify
        mock_decide.return_value = Action(
            action_type=ActionType.DONE, reasoning="step complete",
        )
        mock_verify.return_value = (True, "high", "verified")

        device = MagicMock()
        device.get_screen_size.return_value = (1080, 2400)
        device.screenshot_bytes.return_value = b"fake_png"

        test_case = {
            "id": "test_001",
            "description": (
                "1. Open the app\n"
                "2. Tap the search button\n"
                "3. Verify search page is displayed"
            ),
        }
        config = LLMConfig(provider="google", model="gemini-2.0-flash", api_key="fake")
        result = execute_test(test_case, device, config, "org.wikipedia")

        assert result.test_id == "test_001"
        assert result.status == "passed"
        assert len(result.steps) == 2
        # Framework launches app automatically (not via step)
        device.launch_app.assert_called_once_with("org.wikipedia")

    @patch("apptest.runner.executor.verify_step")
    @patch("apptest.runner.executor.decide_action")
    def test_verification_failure_stops_test(self, mock_decide, mock_verify):
        from apptest.runner.executor import execute_test

        mock_decide.return_value = Action(
            action_type=ActionType.DONE, reasoning="step complete",
        )
        mock_verify.return_value = (False, "high", "button not found")

        device = MagicMock()
        device.get_screen_size.return_value = (1080, 2400)
        device.screenshot_bytes.return_value = b"fake_png"

        test_case = {
            "id": "test_002",
            "description": (
                "1. Open the app\n"
                "2. Verify missing element is displayed\n"
                "3. Tap something else"
            ),
        }
        config = LLMConfig(provider="google", model="gemini-2.0-flash", api_key="fake")
        result = execute_test(test_case, device, config, "org.wikipedia")

        assert result.status == "failed"
        # "Open the app" is skipped, so only verify step runs (and fails)
        assert len(result.steps) == 1
        assert "button not found" in result.failure_reason


# ---------------------------------------------------------------------------
# to_execution_results conversion
# ---------------------------------------------------------------------------


class TestToExecutionResults:
    """Conversion from RunSummary to TestExecutionResult list."""

    def test_basic_conversion(self):
        summary = RunSummary(
            started_at="2026-01-01T00:00:00Z",
            completed_at="2026-01-01T00:01:00Z",
            device_serial="emulator-5554",
            app_package="org.wikipedia",
            total_tests=2,
            passed=1,
            failed=1,
            skipped=0,
            errored=0,
            results=[
                TestRunResult(
                    test_id="test_001",
                    status="passed",
                    steps=[
                        StepResult(step_index=1, step_text="Open app", status="passed"),
                        StepResult(step_index=2, step_text="Verify", status="passed"),
                    ],
                    total_duration_ms=5000,
                ),
                TestRunResult(
                    test_id="test_002",
                    status="failed",
                    steps=[
                        StepResult(step_index=1, step_text="Open app", status="passed"),
                        StepResult(step_index=2, step_text="Verify", status="failed"),
                    ],
                    total_duration_ms=3000,
                    failure_reason="Step 2: element not found",
                ),
            ],
        )

        results = to_execution_results(summary)
        assert len(results) == 2

        assert results[0].test_id == "test_001"
        assert results[0].status == "passed"
        assert results[0].duration_ms == 5000
        assert results[0].steps_completed == 2
        assert results[0].steps_total == 2

        assert results[1].test_id == "test_002"
        assert results[1].status == "failed"
        assert results[1].steps_completed == 1
        assert results[1].steps_total == 2
        assert results[1].failure_reason == "Step 2: element not found"

    def test_empty_summary(self):
        summary = RunSummary(
            started_at="", completed_at="", device_serial="", app_package="",
            total_tests=0, passed=0, failed=0, skipped=0, errored=0,
        )
        assert to_execution_results(summary) == []
