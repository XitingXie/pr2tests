"""Parse natural-language test steps from test descriptions."""

import re
from dataclasses import dataclass

_VERIFICATION_PREFIXES = (
    "verify", "check", "assert", "confirm", "ensure",
    "validate", "expect", "should",
)

# Steps the framework handles automatically — skip if LLM generates them.
_SKIP_KEYWORDS = (
    "fresh install", "install the app", "reinstall",
    "open the app", "launch the app", "start the app",
    "relaunch the app", "reopen the app", "restart the app",
)

_NUMBERED_STEP = re.compile(r"^\s*(\d+)\.\s+(.+)", re.MULTILINE)


@dataclass
class ParsedStep:
    index: int
    text: str
    is_verification: bool


def parse_test_steps(description: str) -> list[ParsedStep]:
    """Split a description on numbered lines into ParsedStep objects.

    Handles formats like:
        1. Open the app
        2. Navigate to Search
        3. Verify results are displayed

    Verification steps are detected by prefix keywords.
    """
    matches = _NUMBERED_STEP.findall(description)

    if not matches:
        # Fallback: treat the whole description as a single action step
        text = description.strip()
        if text:
            return [ParsedStep(index=1, text=text, is_verification=_is_verification(text))]
        return []

    steps: list[ParsedStep] = []
    for idx_str, text in matches:
        text = text.strip()
        if _should_skip(text):
            continue
        steps.append(ParsedStep(
            index=int(idx_str),
            text=text,
            is_verification=_is_verification(text),
        ))
    return steps


def _should_skip(text: str) -> bool:
    """Check if a step should be skipped (handled by the framework)."""
    lower = text.lower()
    return any(kw in lower for kw in _SKIP_KEYWORDS)


def _is_verification(text: str) -> bool:
    """Check if a step is a verification/assertion step."""
    lower = text.lower().lstrip()
    return any(lower.startswith(prefix) for prefix in _VERIFICATION_PREFIXES)
