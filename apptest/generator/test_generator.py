"""Generate user-facing test steps from PR analysis using an LLM."""

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import click

from ..config import LLMConfig
from .prompts import AGENT_CAPABILITIES, LOGIC_ONLY_ADDENDUM, TEST_GENERATION_PROMPT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TestCase:
    id: str                     # e.g. "test_001"
    description: str            # step-by-step user actions
    covers: str                 # what aspect of the change
    change_type: str            # new_feature|bug_fix|regression|error_case|edge_case
    priority: str               # high|medium|low
    preconditions: list = field(default_factory=list)  # structured dicts or legacy strings
    test_data: dict = field(default_factory=dict)


@dataclass
class GenerationResult:
    generated_at: str           # ISO timestamp
    pr_ref: str
    change_summary: dict        # counts per category
    tests: list[TestCase] = field(default_factory=list)
    pr_number: int | None = None
    pr_title: str | None = None
    pr_url: str | None = None


# ---------------------------------------------------------------------------
# Change formatting
# ---------------------------------------------------------------------------

_MAX_SOURCE_LINES = 100


def _truncate_source(source: str, max_lines: int = _MAX_SOURCE_LINES) -> str:
    """Truncate source code to max_lines, adding a note if truncated."""
    lines = source.splitlines()
    if len(lines) <= max_lines:
        return source
    return "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"


def _format_changes(analysis: dict) -> str:
    """Format analysis dict into readable sections for the LLM prompt."""
    sections: list[str] = []

    # --- UI changes ---
    ui_changes = analysis.get("ui_changes", [])
    if ui_changes:
        parts = ["## UI Changes"]
        for i, ch in enumerate(ui_changes, 1):
            parts.append(f"\n### UI Change {i}: {ch['file']}")
            parts.append(f"Type: {ch['type']}")
            if ch.get("diff"):
                parts.append(f"Diff:\n```\n{ch['diff']}\n```")
            screens = ch.get("affected_screens", [])
            if screens:
                names = [Path(s).stem for s in screens]
                parts.append(f"Affected screens: {', '.join(names)}")
            strings = ch.get("related_strings", {})
            if strings:
                str_lines = [f"  {k}: {v}" for k, v in strings.items()]
                parts.append("Related strings:\n" + "\n".join(str_lines))
        sections.append("\n".join(parts))

    # --- Logic changes ---
    logic_changes = analysis.get("logic_changes", [])
    if logic_changes:
        parts = ["## Logic Changes"]
        for i, ch in enumerate(logic_changes, 1):
            parts.append(f"\n### Logic Change {i}: {ch['file']}")
            parts.append(f"Type: {ch['type']}")
            parts.append(f"Change nature: {ch['change_nature']}")
            if ch.get("diff"):
                parts.append(f"Diff:\n```\n{ch['diff']}\n```")
            if ch.get("full_source"):
                parts.append(
                    f"Full source (context):\n```\n{_truncate_source(ch['full_source'])}\n```"
                )
            chain = ch.get("dependency_chain", [])
            if chain:
                chain_names = [Path(c).stem for c in chain]
                parts.append(f"Dependency chain: {' → '.join(chain_names)}")
            screens = ch.get("affected_screens", [])
            if screens:
                names = [Path(s).stem for s in screens]
                parts.append(f"Affected screens: {', '.join(names)}")
            for ctx in ch.get("screen_context", []):
                screen_name = Path(ctx.get("screen_file", "")).stem
                parts.append(f"\nScreen context ({screen_name}):")
                if ctx.get("layout"):
                    parts.append(f"Layout ({ctx.get('layout_file', 'unknown')}):\n```xml\n{ctx['layout']}\n```")
        sections.append("\n".join(parts))

    # --- Test changes ---
    test_changes = analysis.get("test_changes", [])
    if test_changes:
        parts = ["## Existing Test Changes (informational)"]
        for ch in test_changes:
            parts.append(f"- {ch['file']}")
            if ch.get("diff"):
                parts.append(f"```\n{ch['diff']}\n```")
        sections.append("\n".join(parts))

    # --- Infra changes ---
    infra_changes = analysis.get("infra_changes", [])
    if infra_changes:
        parts = ["## Infrastructure Changes (informational)"]
        for ch in infra_changes:
            parts.append(f"- {ch['file']} ({ch['type']})")
        sections.append("\n".join(parts))

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


def _parse_test_cases(raw_text: str) -> list[TestCase]:
    """Parse LLM response text into TestCase objects.

    Handles both clean JSON arrays and responses wrapped in markdown fences.
    """
    text = raw_text.strip()

    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # Try to find a JSON array in the text
    bracket_start = text.find("[")
    bracket_end = text.rfind("]")
    if bracket_start != -1 and bracket_end != -1:
        text = text[bracket_start : bracket_end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse LLM response as JSON: %s", e)
        return []

    if not isinstance(data, list):
        logger.warning("LLM response is not a JSON array")
        return []

    cases: list[TestCase] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            raw_pre = item.get("preconditions", [])
            if not isinstance(raw_pre, list):
                raw_pre = []
            # Accept both structured dicts and legacy strings
            preconditions: list = []
            for p in raw_pre:
                if isinstance(p, dict):
                    preconditions.append(p)
                elif isinstance(p, str):
                    preconditions.append(
                        {"agent": "unknown", "action": "note", "params": {"text": p}}
                    )
            cases.append(TestCase(
                id=str(item.get("id", f"test_{len(cases) + 1:03d}")),
                description=str(item.get("description", "")),
                covers=str(item.get("covers", "")),
                change_type=str(item.get("change_type", "unknown")),
                priority=str(item.get("priority", "medium")),
                preconditions=preconditions,
                test_data=item.get("test_data", {}) if isinstance(item.get("test_data"), dict) else {},
            ))
        except (TypeError, ValueError) as e:
            logger.warning("Skipping malformed test case: %s", e)
    return cases


def generate_tests(analysis: dict, config: LLMConfig, verbose: bool = False) -> GenerationResult:
    """Generate test cases from analysis output using an LLM.

    Args:
        analysis: Parsed analysis.json dict.
        config: LLM configuration (provider, model, api_key).
        verbose: If True, print LLM request/response timing to console.

    Returns:
        GenerationResult with generated test cases.
    """
    pr_ref = analysis.get("diff_ref", "unknown")
    pr_number = analysis.get("pr_number")
    pr_title = analysis.get("pr_title")
    pr_url = analysis.get("pr_url")
    change_summary = {
        "ui": len(analysis.get("ui_changes", [])),
        "logic": len(analysis.get("logic_changes", [])),
        "test": len(analysis.get("test_changes", [])),
        "infra": len(analysis.get("infra_changes", [])),
    }

    # Build the prompt
    changes_text = _format_changes(analysis)
    if not changes_text.strip():
        return GenerationResult(
            generated_at=datetime.now(timezone.utc).isoformat(),
            pr_ref=pr_ref,
            change_summary=change_summary,
            tests=[],
            pr_number=pr_number,
            pr_title=pr_title,
            pr_url=pr_url,
        )

    # Build system prompt with optional addenda
    from ..agents import AgentRegistry

    prompt = TEST_GENERATION_PROMPT
    if change_summary["ui"] == 0 and change_summary["logic"] > 0:
        prompt += LOGIC_ONLY_ADDENDUM

    # Inject agent capabilities so the LLM outputs structured preconditions
    registry = AgentRegistry.auto_discover()
    prompt += AGENT_CAPABILITIES.format(
        agent_descriptions=registry.prompt_description(),
    )

    # Include PR title in context if available
    pr_label = f"PR: {pr_ref}"
    if pr_title:
        pr_label = f"PR #{pr_number}: {pr_title}" if pr_number else f"PR: {pr_title}"
    user_message = (
        f"App: {analysis.get('app_name', 'Unknown')} ({analysis.get('app_package', '')})\n"
        f"{pr_label}\n\n"
        f"{changes_text}"
    )

    # Call the LLM
    if verbose:
        click.echo(f"  [LLM] Sending request to {config.provider}/{config.model}...")
    call_start = time.monotonic()
    raw_response = _call_llm(user_message, prompt, config)
    call_ms = int((time.monotonic() - call_start) * 1000)
    if verbose:
        click.echo(f"  [LLM] Response received ({call_ms}ms, {len(raw_response)} chars)")

    # Parse response
    tests = _parse_test_cases(raw_response)

    return GenerationResult(
        generated_at=datetime.now(timezone.utc).isoformat(),
        pr_ref=pr_ref,
        change_summary=change_summary,
        tests=tests,
        pr_number=pr_number,
        pr_title=pr_title,
        pr_url=pr_url,
    )


def _call_llm(user_message: str, system_prompt: str, config: LLMConfig) -> str:
    """Call the configured LLM provider and return the response text."""
    if config.provider in ("moonshot", "kimi"):
        return _call_moonshot(user_message, system_prompt, config)
    elif config.provider == "google":
        return _call_google(user_message, system_prompt, config)
    else:
        raise ValueError(
            f"Unsupported LLM provider: '{config.provider}'. "
            f"Supported: moonshot, kimi, google"
        )


def _call_moonshot(user_message: str, system_prompt: str, config: LLMConfig) -> str:
    """Call Moonshot Kimi via the OpenAI-compatible API."""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError(
            "openai package is required for Moonshot/Kimi provider. "
            "Install with: pip install openai"
        )

    api_key = config.api_key or os.environ.get("MOONSHOT_API_KEY")
    if not api_key:
        raise ValueError(
            "MOONSHOT_API_KEY environment variable is not set and no api_key in config. "
            "Set it with: export MOONSHOT_API_KEY=your-key"
        )

    client = OpenAI(api_key=api_key, base_url="https://api.moonshot.ai/v1")

    # Kimi K2.5 only allows temperature=1; other Moonshot models accept 0-1.
    temp = 1.0 if "k2.5" in config.model.lower() else 0.3

    response = client.chat.completions.create(
        model=config.model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=temp,
    )
    return response.choices[0].message.content


def _call_google(user_message: str, system_prompt: str, config: LLMConfig) -> str:
    """Call Google Gemini via the google-genai SDK."""
    try:
        from google import genai
    except ImportError:
        raise ImportError(
            "google-genai package is required for Google provider. "
            "Install with: pip install google-genai"
        )

    api_key = config.api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY environment variable is not set and no api_key in config. "
            "Set it with: export GEMINI_API_KEY=your-key"
        )

    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=config.model,
        contents=user_message,
        config=genai.types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.3,
        ),
    )
    return response.text


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def write_tests(result: GenerationResult, output_path: Path) -> Path:
    """Write generation result to a JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(result)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    return output_path
