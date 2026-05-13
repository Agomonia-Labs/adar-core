"""
src/adar/agents/agents.py
=========================
CHANGE FROM ORIGINAL — only two lines near the top:

  BEFORE:
    _CONFIG_PATH = pathlib.Path(__file__).parent / "agents_config.json"

  AFTER:
    _DOMAIN      = os.getenv("DOMAIN", "arcl")
    _CONFIG_PATH = pathlib.Path(__file__).parent / f"agents_config.{_DOMAIN}.json"

Also rename the existing agents_config.json  →  agents_config.arcl.json
so ARCL continues to work with no other changes.

Everything else in this file stays exactly as it was in the original.
"""

import importlib
import json
import os
import pathlib

# ── CHANGED: domain-aware config path ────────────────────────────────────────
_DOMAIN      = os.getenv("DOMAIN", "arcl")
_CONFIG_PATH = pathlib.Path(__file__).parent / f"agents_config.{_DOMAIN}.json"


def _load_tool_registry() -> dict:
    """Import TOOL_REGISTRY from the active domain's tools package."""
    module = importlib.import_module(f"domains.{_DOMAIN}.tools")
    return module.TOOL_REGISTRY


def build_agents():
    """
    Parse agents_config.{DOMAIN}.json and instantiate ADK agents.
    Returns (orchestrator_agent, all_agents_list).
    The body of this function is unchanged from the original.
    """
    from google.adk.agents import LlmAgent
    from google.genai import types as _genai_types


    # Geetabitan needs high max_output_tokens — full songs can be 2000+ tokens
    _gen_cfg = _genai_types.GenerateContentConfig(
        max_output_tokens=8192,
        temperature=0.2,
    ) if _DOMAIN == "geetabitan" else None

    config   = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    registry = _load_tool_registry()
    agent_map: dict = {}

    # First pass — leaf agents (tools, no sub_agents)
    for spec in config["agents"]:
        if "tools" in spec and "sub_agents" not in spec:
            tools = [registry[t] for t in spec["tools"] if t in registry]
            agent_map[spec["name"]] = LlmAgent(
                name=spec["name"],
                instruction=spec["instruction"],
                tools=tools,
                **( {"generate_content_config": _gen_cfg} if _gen_cfg else {} ),
            )

    # Second pass — orchestrator agents (sub_agents, no tools)
    for spec in config["agents"]:
        if "sub_agents" in spec:
            subs = [agent_map[n] for n in spec["sub_agents"] if n in agent_map]
            agent_map[spec["name"]] = LlmAgent(
                name=spec["name"],
                instruction=spec["instruction"],
                sub_agents=subs,
                **( {"generate_content_config": _gen_cfg} if _gen_cfg else {} ),
            )

    orchestrator = next(
        (a for name, a in agent_map.items() if name.endswith("_orchestrator")),
        list(agent_map.values())[0],
    )
    return orchestrator, list(agent_map.values())