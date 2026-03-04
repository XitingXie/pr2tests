"""Vision integration for screenshot analysis (Gemini, OpenAI, Anthropic Claude, Moonshot Kimi)."""

import base64
import json
import logging
import os
import re

from ..config import LLMConfig
from ..llm_retry import retry_llm_call
from .prompts import (
    ACTION_PROMPT,
    GROUNDING_PROMPT,
    REASONING_PROMPT,
    VERIFICATION_PROMPT,
)
from .schemas import Action, ActionType

logger = logging.getLogger(__name__)

# Cached clients keyed by (provider, api_key).
_client_cache: dict[str, object] = {}

_OPENAI_PROVIDERS = ("openai",)
_GOOGLE_PROVIDERS = ("google", "gemini")
_ANTHROPIC_PROVIDERS = ("anthropic", "claude")
_MOONSHOT_PROVIDERS = ("moonshot", "kimi")

_MOONSHOT_BASE_URL = "https://api.moonshot.ai/v1"

# Actions that require coordinate grounding (Stage 2 of hybrid pipeline).
_COORD_ACTIONS = {"tap", "long_press", "drag"}


def _get_client(api_key: str, provider: str = "google"):
    """Return a cached client for the given provider and API key."""
    cache_key = f"{provider}:{api_key}"
    if cache_key not in _client_cache:
        if provider in _MOONSHOT_PROVIDERS:
            from openai import OpenAI
            _client_cache[cache_key] = OpenAI(
                api_key=api_key, base_url=_MOONSHOT_BASE_URL,
            )
        elif provider in _OPENAI_PROVIDERS:
            from openai import OpenAI
            _client_cache[cache_key] = OpenAI(api_key=api_key)
        elif provider in _ANTHROPIC_PROVIDERS:
            import anthropic
            _client_cache[cache_key] = anthropic.Anthropic(api_key=api_key)
        else:
            from google import genai
            _client_cache[cache_key] = genai.Client(api_key=api_key)
    return _client_cache[cache_key]


def decide_action(
    screenshot_png: bytes,
    step_text: str,
    width: int,
    height: int,
    actions_so_far: int,
    config: LLMConfig,
    device_context: str = "",
    trace_entries: list | None = None,
    nav_context: str = "",
) -> Action:
    """Send screenshot + step to the LLM, return the next Action to take."""
    # Hybrid pipeline: reasoning model + grounding model
    if config.grounding_provider:
        return _decide_action_hybrid(
            screenshot_png, step_text, width, height,
            actions_so_far, config, device_context, trace_entries,
            nav_context=nav_context,
        )

    provider = config.provider.lower()

    if provider in _MOONSHOT_PROVIDERS:
        return _decide_action_moonshot(
            screenshot_png, step_text, width, height,
            actions_so_far, config, device_context, trace_entries,
        )

    prompt = ACTION_PROMPT.format(
        step_text=step_text,
        width=width,
        height=height,
        actions_so_far=actions_so_far,
        device_context=f"Device context: {device_context}\n" if device_context else "",
    )

    raw = _call_vision(prompt, screenshot_png, config)
    data = _parse_json(raw)

    if trace_entries is not None:
        trace_entries.append({"prompt": prompt, "raw_response": raw})

    action_str = data.get("action", "wait")
    try:
        action_type = ActionType(action_str)
    except ValueError:
        logger.warning("Unknown action type '%s', defaulting to wait", action_str)
        action_type = ActionType.WAIT

    return Action(
        action_type=action_type,
        x=int(data.get("x", 0)),
        y=int(data.get("y", 0)),
        x2=int(data.get("x2", 0)),
        y2=int(data.get("y2", 0)),
        text=str(data.get("text", "")),
        reasoning=str(data.get("reasoning", "")),
    )


def verify_step(
    screenshot_png: bytes,
    step_text: str,
    config: LLMConfig,
    device_context: str = "",
    trace_entries: list | None = None,
) -> tuple[bool, str, str]:
    """Send screenshot + assertion to the LLM, return (passed, confidence, reasoning)."""
    provider = config.provider.lower()

    if provider in _MOONSHOT_PROVIDERS:
        return _verify_step_moonshot(
            screenshot_png, step_text, config, device_context, trace_entries,
        )

    prompt = VERIFICATION_PROMPT.format(
        step_text=step_text,
        device_context=f"Device context: {device_context}\n" if device_context else "",
    )

    raw = _call_vision(prompt, screenshot_png, config)
    data = _parse_json(raw)

    if trace_entries is not None:
        trace_entries.append({"prompt": prompt, "raw_response": raw})

    passed = bool(data.get("passed", False))
    confidence = str(data.get("confidence", "low"))
    reasoning = str(data.get("reasoning", ""))

    return passed, confidence, reasoning


def _call_vision(prompt: str, image_png: bytes, config: LLMConfig) -> str:
    """Multimodal call with image + text prompt. Supports Google, OpenAI, and Anthropic."""
    provider = config.provider.lower()

    if provider in _OPENAI_PROVIDERS:
        return _call_vision_openai(prompt, image_png, config)
    if provider in _ANTHROPIC_PROVIDERS:
        return _call_vision_anthropic(prompt, image_png, config)
    return _call_vision_google(prompt, image_png, config)


@retry_llm_call
def _call_vision_google(prompt: str, image_png: bytes, config: LLMConfig) -> str:
    """Google Gemini multimodal call."""
    from google import genai

    api_key = config.api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set.")

    client = _get_client(api_key, provider="google")
    image_part = genai.types.Part.from_bytes(data=image_png, mime_type="image/png")

    model_id = config.model if config.model.startswith("models/") else f"models/{config.model}"
    response = client.models.generate_content(
        model=model_id,
        contents=[image_part, prompt],
        config=genai.types.GenerateContentConfig(temperature=0.1),
    )
    return response.text


@retry_llm_call
def _call_vision_openai(prompt: str, image_png: bytes, config: LLMConfig) -> str:
    """OpenAI multimodal call (GPT-4o, etc.)."""
    api_key = config.api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set.")

    client = _get_client(api_key, provider="openai")
    b64_image = base64.b64encode(image_png).decode("utf-8")

    response = client.chat.completions.create(
        model=config.model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{b64_image}",
                }},
            ],
        }],
        temperature=0.1,
    )
    return response.choices[0].message.content


@retry_llm_call
def _call_vision_anthropic(prompt: str, image_png: bytes, config: LLMConfig) -> str:
    """Anthropic Claude multimodal call."""
    api_key = config.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set.")

    client = _get_client(api_key, provider="anthropic")
    b64_image = base64.b64encode(image_png).decode("utf-8")

    response = client.messages.create(
        model=config.model,
        max_tokens=4096,
        temperature=0.1,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64_image,
                }},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return response.content[0].text


def _get_moonshot_client(config: LLMConfig):
    """Return a cached Moonshot OpenAI-compatible client."""
    api_key = config.api_key or os.environ.get("MOONSHOT_API_KEY")
    if not api_key:
        raise ValueError("MOONSHOT_API_KEY environment variable is not set.")
    return _get_client(api_key, provider="moonshot")


@retry_llm_call
def _chat_completion_with_retry(client, **kwargs):
    """Wrapper around client.chat.completions.create with retry on transient errors."""
    return client.chat.completions.create(**kwargs)


# ---------------------------------------------------------------------------
# Moonshot / Kimi K2.5 — action pipeline (normalized 0-1000 coordinates)
# ---------------------------------------------------------------------------

_KIMI_ACTION_SYSTEM = """\
You are an Android/iOS UI automation expert.
Your task is to identify the target UI element based on a test step and return \
the next action to perform.
Before returning the JSON, mentally draw a 10x10 grid over the image to align \
the element centers.
Return ONLY a JSON object in this format:
{"action": "<action_type>", "coords": [x, y], "text": "", "reasoning": "short explanation"}

action_type must be one of: tap, type, swipe_up, swipe_down, swipe_left, swipe_right, long_press, drag, back, enter, wait, done.
- tap: tap the element at coords.
- type: type text into the currently focused field (coords ignored, include "text").
- swipe_up / swipe_down: scroll the screen vertically.
- swipe_left / swipe_right: swipe the screen horizontally (for carousels, tabs).
- long_press: long-press at coords (for context menus, selection mode).
- drag: drag from coords to coords2 (for reordering, sliders). Include "coords2": [x2, y2].
- back: press Android back button.
- enter: press Enter/Return key.
- wait: wait for the screen to update.
- done: the step is already complete on screen.

Coordinates must be normalized to a 0-1000 scale (top-left = [0,0], bottom-right = [1000,1000]).
If the action does not need coordinates, use [0, 0]."""

_KIMI_ACTION_USER = """\
Test step: {step_text}
Actions taken so far for this step: {actions_so_far}
{device_context}
Analyze the screenshot and return the single next action."""


def _decide_action_moonshot(
    screenshot_png: bytes,
    step_text: str,
    width: int,
    height: int,
    actions_so_far: int,
    config: LLMConfig,
    device_context: str,
    trace_entries: list | None,
) -> Action:
    """Kimi K2.5 action call with normalized 0-1000 coordinates."""
    client = _get_moonshot_client(config)
    b64_image = base64.b64encode(screenshot_png).decode("utf-8")

    user_text = _KIMI_ACTION_USER.format(
        step_text=step_text,
        actions_so_far=actions_so_far,
        device_context=f"Device context: {device_context}\n" if device_context else "",
    )

    # Use Thinking model for complex UI; fall back to standard for speed
    use_thinking = config.model.endswith("-thinking") or "thinking" in config.model
    extra: dict = {}
    if not use_thinking:
        extra["extra_body"] = {"thinking": {"type": "disabled"}}

    response = _chat_completion_with_retry(
        client,
        model=config.model,
        messages=[
            {"role": "system", "content": _KIMI_ACTION_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{b64_image}",
                    }},
                    {"type": "text", "text": user_text},
                ],
            },
        ],
        max_tokens=4096,
        temperature=0.6,
        top_p=0.95,
        response_format={"type": "json_object"},
        **extra,
    )

    raw = response.choices[0].message.content
    data = _parse_json(raw)

    if trace_entries is not None:
        trace_entries.append({
            "prompt": f"[system] {_KIMI_ACTION_SYSTEM}\n\n[user] {user_text}",
            "raw_response": raw,
        })

    action_str = data.get("action", "wait")
    try:
        action_type = ActionType(action_str)
    except ValueError:
        logger.warning("Unknown action type '%s', defaulting to wait", action_str)
        action_type = ActionType.WAIT

    # Denormalize 0-1000 coords to actual screen pixels
    coords = data.get("coords", [0, 0])
    if isinstance(coords, list) and len(coords) >= 2:
        px_x = int(coords[0] / 1000 * width)
        px_y = int(coords[1] / 1000 * height)
    else:
        px_x, px_y = 0, 0

    # Drag endpoint (coords2)
    coords2 = data.get("coords2", [0, 0])
    if isinstance(coords2, list) and len(coords2) >= 2:
        px_x2 = int(coords2[0] / 1000 * width)
        px_y2 = int(coords2[1] / 1000 * height)
    else:
        px_x2, px_y2 = 0, 0

    return Action(
        action_type=action_type,
        x=px_x,
        y=px_y,
        x2=px_x2,
        y2=px_y2,
        text=str(data.get("text", "")),
        reasoning=str(data.get("reasoning", "")),
    )


# ---------------------------------------------------------------------------
# Moonshot / Kimi K2.5 — verification pipeline
# ---------------------------------------------------------------------------

_KIMI_VERIFY_SYSTEM = """\
You are an Android/iOS UI verification expert.
Analyze the screenshot and determine whether the given assertion passes or fails.
Return ONLY a JSON object in this format:
{"passed": true, "confidence": "high", "reasoning": "short explanation"}

- "passed": true if the assertion is clearly satisfied, false otherwise.
- "confidence": "high", "medium", or "low".
- If you cannot determine the result, set "passed" to false and "confidence" to "low"."""

_KIMI_VERIFY_USER = """\
Assertion to verify: {step_text}
{device_context}
Analyze the screenshot and determine if this assertion passes."""


def _verify_step_moonshot(
    screenshot_png: bytes,
    step_text: str,
    config: LLMConfig,
    device_context: str,
    trace_entries: list | None,
) -> tuple[bool, str, str]:
    """Kimi K2.5 verification with Thinking mode for deeper analysis."""
    client = _get_moonshot_client(config)
    b64_image = base64.b64encode(screenshot_png).decode("utf-8")

    user_text = _KIMI_VERIFY_USER.format(
        step_text=step_text,
        device_context=f"Device context: {device_context}\n" if device_context else "",
    )

    response = _chat_completion_with_retry(
        client,
        model=config.model,
        messages=[
            {"role": "system", "content": _KIMI_VERIFY_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{b64_image}",
                    }},
                    {"type": "text", "text": user_text},
                ],
            },
        ],
        max_tokens=4096,
        temperature=1.0,
        top_p=0.95,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    data = _parse_json(raw)

    if trace_entries is not None:
        trace_entries.append({
            "prompt": f"[system] {_KIMI_VERIFY_SYSTEM}\n\n[user] {user_text}",
            "raw_response": raw,
        })

    passed = bool(data.get("passed", False))
    confidence = str(data.get("confidence", "low"))
    reasoning = str(data.get("reasoning", ""))

    return passed, confidence, reasoning


# ---------------------------------------------------------------------------
# Hybrid pipeline: reasoning model (Stage 1) + grounding model (Stage 2)
# ---------------------------------------------------------------------------


def _make_grounding_config(config: LLMConfig) -> LLMConfig:
    """Create an LLMConfig for the grounding model from the parent config."""
    return LLMConfig(
        provider=config.grounding_provider,
        model=config.grounding_model,
        api_key=config.grounding_api_key,
    )


def _decide_action_hybrid(
    screenshot_png: bytes,
    step_text: str,
    width: int,
    height: int,
    actions_so_far: int,
    config: LLMConfig,
    device_context: str,
    trace_entries: list | None,
    nav_context: str = "",
) -> Action:
    """Two-stage hybrid pipeline: reasoning model decides WHAT, grounding model decides WHERE."""

    # --- Stage 1: Reasoning (action + target description) ---
    reasoning_prompt = REASONING_PROMPT.format(
        step_text=step_text,
        width=width,
        height=height,
        actions_so_far=actions_so_far,
        device_context=f"Device context: {device_context}\n" if device_context else "",
        nav_context=nav_context,
    )

    raw_reasoning = _call_vision(reasoning_prompt, screenshot_png, config)
    data = _parse_json(raw_reasoning)

    action_str = data.get("action", "wait")
    try:
        action_type = ActionType(action_str)
    except ValueError:
        logger.warning("Unknown action type '%s', defaulting to wait", action_str)
        action_type = ActionType.WAIT

    target = str(data.get("target", ""))
    target2 = str(data.get("target2", ""))
    reasoning = str(data.get("reasoning", ""))
    text = str(data.get("text", ""))

    # --- Stage 2: Grounding (coordinates) — only for coordinate actions ---
    px_x, px_y, px_x2, px_y2 = 0, 0, 0, 0
    raw_grounding = ""

    if action_str in _COORD_ACTIONS and target:
        grounding_config = _make_grounding_config(config)
        grounding_prompt_text = ""
        px_x, px_y, raw_grounding, grounding_prompt_text = _call_grounding(
            screenshot_png, action_str, target, width, height, grounding_config,
            step_text=step_text, actions_so_far=actions_so_far,
            device_context=device_context,
        )

        # For drag, ground the second target as well
        if action_type == ActionType.DRAG and target2:
            px_x2, px_y2, raw_grounding_2, gp2 = _call_grounding(
                screenshot_png, action_str, target2, width, height, grounding_config,
                step_text=step_text, actions_so_far=actions_so_far,
                device_context=device_context,
            )
            raw_grounding += "\n---\n" + raw_grounding_2
            grounding_prompt_text += "\n---\n" + gp2

    # --- Trace ---
    if trace_entries is not None:
        entry = {"prompt": reasoning_prompt, "raw_response": raw_reasoning}
        trace_entries.append(entry)
        if raw_grounding:
            trace_entries.append({
                "prompt": grounding_prompt_text if grounding_prompt_text else "(grounding)",
                "raw_response": raw_grounding,
            })

    return Action(
        action_type=action_type,
        x=px_x,
        y=px_y,
        x2=px_x2,
        y2=px_y2,
        text=text,
        reasoning=reasoning,
    )


def _call_grounding(
    screenshot_png: bytes,
    action_type: str,
    target: str,
    width: int,
    height: int,
    config: LLMConfig,
    step_text: str = "",
    actions_so_far: int = 0,
    device_context: str = "",
) -> tuple[int, int, str, str]:
    """Route grounding call to Kimi or generic provider.

    Returns (px_x, px_y, raw_response, prompt_text).
    """
    provider = config.provider.lower()
    if provider in _MOONSHOT_PROVIDERS:
        return _call_grounding_kimi(
            screenshot_png, action_type, target, width, height, config,
            step_text=step_text, actions_so_far=actions_so_far,
            device_context=device_context,
        )
    return _call_grounding_generic(screenshot_png, action_type, target, width, height, config)


def _call_grounding_kimi(
    screenshot_png: bytes,
    action_type: str,
    target: str,
    width: int,
    height: int,
    config: LLMConfig,
    step_text: str = "",
    actions_so_far: int = 0,
    device_context: str = "",
) -> tuple[int, int, str, str]:
    """Kimi grounding using the proven action prompt + reasoning hint.

    Reuses _KIMI_ACTION_SYSTEM (which Kimi is tuned for) and adds
    the reasoning model's target description as a hint so Kimi knows
    exactly which element to locate.
    """
    client = _get_moonshot_client(config)
    b64_image = base64.b64encode(screenshot_png).decode("utf-8")

    user_text = _KIMI_ACTION_USER.format(
        step_text=step_text,
        actions_so_far=actions_so_far,
        device_context=f"Device context: {device_context}\n" if device_context else "",
    )
    user_text += f"\nHint from reasoning model: {action_type} on \"{target}\""

    response = _chat_completion_with_retry(
        client,
        model=config.model,
        messages=[
            {"role": "system", "content": _KIMI_ACTION_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{b64_image}",
                    }},
                    {"type": "text", "text": user_text},
                ],
            },
        ],
        max_tokens=4096,
        temperature=0.6,
        top_p=0.95,
        response_format={"type": "json_object"},
        extra_body={"thinking": {"type": "disabled"}},
    )

    raw = response.choices[0].message.content
    data = _parse_json(raw)

    coords = data.get("coords", [0, 0])
    if isinstance(coords, list) and len(coords) >= 2:
        px_x = int(coords[0] / 1000 * width)
        px_y = int(coords[1] / 1000 * height)
    else:
        px_x, px_y = 0, 0

    prompt_text = f"[system] {_KIMI_ACTION_SYSTEM}\n\n[user] {user_text}"
    return px_x, px_y, raw, prompt_text


def _call_grounding_generic(
    screenshot_png: bytes,
    action_type: str,
    target: str,
    width: int,
    height: int,
    config: LLMConfig,
) -> tuple[int, int, str, str]:
    """Generic grounding via Google/OpenAI with pixel coordinates."""
    prompt = GROUNDING_PROMPT.format(
        action_type=action_type, target=target, width=width, height=height,
    )

    raw = _call_vision(prompt, screenshot_png, config)
    data = _parse_json(raw)

    px_x = int(data.get("x", 0))
    px_y = int(data.get("y", 0))

    return px_x, px_y, raw, prompt


def _parse_json(raw: str) -> dict:
    """Parse JSON from LLM response, handling fences and extra text."""
    text = raw.strip()

    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # Find the JSON object
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1:
        text = text[brace_start : brace_end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse vision response as JSON: %s", e)
        return {}

    if not isinstance(data, dict):
        return {}
    return data
