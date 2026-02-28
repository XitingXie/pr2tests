"""Tests for the step parser module."""

import pytest

from apptest.runner.step_parser import ParsedStep, parse_test_steps


class TestParseTestSteps:
    """Parsing numbered steps from descriptions."""

    def test_basic_numbered_steps(self):
        desc = "1. Open the app\n2. Navigate to Search\n3. Type 'hello'"
        steps = parse_test_steps(desc)
        assert len(steps) == 3
        assert steps[0] == ParsedStep(index=1, text="Open the app", is_verification=False)
        assert steps[1] == ParsedStep(index=2, text="Navigate to Search", is_verification=False)
        assert steps[2] == ParsedStep(index=3, text="Type 'hello'", is_verification=False)

    def test_verification_steps_detected(self):
        desc = (
            "1. Open the app\n"
            "2. Verify the home screen is displayed\n"
            "3. Check that the logo is visible\n"
            "4. Assert search bar exists"
        )
        steps = parse_test_steps(desc)
        assert len(steps) == 4
        assert steps[0].is_verification is False
        assert steps[1].is_verification is True
        assert steps[2].is_verification is True
        assert steps[3].is_verification is True

    def test_confirm_ensure_validate_prefixes(self):
        desc = (
            "1. Confirm the dialog appears\n"
            "2. Ensure the button is enabled\n"
            "3. Validate the input field"
        )
        steps = parse_test_steps(desc)
        assert all(s.is_verification for s in steps)

    def test_expect_should_prefixes(self):
        desc = (
            "1. Expect the list to be populated\n"
            "2. Should see the title"
        )
        steps = parse_test_steps(desc)
        assert all(s.is_verification for s in steps)

    def test_single_step(self):
        desc = "1. Open the app"
        steps = parse_test_steps(desc)
        assert len(steps) == 1
        assert steps[0].text == "Open the app"

    def test_no_numbers_fallback(self):
        desc = "Open the app and navigate to settings"
        steps = parse_test_steps(desc)
        assert len(steps) == 1
        assert steps[0].index == 1
        assert steps[0].text == "Open the app and navigate to settings"
        assert steps[0].is_verification is False

    def test_empty_description(self):
        assert parse_test_steps("") == []
        assert parse_test_steps("   ") == []

    def test_mixed_formatting_with_extra_whitespace(self):
        desc = "  1.  Open the app  \n  2.  Tap on menu  \n  3.  Verify settings page  "
        steps = parse_test_steps(desc)
        assert len(steps) == 3
        assert steps[0].text == "Open the app"
        assert steps[2].is_verification is True

    def test_multiline_with_blank_lines(self):
        desc = "1. Open the app\n\n2. Navigate to Search\n\n3. Type query"
        steps = parse_test_steps(desc)
        assert len(steps) == 3

    def test_steps_preserve_order(self):
        desc = "3. Third step\n1. First step\n2. Second step"
        steps = parse_test_steps(desc)
        # Steps are returned in document order, with original index preserved
        assert steps[0].index == 3
        assert steps[1].index == 1
        assert steps[2].index == 2

    def test_verification_not_case_sensitive(self):
        desc = "1. VERIFY the button\n2. Check the state"
        steps = parse_test_steps(desc)
        assert steps[0].is_verification is True
        assert steps[1].is_verification is True

    def test_non_verification_with_verify_in_middle(self):
        desc = "1. Tap to verify your email"
        steps = parse_test_steps(desc)
        # "verify" is not at the start of the text
        assert steps[0].is_verification is False
