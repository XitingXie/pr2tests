"""Gemini Computer Use integration for Android testing.

Uses the computer_use tool in the Gemini API for structured UI actions
with normalized coordinates (0-1000 grid), providing better coordinate
accuracy than free-form JSON prompting.
"""

import logging
import os

from ..config import LLMConfig
from .schemas import Action, ActionType

logger = logging.getLogger(__name__)

# Models that support the computer_use tool
COMPUTER_USE_MODELS = {
    "gemini-2.5-computer-use-preview-10-2025",
}

# Browser-specific functions to exclude for Android testing
_EXCLUDED_FUNCTIONS = [
    "open_web_browser",
    "navigate",
    "search",
    "go_forward",
]

_INITIAL_PROMPT = """\
You are testing an Android mobile app. Perform the following step:

{step_text}

The screen resolution is {width}x{height} pixels. This is an Android device, not a web browser.
- Tap buttons and UI elements to interact with the app.
- If you see a setup wizard, onboarding, or welcome screen, tap "Skip" or "Get started" to dismiss it.
- When typing text into a field, do NOT press Enter/Return unless the step explicitly asks you to submit or press Enter. On Android, pressing Enter often dismisses the keyboard or navigates away.
- When the step is fully complete, stop and do not return any more function calls.\
"""


def is_computer_use_model(model: str) -> bool:
    """Check if a model supports the computer_use tool."""
    return model in COMPUTER_USE_MODELS


class ComputerUseSession:
    """Maintains multi-turn conversation state for Gemini computer use API.

    The computer use model operates in a loop:
    1. User sends task + screenshot
    2. Model returns function_call(s) (click_at, type_text_at, etc.)
    3. User executes action, sends function_response with new screenshot
    4. Repeat until model returns no function calls (step complete)

    Coordinates are normalized to a 0-1000 grid and denormalized to actual
    screen dimensions before returning.
    """

    def __init__(
        self,
        step_text: str,
        screen_width: int,
        screen_height: int,
        config: LLMConfig,
    ):
        self.step_text = step_text
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.config = config
        self.contents: list = []

        api_key = config.api_key or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")

        from .vision import _get_client
        self._client = _get_client(api_key)

        from google.genai import types
        self._types = types

        self._gen_config = types.GenerateContentConfig(
            tools=[
                types.Tool(
                    computer_use=types.ComputerUse(
                        environment=types.Environment.ENVIRONMENT_UNSPECIFIED,
                        excluded_predefined_functions=_EXCLUDED_FUNCTIONS,
                    )
                )
            ],
            temperature=0.1,
        )

    def get_action(
        self,
        screenshot_png: bytes,
        prev_function_names: list[str] | None = None,
        trace_entries: list | None = None,
    ) -> tuple[list[Action], list[str]]:
        """Get next action(s) from the computer use model.

        Args:
            screenshot_png: Current device screenshot (PNG bytes).
            prev_function_names: Raw function names from previous call's response.
                None for the first call in a step.
            trace_entries: Optional list to append {"prompt", "raw_response"} dicts.

        Returns:
            (actions, function_names):
                actions: List of Actions to execute on the device.
                function_names: Raw function names from the model response,
                    needed for the next call's function responses.
                    Empty list means the step is complete.
        """
        types = self._types

        prompt_text = ""
        if prev_function_names is None:
            # First call: send task description + screenshot
            prompt_text = _INITIAL_PROMPT.format(
                step_text=self.step_text,
                width=self.screen_width,
                height=self.screen_height,
            )
            self.contents.append(types.Content(
                role="user",
                parts=[
                    types.Part(text=prompt_text),
                    types.Part.from_bytes(
                        data=screenshot_png, mime_type="image/png",
                    ),
                ],
            ))
        else:
            # Subsequent calls: send function response(s) with new screenshot
            prompt_text = f"[function_response for: {', '.join(prev_function_names)}]"
            parts = []
            for fn_name in prev_function_names:
                parts.append(types.Part(
                    function_response=types.FunctionResponse(
                        name=fn_name,
                        response={"result": "success", "url": "android://device"},
                        parts=[
                            types.FunctionResponsePart(
                                inline_data=types.FunctionResponseBlob(
                                    data=screenshot_png,
                                    mime_type="image/png",
                                )
                            )
                        ],
                    )
                ))
            self.contents.append(types.Content(role="user", parts=parts))

        # Call the model
        response = self._client.models.generate_content(
            model=self.config.model,
            contents=self.contents,
            config=self._gen_config,
        )

        candidate = response.candidates[0]
        self.contents.append(candidate.content)

        # Build raw response text for tracing
        raw_response_parts = []
        parts = candidate.content.parts or []
        for part in parts:
            if part.function_call:
                fc = part.function_call
                raw_response_parts.append(f"function_call: {fc.name}({fc.args})")
            elif hasattr(part, "text") and part.text:
                raw_response_parts.append(part.text)
        raw_response = "\n".join(raw_response_parts)

        if trace_entries is not None:
            trace_entries.append({"prompt": prompt_text, "raw_response": raw_response})

        # Parse function calls from response
        actions: list[Action] = []
        function_names: list[str] = []
        for part in parts:
            if part.function_call:
                fc = part.function_call
                parsed = self._parse_function_call(fc)
                actions.extend(parsed)
                function_names.append(fc.name)

        if not function_names:
            # No function calls = step is complete
            text = ""
            for part in parts:
                if hasattr(part, 'text') and part.text:
                    text = part.text
                    break
            reasoning = f"Computer use: step complete. {text[:100]}" if text else "Computer use: step complete"
            actions = [Action(action_type=ActionType.DONE, reasoning=reasoning)]

        return actions, function_names

    def _parse_function_call(self, fc) -> list[Action]:
        """Convert a Gemini computer use function_call to Action(s).

        Some functions (e.g. type_text_at) decompose into multiple
        sequential Actions (tap to focus, then type).
        """
        name = fc.name
        args = fc.args or {}

        if name == "click_at":
            x = self._denorm_x(args.get("x", 0))
            y = self._denorm_y(args.get("y", 0))
            return [Action(
                action_type=ActionType.TAP,
                x=x, y=y,
                reasoning=f"Computer use: click at ({x}, {y})",
            )]

        elif name == "type_text_at":
            x = self._denorm_x(args.get("x", 0))
            y = self._denorm_y(args.get("y", 0))
            text = str(args.get("text", ""))
            result = []
            # Tap to focus the field (opens keyboard)
            result.append(Action(
                action_type=ActionType.TAP,
                x=x, y=y,
                reasoning=f"Computer use: focus field at ({x}, {y})",
            ))
            # Type the text via ADB
            result.append(Action(
                action_type=ActionType.TYPE,
                text=text,
                reasoning=f"Computer use: type '{text}'",
            ))
            return result

        elif name == "go_back":
            return [Action(
                action_type=ActionType.BACK,
                reasoning="Computer use: go back",
            )]

        elif name in ("scroll_document", "scroll_at"):
            direction = str(args.get("direction", "down")).lower()
            if direction == "up":
                at = ActionType.SWIPE_UP
            else:
                at = ActionType.SWIPE_DOWN
            return [Action(action_type=at, reasoning=f"Computer use: scroll {direction}")]

        elif name == "key_combination":
            keys = str(args.get("keys", ""))
            if "enter" in keys.lower() or "return" in keys.lower():
                return [Action(
                    action_type=ActionType.ENTER,
                    reasoning=f"Computer use: key combo {keys}",
                )]
            return [Action(
                action_type=ActionType.WAIT,
                reasoning=f"Computer use: unmapped key combo '{keys}'",
            )]

        elif name == "wait_5_seconds":
            return [Action(
                action_type=ActionType.WAIT,
                reasoning="Computer use: wait 5s",
            )]

        elif name == "hover_at":
            x = self._denorm_x(args.get("x", 0))
            y = self._denorm_y(args.get("y", 0))
            return [Action(
                action_type=ActionType.TAP,
                x=x, y=y,
                reasoning=f"Computer use: hover→tap at ({x}, {y})",
            )]

        else:
            logger.warning("Unknown computer use function: %s", name)
            return [Action(
                action_type=ActionType.WAIT,
                reasoning=f"Computer use: unknown function '{name}'",
            )]

    def _denorm_x(self, x) -> int:
        """Denormalize x coordinate from 0-1000 grid to screen pixels."""
        return int(int(x) / 1000 * self.screen_width)

    def _denorm_y(self, y) -> int:
        """Denormalize y coordinate from 0-1000 grid to screen pixels."""
        return int(int(y) / 1000 * self.screen_height)
