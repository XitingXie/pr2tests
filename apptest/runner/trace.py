"""LLM trace logging with HTML timeline visualization."""

import html
import base64
import typing
from dataclasses import dataclass, field


@dataclass
class TraceEntry:
    """A single LLM interaction record."""

    timestamp: str  # ISO timestamp
    call_type: str  # "action" | "verification" | "computer_use"
    test_id: str
    step_index: int
    step_text: str
    prompt: str  # formatted prompt sent to LLM
    screenshot_b64: str  # base64-encoded PNG
    raw_response: str  # raw LLM output text
    parsed_result: str  # human-readable summary of parsed action/verification
    device_context: str  # keyboard state etc.
    duration_ms: int  # LLM call duration
    model: str  # model name used
    provider: str  # google/openai


@dataclass
class RunTrace:
    """Collection of trace entries for an entire test run."""

    entries: list[TraceEntry] = field(default_factory=list)
    on_add: typing.Callable[[TraceEntry], None] | None = None

    def add(self, entry: TraceEntry) -> None:
        self.entries.append(entry)
        if self.on_add:
            self.on_add(entry)


def generate_trace_html(trace: RunTrace, output_path: str) -> None:
    """Generate a self-contained HTML timeline from trace entries."""
    test_ids = sorted(set(e.test_id for e in trace.entries))
    total = len(trace.entries)
    actions = sum(1 for e in trace.entries if e.call_type == "action")
    verifications = sum(1 for e in trace.entries if e.call_type == "verification")
    computer_use = sum(1 for e in trace.entries if e.call_type == "computer_use")

    cards_html = []
    for i, entry in enumerate(trace.entries):
        card = _render_card(i, entry)
        cards_html.append(card)

    test_id_options = "".join(
        f'<option value="{html.escape(tid)}">{html.escape(tid)}</option>'
        for tid in test_ids
    )

    page = _HTML_TEMPLATE.format(
        total=total,
        actions=actions,
        verifications=verifications,
        computer_use=computer_use,
        test_count=len(test_ids),
        test_id_options=test_id_options,
        cards="".join(cards_html),
    )

    with open(output_path, "w") as f:
        f.write(page)


def _render_card(index: int, entry: TraceEntry) -> str:
    """Render a single trace entry as an HTML card."""
    type_class = {
        "action": "card-action",
        "verification": "card-verification",
        "computer_use": "card-computer-use",
    }.get(entry.call_type, "card-action")

    type_label = {
        "action": "ACTION",
        "verification": "VERIFY",
        "computer_use": "COMPUTER USE",
    }.get(entry.call_type, entry.call_type.upper())

    screenshot_html = ""
    if entry.screenshot_b64:
        screenshot_html = (
            '<details class="screenshot-details">'
            "<summary>Screenshot</summary>"
            f'<img src="data:image/png;base64,{entry.screenshot_b64}" '
            'class="screenshot-full" alt="screenshot" />'
            "</details>"
            f'<img src="data:image/png;base64,{entry.screenshot_b64}" '
            'class="screenshot-thumb" alt="screenshot thumbnail" />'
        )

    device_ctx_html = ""
    if entry.device_context:
        device_ctx_html = (
            f'<div class="device-context">Device: {html.escape(entry.device_context)}</div>'
        )

    return (
        f'<div class="card {type_class}" data-testid="{html.escape(entry.test_id)}">'
        f'<div class="card-header">'
        f'<span class="badge">{type_label}</span>'
        f'<span class="entry-num">#{index + 1}</span>'
        f'<span class="timestamp">{html.escape(entry.timestamp)}</span>'
        f'<span class="test-id">{html.escape(entry.test_id)}</span>'
        f'<span class="step-info">Step {entry.step_index}</span>'
        f'<span class="model">{html.escape(entry.model)}</span>'
        f'<span class="duration">{entry.duration_ms}ms</span>'
        f"</div>"
        f'<div class="step-text">{html.escape(entry.step_text)}</div>'
        f"{screenshot_html}"
        f'<details class="prompt-details">'
        f"<summary>Prompt</summary>"
        f'<pre class="prompt-text">{html.escape(entry.prompt)}</pre>'
        f"</details>"
        f'<details class="response-details">'
        f"<summary>Raw LLM Response</summary>"
        f'<pre class="response-text">{html.escape(entry.raw_response)}</pre>'
        f"</details>"
        f'<div class="parsed-result">{html.escape(entry.parsed_result)}</div>'
        f"{device_ctx_html}"
        f"</div>"
    )


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>LLM Trace Timeline</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #f5f5f5; color: #333; padding: 20px; }}
  h1 {{ margin-bottom: 10px; font-size: 1.5em; }}
  .summary {{ background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 16px;
              box-shadow: 0 1px 3px rgba(0,0,0,0.1); display: flex; gap: 24px;
              flex-wrap: wrap; align-items: center; }}
  .summary .stat {{ text-align: center; }}
  .summary .stat .num {{ font-size: 1.8em; font-weight: 700; }}
  .summary .stat .label {{ font-size: 0.8em; color: #666; }}
  .filter {{ margin-bottom: 16px; }}
  .filter select {{ padding: 6px 12px; border-radius: 4px; border: 1px solid #ccc;
                    font-size: 0.9em; }}
  .card {{ background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 12px;
           box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-left: 4px solid #ccc; }}
  .card-action {{ border-left-color: #3b82f6; }}
  .card-verification {{ border-left-color: #10b981; }}
  .card-computer-use {{ border-left-color: #8b5cf6; }}
  .card-header {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
                  margin-bottom: 8px; font-size: 0.85em; }}
  .badge {{ padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 0.75em;
            color: #fff; }}
  .card-action .badge {{ background: #3b82f6; }}
  .card-verification .badge {{ background: #10b981; }}
  .card-computer-use .badge {{ background: #8b5cf6; }}
  .entry-num {{ color: #999; font-weight: 600; }}
  .timestamp {{ color: #666; }}
  .test-id {{ font-weight: 600; color: #1e40af; }}
  .step-info {{ color: #666; }}
  .model {{ color: #666; font-style: italic; }}
  .duration {{ color: #b45309; font-weight: 600; }}
  .step-text {{ font-weight: 500; margin-bottom: 10px; padding: 6px 10px;
                background: #f8fafc; border-radius: 4px; }}
  .screenshot-thumb {{ max-width: 200px; max-height: 160px; border: 1px solid #ddd;
                       border-radius: 4px; margin-bottom: 8px; cursor: pointer; }}
  .screenshot-full {{ max-width: 100%; border: 1px solid #ddd; border-radius: 4px;
                      margin-top: 8px; }}
  .screenshot-details {{ margin-bottom: 8px; }}
  details {{ margin-bottom: 6px; }}
  summary {{ cursor: pointer; font-weight: 600; font-size: 0.85em; color: #555;
             padding: 4px 0; }}
  summary:hover {{ color: #111; }}
  pre {{ background: #1e293b; color: #e2e8f0; padding: 12px; border-radius: 6px;
         overflow-x: auto; font-size: 0.8em; line-height: 1.5; white-space: pre-wrap;
         word-break: break-word; margin-top: 6px; max-height: 400px; overflow-y: auto; }}
  .parsed-result {{ padding: 8px 10px; background: #f0fdf4; border-radius: 4px;
                    font-size: 0.9em; border: 1px solid #bbf7d0; }}
  .card-verification .parsed-result {{ background: #f0fdf4; border-color: #bbf7d0; }}
  .device-context {{ font-size: 0.8em; color: #666; margin-top: 6px; font-style: italic; }}
</style>
</head>
<body>
<h1>LLM Trace Timeline</h1>

<div class="summary">
  <div class="stat"><div class="num">{total}</div><div class="label">Total Calls</div></div>
  <div class="stat"><div class="num">{actions}</div><div class="label">Actions</div></div>
  <div class="stat"><div class="num">{verifications}</div><div class="label">Verifications</div></div>
  <div class="stat"><div class="num">{computer_use}</div><div class="label">Computer Use</div></div>
  <div class="stat"><div class="num">{test_count}</div><div class="label">Tests</div></div>
</div>

<div class="filter">
  <label for="test-filter">Filter by test: </label>
  <select id="test-filter" onchange="filterCards(this.value)">
    <option value="all">All tests</option>
    {test_id_options}
  </select>
</div>

<div id="timeline">
{cards}
</div>

<script>
function filterCards(testId) {{
  var cards = document.querySelectorAll('.card');
  for (var i = 0; i < cards.length; i++) {{
    if (testId === 'all' || cards[i].getAttribute('data-testid') === testId) {{
      cards[i].style.display = '';
    }} else {{
      cards[i].style.display = 'none';
    }}
  }}
}}
</script>
</body>
</html>
"""
