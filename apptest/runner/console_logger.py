"""Real-time console logging for test execution events."""

import click

from .trace import TraceEntry


class ConsoleLogger:
    """Prints structured events to the console during test execution.

    All methods are no-ops when ``enabled=False``, so callers can invoke
    them unconditionally without checking a flag.
    """

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    # -- run-level events ---------------------------------------------------

    def run_start(
        self,
        pr_number: int | None,
        pr_title: str | None,
        model: str,
        provider: str,
        device_serial: str,
        test_count: int,
        app_package: str,
    ) -> None:
        if not self.enabled:
            return
        if pr_number and pr_title:
            click.echo(f"[RUN] PR #{pr_number}: {pr_title}")
        elif pr_title:
            click.echo(f"[RUN] PR: {pr_title}")
        click.echo(f"[RUN] LLM: {provider}/{model} | Device: {device_serial}")
        click.echo(f"[RUN] App: {app_package} | Tests: {test_count}")
        click.echo()

    def log(self, message: str) -> None:
        """Print a general log message (e.g. setup agent output)."""
        if not self.enabled:
            return
        click.echo(f"  [SETUP] {message}")

    # -- test-level events --------------------------------------------------

    def test_start(self, test_id: str) -> None:
        if not self.enabled:
            return
        click.echo(f"[TEST] {test_id} starting")

    def test_end(self, test_id: str, status: str, duration_ms: int) -> None:
        if not self.enabled:
            return
        secs = duration_ms / 1000
        click.echo(f"  [RESULT] {test_id}: {status.upper()} ({secs:.1f}s)")
        click.echo()

    # -- step-level events --------------------------------------------------

    def step_start(self, step_index: int, step_text: str, is_verification: bool) -> None:
        if not self.enabled:
            return
        tag = "VERIFY" if is_verification else "STEP"
        click.echo(f"  [{tag} {step_index}] {step_text}")

    # -- action-level events ------------------------------------------------

    def screenshot_taken(self) -> None:
        if not self.enabled:
            return
        click.echo("    [SCREENSHOT] captured")

    def action_launch(self, app_package: str) -> None:
        if not self.enabled:
            return
        click.echo(f"    [LAUNCH] {app_package}")

    def action_executed(self, action_type: str, x: int = 0, y: int = 0, text: str = "") -> None:
        if not self.enabled:
            return
        if action_type == "tap":
            click.echo(f"    [ACTION] tap({x}, {y})")
        elif action_type == "type":
            click.echo(f"    [ACTION] type(\"{text}\")")
        elif action_type in ("swipe_up", "swipe_down"):
            click.echo(f"    [ACTION] {action_type}")
        else:
            click.echo(f"    [ACTION] {action_type}")

    def stuck_detected(self, recovery: str) -> None:
        if not self.enabled:
            return
        click.echo(f"    [STUCK] recovery: {recovery}")

    # -- trace callback (LLM events) ---------------------------------------

    def on_trace_entry(self, entry: TraceEntry) -> None:
        """Callback for ``RunTrace.add()`` — prints LLM call summary."""
        if not self.enabled:
            return
        call_label = {
            "action": "ACTION",
            "verification": "VERIFY",
            "computer_use": "COMPUTER_USE",
        }.get(entry.call_type, entry.call_type.upper())

        model_short = entry.model.split("/")[-1] if "/" in entry.model else entry.model
        click.echo(f"    [LLM] {call_label} -> {model_short} ({entry.duration_ms}ms)")
        click.echo(f"    [LLM] -> {entry.parsed_result}")
