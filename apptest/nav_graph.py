"""Navigation graph generation and formatting for LLM context."""

import json
import logging
import subprocess
import sys
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
            parts.append(f"Affected screens: {', '.join(affected)}")
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
