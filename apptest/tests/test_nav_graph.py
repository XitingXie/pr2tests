"""Tests for nav_graph routing functions."""

from apptest.nav_graph import (
    build_adjacency_list,
    find_launcher,
    find_route,
    format_route_context,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FULL_GRAPH = {
    "screens": [
        {"id": "org.example.MainActivity", "is_launcher": True},
        {"id": "org.example.MainFragment"},
        {"id": "org.example.OnboardingActivity"},
        {"id": "org.example.SettingsActivity"},
        {"id": "org.example.AboutActivity"},
    ],
    "navigation_edges": [
        {"from": "org.example.MainActivity", "to": "org.example.MainFragment", "method": "fragment"},
        {"from": "org.example.MainActivity", "to": "org.example.OnboardingActivity", "method": "startActivity"},
        {"from": "org.example.MainFragment", "to": "org.example.SettingsActivity", "method": "startActivity"},
        {"from": "org.example.SettingsActivity", "to": "org.example.AboutActivity", "method": "startActivity"},
    ],
}


# ---------------------------------------------------------------------------
# build_adjacency_list
# ---------------------------------------------------------------------------


def test_build_adjacency_list_basic():
    adj, idx = build_adjacency_list(FULL_GRAPH)
    assert "org.example.MainActivity" in adj
    assert len(adj["org.example.MainActivity"]) == 2
    # Name index maps short names
    assert idx["MainActivity"] == "org.example.MainActivity"
    assert idx["AboutActivity"] == "org.example.AboutActivity"


def test_build_adjacency_list_empty():
    adj, idx = build_adjacency_list({})
    assert adj == {}
    assert idx == {}


# ---------------------------------------------------------------------------
# find_launcher
# ---------------------------------------------------------------------------


def test_find_launcher():
    assert find_launcher(FULL_GRAPH) == "org.example.MainActivity"


def test_find_launcher_missing():
    graph = {"screens": [{"id": "SomeScreen"}]}
    assert find_launcher(graph) is None


def test_find_launcher_empty():
    assert find_launcher({}) is None


# ---------------------------------------------------------------------------
# find_route
# ---------------------------------------------------------------------------


def test_find_route_direct():
    adj, idx = build_adjacency_list(FULL_GRAPH)
    route = find_route(adj, "MainActivity", "MainFragment", idx)
    assert route is not None
    assert len(route) == 1
    assert route[0]["screen"] == "org.example.MainFragment"
    assert route[0]["method"] == "fragment"


def test_find_route_multi_hop():
    adj, idx = build_adjacency_list(FULL_GRAPH)
    route = find_route(adj, "MainActivity", "AboutActivity", idx)
    assert route is not None
    assert len(route) == 3
    assert route[0]["screen"] == "org.example.MainFragment"
    assert route[1]["screen"] == "org.example.SettingsActivity"
    assert route[2]["screen"] == "org.example.AboutActivity"


def test_find_route_no_path():
    adj, idx = build_adjacency_list(FULL_GRAPH)
    # No edge back from AboutActivity to anything
    route = find_route(adj, "AboutActivity", "MainActivity", idx)
    assert route is None


def test_find_route_same_node():
    adj, idx = build_adjacency_list(FULL_GRAPH)
    route = find_route(adj, "MainActivity", "MainActivity", idx)
    assert route == []


def test_find_route_fqn():
    adj, idx = build_adjacency_list(FULL_GRAPH)
    route = find_route(adj, "org.example.MainActivity", "org.example.SettingsActivity", idx)
    assert route is not None
    assert len(route) == 2


def test_find_route_handles_cycles():
    graph = {
        "screens": [
            {"id": "A", "is_launcher": True},
            {"id": "B"},
            {"id": "C"},
        ],
        "navigation_edges": [
            {"from": "A", "to": "B", "method": "nav"},
            {"from": "B", "to": "C", "method": "nav"},
            {"from": "C", "to": "A", "method": "nav"},  # cycle
        ],
    }
    adj, idx = build_adjacency_list(graph)
    route = find_route(adj, "A", "C", idx)
    assert route is not None
    assert len(route) == 2


# ---------------------------------------------------------------------------
# format_route_context
# ---------------------------------------------------------------------------


def test_format_route_context_basic():
    nav_data = {"full_graph": FULL_GRAPH}
    result = format_route_context(nav_data, ["SettingsActivity"])
    assert "## Navigation Routes" in result
    assert "Launcher: MainActivity" in result
    assert "Route to SettingsActivity:" in result
    assert "MainActivity" in result
    assert "MainFragment" in result


def test_format_route_context_with_onboarding():
    nav_data = {"full_graph": FULL_GRAPH}
    result = format_route_context(nav_data, ["OnboardingActivity"])
    assert "onboarding" in result.lower()
    assert "dismiss" in result.lower() or "Skip" in result


def test_format_route_context_no_full_graph():
    nav_data = {"affected_screens": [{"screen_name": "Foo"}]}
    result = format_route_context(nav_data, ["Foo"])
    assert result == ""


def test_format_route_context_no_targets():
    nav_data = {"full_graph": FULL_GRAPH}
    result = format_route_context(nav_data, [])
    assert result == ""


def test_format_route_context_none_targets_filtered():
    nav_data = {"full_graph": FULL_GRAPH}
    result = format_route_context(nav_data, [None, "", "SettingsActivity"])
    assert "Route to SettingsActivity:" in result


def test_format_route_context_unreachable_target():
    graph = {
        "screens": [
            {"id": "Launcher", "is_launcher": True},
            {"id": "Isolated"},
        ],
        "navigation_edges": [],
    }
    nav_data = {"full_graph": graph}
    result = format_route_context(nav_data, ["Isolated"])
    # No route found, so no output beyond header
    assert result == ""


def test_format_route_context_respects_max_chars():
    nav_data = {"full_graph": FULL_GRAPH}
    result = format_route_context(nav_data, ["AboutActivity"], max_chars=50)
    # Should be truncated — won't fit full route
    assert len(result) <= 100  # some slack for header
