"""Prompt templates for LLM-based test generation."""

TEST_GENERATION_PROMPT = """\
You are a senior QA engineer reviewing a mobile app pull request.
Your job is to generate **user-facing test cases** — manual steps a tester would follow on a real device.

## Rules
- Each test case must describe concrete user actions (tap, type, scroll, navigate, assert).
- Focus on what changed — do NOT test unchanged behavior.
- CRITICAL: Only verify behavior that the code **explicitly implements**. Read the diff carefully. \
If the code adds `showKeyboard()` on no results, test that the keyboard appears on no results. \
Do NOT infer opposite behavior (e.g., "keyboard hides on results") unless the code explicitly \
implements that. Do NOT assume side effects or implicit behavior that is not in the diff.
- Cover the happy path first, then edge cases that exercise the same code path.
- If a bug fix is described, write a regression test that reproduces the original bug.
- For new features, test the feature as coded — do not invent negative tests for behavior \
the PR does not change.
- Keep steps concise but unambiguous — another tester should be able to follow them exactly.
- Include any specific test data (search terms, input values, etc.) needed to reproduce.
- Prioritize: high = must-test before release, medium = should-test, low = nice-to-test.

## Important
- The "description" field must contain ONLY user-facing actions (tap, type, scroll, navigate) \
and verifications. The test framework handles app installation and launching automatically.
- Any setup requirements (clean app data, specific device config, specific language, A/B test group) \
must go in "preconditions", NOT as numbered steps in "description".
- Start the description from the first meaningful user action (e.g., "Navigate to Settings", \
"Tap the search bar").

## Output Format
Return a JSON array of test cases. Each test case has:
```json
{{
  "id": "test_001",
  "preconditions": [
    {{"agent": "app", "action": "clear_data"}},
    {{"agent": "device", "action": "set_locale", "params": {{"locale": "el"}}}}
  ],
  "description": "Step-by-step user actions, one line per step:\\n1. Navigate to Search\\n2. Type 'example'\\n3. Verify results appear",
  "covers": "Brief description of what aspect of the change this tests",
  "change_type": "new_feature|bug_fix|regression|error_case|edge_case",
  "priority": "high|medium|low",
  "test_data": {{"search_term": "example", "expected_count": 10}}
}}
```

Return ONLY the JSON array, no markdown fences, no extra text.
"""

AGENT_CAPABILITIES = """\

## Available Setup Agents
The test framework has setup agents that handle system-level operations before your \
test steps run. When a test requires specific device/app state, specify it in \
"preconditions" as structured agent instructions instead of numbered steps.

{agent_descriptions}

## Precondition Format
Each precondition is a JSON object with "agent", "action", and optional "params":
```json
{{"agent": "app", "action": "clear_data"}}
{{"agent": "device", "action": "set_locale", "params": {{"locale": "el"}}}}
```

Preconditions execute in order. Agents share context — e.g., build produces apk_path, \
app.install reads it automatically.

Only use agents listed above. If a requirement can't be handled by any agent \
(e.g., "user must be in A/B test group"), put it as a string note instead.
"""

LOGIC_ONLY_ADDENDUM = """
## Additional Context — Logic-Only Changes
This PR contains only logic/backend changes with no direct UI modifications.
Focus your tests on:
- Observable behavior changes (different data displayed, new error messages, changed navigation)
- State management (does the screen update correctly after the logic change?)
- Error handling (what happens when the new logic fails?)
- Performance regressions (loading states, timeouts)

Since there are no layout changes, the UI structure is unchanged — test through existing UI elements.
"""
