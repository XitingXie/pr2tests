# Changelog: LLM-Based Test Step Generator

**Commit:** `d9dd515`
**Date:** 2026-02-27
**Scope:** `apptest/generator/`, `cli.py`, `config.py`, `pyproject.toml`, tests

## Why

The analyzer phase produces `analysis.json` with classified changes, dependency chains, and screen context — but there was no way to turn that into actionable test steps. This is the core value proposition of the tool: given a code change, automatically generate the manual QA steps a tester should run. Without this, the pipeline stops at "here's what changed" instead of "here's what to test."

## What Changed

### 1. New `apptest/generator/` package

#### `prompts.py` — Prompt templates
- `TEST_GENERATION_PROMPT`: System prompt instructing the LLM to act as a senior QA engineer. Specifies rules (test what changed, cover happy + edge + error paths, write regression tests for bug fixes), and the exact JSON output schema (`id`, `description`, `covers`, `change_type`, `priority`, `test_data`).
- `LOGIC_ONLY_ADDENDUM`: Extra instructions appended when a PR has no UI changes — guides the LLM to focus on observable behavior, state management, error handling, and performance regressions through existing UI elements.

#### `test_generator.py` — Core module
- **Data structures:**
  - `TestCase` — a single generated test with step-by-step description, coverage info, change type classification, priority, and optional test data inputs.
  - `GenerationResult` — wraps the full output: timestamp, PR ref, change counts per category, and list of `TestCase`s.
- **`_format_changes(analysis)`** — Converts the analysis dict into structured, readable sections for the prompt:
  - UI changes: diff + affected screens + related strings
  - Logic changes: diff + truncated full source (100-line cap) + dependency chain + screen context with layout XML
  - Test changes: file list + diff (informational)
  - Infra changes: file list only (informational)
- **`_parse_test_cases(raw_text)`** — Robust JSON extraction from LLM output. Handles: clean arrays, markdown-fenced responses, text-wrapped JSON, missing fields (defaults applied), non-dict items (skipped), and invalid `test_data` types. Returns empty list on malformed responses rather than crashing.
- **`generate_tests(analysis, config)`** — Orchestrator: builds prompt, conditionally appends logic-only addendum, calls LLM, parses response. Returns `GenerationResult` with empty tests list for no-op cases (no UI/logic changes).
- **`_call_google()`** — Google Gemini integration via `google-genai` SDK. Uses `temperature=0.3` for deterministic output. API key from `config.api_key` or `GEMINI_API_KEY` env var.
- **`write_tests(result, path)`** — Serializes `GenerationResult` to JSON.

### 2. CLI command: `apptest generate`
- **Options:** `--analysis` (default `.apptest/analysis.json`), `--output` (default `.apptest/tests.json`), `--config` (default `apptest.yml`)
- **Pipeline:** load analysis → call `generate_tests()` → write output → print summary with per-test priority/coverage info
- Early-exits if no UI or logic changes present.

### 3. Config changes (`config.py`)
- `LLMConfig` defaults changed: `provider="google"`, `model="gemini-2.0-flash"`.
- Added `api_key: str = ""` field — loaded from YAML or falls back to `GEMINI_API_KEY` env var at call time.
- `load_config()` updated to parse the new `api_key` field.

### 4. Dependencies (`pyproject.toml`)
- Added `google-genai>=1.0` to core dependencies.

### 5. Tests (`apptest/tests/test_generator.py`)
25 unit tests across 5 test classes:
- **`TestTruncateSource`** (2 tests): short source unchanged, long source capped at 100 lines.
- **`TestFormatChanges`** (7 tests): each change type formatted correctly, empty analysis returns empty string, logic-only omits UI section, screen context includes layout.
- **`TestParseTestCases`** (9 tests): valid JSON, markdown fences, surrounding text, malformed JSON, non-array, empty array, missing fields, non-dict items, invalid test_data type.
- **`TestGenerateTests`** (6 tests): empty analysis short-circuits, logic-only addendum included/excluded correctly, change summary counts, PR ref captured, malformed LLM response returns empty tests.
- **`TestWriteTests`** (1 test): JSON round-trip serialization.

## How It Works (End-to-End)

```
apptest analyze --diff HEAD~1..HEAD    # → .apptest/analysis.json
apptest generate                        # → .apptest/tests.json
```

The generator reads analysis.json, formats each change category into a structured prompt section, sends it to Gemini 2.0 Flash with QA-engineer system instructions, parses the JSON response into typed `TestCase` objects, and writes the result. The prompt includes full code diffs, truncated source context, dependency chains, and layout XML so the LLM can generate precise, screen-specific test steps.

## Lessons Learned

- **Robust parsing matters more than prompt engineering.** LLMs return inconsistent formats (fenced, wrapped, partial JSON). The bracket-finding + fence-stripping approach handles all observed variations without brittle regex.
- **Truncating source at 100 lines is a good tradeoff.** Full source files can be 500+ lines, which wastes tokens on irrelevant code. The diff already captures what changed; the truncated source provides class structure context.
- **The logic-only addendum is important.** Without it, the LLM tries to invent UI elements for logic-only PRs. Explicitly saying "the UI is unchanged" produces much better tests that work through existing screens.

## Potential Issues

- **Token limits:** Large PRs with many files could exceed Gemini's context window. No chunking/batching strategy yet — a future improvement would split by screen and merge results.
- **No retry logic:** If the LLM call fails (rate limit, network), the command fails. Could add exponential backoff.
- **Single provider:** Only Google/Gemini supported. The `_call_llm` dispatcher is structured for adding providers but only `google` is implemented.

## Future Improvements

- Add Anthropic/Claude provider support alongside Google
- Chunk large PRs by screen to avoid token limits
- Add retry logic with exponential backoff for LLM calls
- Wire generator into the `report` pipeline to replace mock tests
- Add a `--dry-run` flag to preview the prompt without calling the LLM
