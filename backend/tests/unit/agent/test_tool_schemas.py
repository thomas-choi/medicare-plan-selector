"""Tool JSON-Schema snapshots; no session id anywhere; strict arguments (DESIGN §6.2, §8.3)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from selector.agent.tools import TOOLS, tool_specs

SNAPSHOT = Path(__file__).resolve().parents[2] / "fixtures" / "tool_schemas.json"
DESIGN_TOOLS = {
    "resolve_location",
    "resolve_drug",
    "lookup_provider",
    "search_plans",
    "filter_plans",
    "estimate_costs",
    "compare_plans",
    "explain_plan",
    "update_canvas",
    "record_feedback",
    # v0.4 addendum A6
    "get_plan_benefits",
}


def _walk(o: Any) -> list[Any]:
    out = [o]
    if isinstance(o, dict):
        for v in o.values():
            out += _walk(v)
    elif isinstance(o, list):
        for v in o:
            out += _walk(v)
    return out


def test_schema_snapshot() -> None:
    specs = {s.name: {"description": s.description, "parameters": s.parameters} for s in tool_specs()}
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.write_text(json.dumps(specs, indent=2, sort_keys=True) + "\n")
    assert specs == json.loads(SNAPSHOT.read_text())


def test_design_tool_set() -> None:
    assert set(TOOLS) == DESIGN_TOOLS


def test_no_session_id_in_any_schema_and_extra_forbidden() -> None:
    for s in tool_specs():
        for node in _walk(s.parameters):
            if isinstance(node, dict) and "properties" in node:
                assert not any("session" in k.lower() for k in node["properties"]), s.name
                assert node.get("additionalProperties") is False, s.name


def test_no_sponsor_or_boost_fields() -> None:
    blob = json.dumps([s.parameters for s in tool_specs()]).lower()
    for word in ("sponsor", "boost", "carrier", "organization", "priority"):
        assert word not in blob


def test_compare_is_bounded_to_five() -> None:
    p = {s.name: s.parameters for s in tool_specs()}
    assert p["compare_plans"]["properties"]["limit"]["maximum"] == 5
    assert p["estimate_costs"]["properties"]["plan_keys"]["maxItems"] == 5
