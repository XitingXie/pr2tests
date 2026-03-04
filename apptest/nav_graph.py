"""Navigation graph generation and formatting for LLM context."""

import json
import logging
import subprocess
import sys
from collections import deque
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_nav_graph(
    repo_path: str | Path,
    nav_graph_project: str | Path,
    changed_files: list[str] | None = None,
) -> dict:
    """Generate a navigation graph by shelling out to the nav graph CLI.

    Args:
        repo_path: Path to the Android project root.
        nav_graph_project: Path to the Android-navigation-graph project.
        changed_files: Optional list of changed file paths for impact analysis.

    Returns:
        Parsed JSON dict from the CLI output; empty dict on failure.
    """
    nav_graph_project = Path(nav_graph_project)
    script = nav_graph_project / "parse_nav_graph.py"

    if not script.exists():
        logger.warning("Nav graph script not found: %s", script)
        return {}

    cmd = [sys.executable, str(script), str(repo_path)]

    if changed_files:
        cmd += ["--impact", "--diff-files"] + list(changed_files)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Nav graph generation timed out")
        return {}
    except FileNotFoundError:
        logger.warning("Python interpreter not found for nav graph")
        return {}

    if result.returncode != 0:
        logger.warning("Nav graph CLI failed (rc=%d): %s", result.returncode, result.stderr[:500])
        return {}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse nav graph JSON: %s", e)
        return {}


def generate_full_nav_graph(
    repo_path: str | Path,
    nav_graph_project: str | Path,
) -> dict:
    """Generate the full navigation graph (all screens + edges, no impact filtering).

    Calls parse_nav_graph.py WITHOUT --impact to get the complete graph.

    Returns:
        Parsed JSON dict with screens, navigation_edges, summary; empty dict on failure.
    """
    nav_graph_project = Path(nav_graph_project)
    script = nav_graph_project / "parse_nav_graph.py"

    if not script.exists():
        logger.warning("Nav graph script not found: %s", script)
        return {}

    cmd = [sys.executable, str(script), str(repo_path)]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Full nav graph generation timed out")
        return {}
    except FileNotFoundError:
        logger.warning("Python interpreter not found for nav graph")
        return {}

    if result.returncode != 0:
        logger.warning("Full nav graph CLI failed (rc=%d): %s", result.returncode, result.stderr[:500])
        return {}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse full nav graph JSON: %s", e)
        return {}


def build_adjacency_list(full_graph: dict) -> tuple[dict[str, list[dict]], dict[str, str]]:
    """Build an adjacency list and short-name index from the full nav graph.

    Args:
        full_graph: Dict with "screens" and "navigation_edges" keys.

    Returns:
        Tuple of (adjacency, name_index) where:
        - adjacency: {source_id: [{target, method}, ...]}
        - name_index: {short_name: full_id} for name resolution
    """
    adjacency: dict[str, list[dict]] = {}
    name_index: dict[str, str] = {}

    # Build name index from screens
    for screen in full_graph.get("screens", []):
        if isinstance(screen, dict):
            screen_id = screen.get("id", screen.get("screen_name", ""))
            short = screen_id.rsplit(".", 1)[-1] if "." in screen_id else screen_id
            if screen_id:
                name_index[short] = screen_id
                name_index[screen_id] = screen_id  # FQN maps to itself

    # Build adjacency list from edges
    for edge in full_graph.get("navigation_edges", []):
        if not isinstance(edge, dict):
            continue
        source = edge.get("from", edge.get("source", ""))
        target = edge.get("to", edge.get("target", ""))
        method = edge.get("method", edge.get("action", ""))
        if source and target:
            adjacency.setdefault(source, []).append({"target": target, "method": method})

    return adjacency, name_index


def find_launcher(full_graph: dict) -> str | None:
    """Find the launcher screen in the full nav graph.

    Scans screens for is_launcher: True.

    Returns:
        Screen ID of the launcher, or None if not found.
    """
    for screen in full_graph.get("screens", []):
        if isinstance(screen, dict) and screen.get("is_launcher"):
            return screen.get("id", screen.get("screen_name", ""))
    return None


def find_route(
    adjacency: dict[str, list[dict]],
    source: str,
    target: str,
    name_index: dict[str, str],
) -> list[dict] | None:
    """BFS shortest path from source to target.

    Accepts both short names (AboutActivity) and FQN (org.wikipedia.settings.AboutActivity).

    Returns:
        List of {screen, method} steps from source to target, or None if no path.
    """
    # Resolve names to full IDs
    source_id = name_index.get(source, source)
    target_id = name_index.get(target, target)

    if source_id == target_id:
        return []

    # BFS
    visited: set[str] = {source_id}
    queue: deque[tuple[str, list[dict]]] = deque()
    queue.append((source_id, []))

    while queue:
        current, path = queue.popleft()
        for neighbor in adjacency.get(current, []):
            next_id = neighbor["target"]
            if next_id in visited:
                continue
            new_path = path + [{"screen": next_id, "method": neighbor["method"]}]
            if next_id == target_id:
                return new_path
            visited.add(next_id)
            queue.append((next_id, new_path))

    return None


_ONBOARDING_KEYWORDS = ("onboarding", "welcome", "intro", "tutorial", "walkthrough", "initial")


def format_route_context(
    nav_data: dict,
    target_screens: list[str],
    max_chars: int = 3000,
) -> str:
    """Format BFS routes from launcher to each target screen.

    Args:
        nav_data: Dict that may contain "full_graph" with screens/edges.
        target_screens: List of screen names (short or FQN) to route to.
        max_chars: Character budget for output.

    Returns:
        Formatted route context string, or empty string if no full_graph.
    """
    full_graph = nav_data.get("full_graph")
    if not full_graph:
        return ""

    launcher = find_launcher(full_graph)
    if not launcher:
        return ""

    adjacency, name_index = build_adjacency_list(full_graph)

    # Filter out None/empty targets
    targets = [t for t in target_screens if t]
    if not targets:
        return ""

    launcher_short = launcher.rsplit(".", 1)[-1] if "." in launcher else launcher
    parts: list[str] = [
        "## Navigation Routes",
        f"Launcher: {launcher_short}",
    ]
    used = sum(len(p) for p in parts)
    has_onboarding = False

    for target in targets:
        route = find_route(adjacency, launcher, target, name_index)
        if route is None:
            continue

        target_short = target.rsplit(".", 1)[-1] if "." in target else target
        header = f"\nRoute to {target_short}:"
        if used + len(header) > max_chars:
            break

        # Format steps: Launcher → Step1 (method) → Step2 (method) → ...
        step_parts = [launcher_short]
        for step in route:
            screen_short = step["screen"].rsplit(".", 1)[-1] if "." in step["screen"] else step["screen"]
            method = step["method"]
            step_parts.append(f"{screen_short} ({method})" if method else screen_short)

            # Check for onboarding screens in the route
            if any(kw in screen_short.lower() for kw in _ONBOARDING_KEYWORDS):
                has_onboarding = True

        route_line = "  " + " → ".join(step_parts)
        combined = header + "\n" + route_line
        if used + len(combined) > max_chars:
            break

        parts.append(header)
        parts.append(route_line)
        used += len(combined)

    if has_onboarding:
        note = ("\nNote: Route passes through an onboarding/welcome screen. "
                "Include a step to dismiss it (tap 'Skip' or 'Get started').")
        if used + len(note) <= max_chars:
            parts.append(note)

    return "\n".join(parts) if len(parts) > 2 else ""


def format_nav_context(nav_data: dict, max_chars: int = 4000) -> str:
    """Format navigation graph data into concise text for LLM prompts.

    Handles two modes:
    - Impact mode: nav_data has "affected_screens", "suggested_flows", etc.
    - Full graph mode: nav_data has "nodes", "edges", "launcher", etc.

    Returns empty string if no useful data.
    """
    if not nav_data:
        return ""

    parts: list[str] = ["## Navigation Map"]
    used = len(parts[0])

    # --- Impact mode ---
    if "affected_screens" in nav_data:
        affected = nav_data.get("affected_screens", [])
        if affected:
            # affected_screens can be strings or dicts with screen_name
            names = []
            for s in affected:
                if isinstance(s, dict):
                    names.append(s.get("screen_name", s.get("screen", "?")))
                else:
                    names.append(str(s))
            parts.append(f"Affected screens: {', '.join(names)}")
            used += len(parts[-1])

        flows = nav_data.get("suggested_flows", [])
        if flows:
            parts.append("Suggested test flows:")
            for flow in flows:
                if isinstance(flow, list):
                    line = f"  - {' -> '.join(flow)}"
                elif isinstance(flow, dict):
                    path = flow.get("path", [])
                    line = f"  - {' -> '.join(path)}" if path else f"  - {flow}"
                else:
                    line = f"  - {flow}"
                if used + len(line) > max_chars:
                    parts.append("  - ... (truncated)")
                    break
                parts.append(line)
                used += len(line)

        # Include edges to affected screens for navigation paths
        edges = nav_data.get("edges_to_affected", nav_data.get("edges", []))
        if edges and used < max_chars - 200:
            parts.append("Navigation edges to affected screens:")
            for edge in edges:
                if isinstance(edge, dict):
                    src = edge.get("from", edge.get("source", "?"))
                    dst = edge.get("to", edge.get("target", "?"))
                    action = edge.get("action", "")
                    line = f"  - {src} -> {dst}"
                    if action:
                        line += f" ({action})"
                elif isinstance(edge, list) and len(edge) >= 2:
                    line = f"  - {edge[0]} -> {edge[1]}"
                else:
                    line = f"  - {edge}"
                if used + len(line) > max_chars:
                    parts.append("  - ... (truncated)")
                    break
                parts.append(line)
                used += len(line)

        return "\n".join(parts) if len(parts) > 1 else ""

    # --- Full graph mode ---
    launcher = nav_data.get("launcher", "")
    if launcher:
        parts.append(f"Launcher screen: {launcher}")
        used += len(parts[-1])

    nodes = nav_data.get("nodes", [])
    edges = nav_data.get("edges", [])

    if nodes:
        parts.append(f"Screens ({len(nodes)}):")
        for node in nodes:
            if isinstance(node, dict):
                name = node.get("name", node.get("id", "?"))
                ntype = node.get("type", "")
                line = f"  - {name}" + (f" ({ntype})" if ntype else "")
            else:
                line = f"  - {node}"
            if used + len(line) > max_chars:
                remaining = len(nodes) - nodes.index(node)
                parts.append(f"  ... ({remaining} more screens)")
                break
            parts.append(line)
            used += len(line)

    if edges and used < max_chars - 200:
        parts.append("Navigation edges:")
        for edge in edges:
            if isinstance(edge, dict):
                src = edge.get("from", edge.get("source", "?"))
                dst = edge.get("to", edge.get("target", "?"))
                action = edge.get("action", "")
                line = f"  - {src} -> {dst}"
                if action:
                    line += f" ({action})"
            elif isinstance(edge, list) and len(edge) >= 2:
                line = f"  - {edge[0]} -> {edge[1]}"
            else:
                line = f"  - {edge}"
            if used + len(line) > max_chars:
                parts.append("  ... (truncated)")
                break
            parts.append(line)
            used += len(line)

    return "\n".join(parts) if len(parts) > 1 else ""
