"""Base class for setup agents."""

from abc import ABC, abstractmethod


class SetupAgent(ABC):
    """Abstract base for setup agents that run before UI tests.

    Each agent declares a ``name`` and a dict of ``actions`` it supports.
    The executor dispatches structured preconditions to the matching agent.
    """

    name: str = ""
    actions: dict[str, str] = {}

    @abstractmethod
    def execute(self, action: str, device, params: dict) -> str:
        """Execute a named action. Return a log message."""

    def describe(self) -> str:
        """Return capability description for LLM prompt injection."""
        lines = [f"- **{self.name}**:"]
        for action, desc in self.actions.items():
            lines.append(f"  - `{action}`: {desc}")
        return "\n".join(lines)
