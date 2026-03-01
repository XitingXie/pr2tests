"""Agent registry with auto-discovery from bundled, project, and user directories."""

import importlib
import importlib.util
import logging
import sys
from pathlib import Path

from .base import SetupAgent

logger = logging.getLogger(__name__)

__all__ = ["AgentRegistry", "SetupAgent"]

# Directory containing bundled agents (this package)
_BUNDLED_DIR = Path(__file__).parent


class AgentRegistry:
    """Registry of setup agents, with auto-discovery from multiple directories.

    Scan order (later overrides earlier):
      1. Bundled agents in ``apptest/agents/``
      2. Project agents in ``<project>/.apptest/agents/``
      3. User agents in ``~/.apptest/agents/``
    """

    def __init__(self):
        self._agents: dict[str, SetupAgent] = {}

    def register(self, agent: SetupAgent) -> None:
        self._agents[agent.name] = agent

    def get(self, name: str) -> SetupAgent | None:
        return self._agents.get(name)

    @classmethod
    def auto_discover(cls, project_path: Path | None = None) -> "AgentRegistry":
        """Scan agent directories and auto-register all agents."""
        registry = cls()

        # 1. Bundled agents (import via package so relative imports work)
        registry._load_bundled()

        # 2. Project-level agents
        if project_path:
            project_agents = project_path / ".apptest" / "agents"
            if project_agents.is_dir():
                registry._load_from_directory(project_agents)

        # 3. User-level agents
        user_agents = Path.home() / ".apptest" / "agents"
        if user_agents.is_dir():
            registry._load_from_directory(user_agents)

        return registry

    def _load_bundled(self) -> None:
        """Load bundled agents via normal package imports."""
        package = __name__  # "apptest.agents"
        for py_file in sorted(_BUNDLED_DIR.glob("*_agent.py")):
            module_name = f"{package}.{py_file.stem}"
            try:
                module = importlib.import_module(module_name)
                self._scan_module(module)
            except Exception as exc:
                logger.warning("Failed to load bundled agent %s: %s", module_name, exc)

    def _load_from_directory(self, directory: Path) -> None:
        """Load external ``*_agent.py`` modules from a directory.

        External agents are loaded via ``importlib.util`` so they can live
        outside the package.  The :class:`SetupAgent` base is injected into
        the module's namespace so external agents can ``from apptest.agents.base
        import SetupAgent`` or simply reference the injected name.
        """
        for py_file in sorted(directory.glob("*_agent.py")):
            try:
                spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                # Make SetupAgent available for external agents that import it
                sys.modules.setdefault("apptest.agents.base", sys.modules[__name__])
                spec.loader.exec_module(module)
                self._scan_module(module)
            except Exception as exc:
                logger.warning("Failed to load agent from %s: %s", py_file, exc)

    def _scan_module(self, module) -> None:
        """Find and register all SetupAgent subclasses in a module."""
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, SetupAgent)
                and attr is not SetupAgent
            ):
                instance = attr()
                self._agents[instance.name] = instance

    def dispatch(
        self,
        preconditions: list[dict],
        device,
        context: dict | None = None,
    ) -> list[str]:
        """Execute structured preconditions in order. Return log messages.

        Agents share context — outputs from earlier agents (e.g. ``apk_path``
        from BuildAgent) flow into later agents (e.g. AppAgent.install).
        """
        log: list[str] = []
        shared = dict(context or {})
        for p in preconditions:
            agent_name = p.get("agent", "")
            action = p.get("action", "")
            params = p.get("params", {})

            agent = self._agents.get(agent_name)
            if agent:
                merged = {**shared, **params}
                try:
                    msg = agent.execute(action, device, merged)
                    shared.update(merged)
                    log.append(f"[{agent_name}] {action}: {msg}")
                except Exception as exc:
                    log.append(f"[{agent_name}] {action}: ERROR {exc}")
                    logger.error("Agent %s.%s failed: %s", agent_name, action, exc)
            else:
                log.append(f"[warning] Unknown agent: {agent_name}")
        return log

    def prompt_description(self) -> str:
        """Generate capability text for injection into LLM system prompt."""
        parts = ["Available setup agents (use in preconditions):"]
        for agent in self._agents.values():
            parts.append(agent.describe())
        return "\n".join(parts)
