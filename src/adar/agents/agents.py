import json
import logging
from pathlib import Path

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools import FunctionTool

from src.adar.config import settings
from domains.arcl.tools import TOOL_REGISTRY

logger = logging.getLogger(__name__)


def load_config() -> dict:
    config_path = Path(__file__).parent / "agents_config.json"
    with open(config_path) as f:
        return json.load(f)


def build_agent(agent_config: dict, model: str, all_agents: dict) -> LlmAgent:
    """Build a single LlmAgent from its config block."""
    tool_names = agent_config.get("tools", [])
    tools = []
    for name in tool_names:
        fn = TOOL_REGISTRY.get(name)
        if fn:
            tools.append(FunctionTool(fn))
        else:
            logger.warning(f"Tool '{name}' not found in TOOL_REGISTRY")

    sub_agent_names = agent_config.get("sub_agents", [])
    sub_agents = [all_agents[n] for n in sub_agent_names if n in all_agents]

    return LlmAgent(
        name=agent_config["name"],
        model=agent_config.get("model", model),
        instruction=agent_config["instruction"],
        tools=tools,
        sub_agents=sub_agents,
    )


def build_arcl_orchestrator() -> LlmAgent:
    """Build the full ARCL agent tree and return the root orchestrator."""
    config = load_config()
    model = config.get("default_model", settings.ADK_MODEL)
    agents_config = config["agents"]

    built: dict[str, LlmAgent] = {}

    # Build leaf agents first (no sub_agents), then orchestrators
    leaf_names = [
        a["name"] for a in agents_config
        if not a.get("sub_agents")
    ]
    orchestrator_names = [
        a["name"] for a in agents_config
        if a.get("sub_agents")
    ]

    for agent_def in agents_config:
        if agent_def["name"] in leaf_names:
            built[agent_def["name"]] = build_agent(agent_def, model, built)

    for agent_def in agents_config:
        if agent_def["name"] in orchestrator_names:
            built[agent_def["name"]] = build_agent(agent_def, model, built)

    root_name = config.get("root_agent", orchestrator_names[0] if orchestrator_names else leaf_names[0])
    return built[root_name]
