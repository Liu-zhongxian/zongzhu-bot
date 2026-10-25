"""Gateway: a sentence from the board goes to the first skill that takes it, else to the current AI.

Config (`gateway` in .config.yaml, optional):

    gateway:
      skills: [local_music]   # tried in this order; [] = none
      agent: grok_bot         # the AI that gets the rest; empty = upstream chat model

Without the section the order is the one before the gateway: local music, then the Bot.
"""
from core.gateway import builtin
from core.gateway.skill import Skill

TAG = "gateway"
DEFAULT_SKILLS = ["local_music"]
DEFAULT_AGENT = "grok_bot"

SKILLS: dict = {}
AGENTS: dict = {}


def register_skill(skill: Skill):
    SKILLS[skill.name] = skill


def register_agent(name: str, handler):
    """`handler(conn, text) -> bool`; True when the AI took the sentence."""
    AGENTS[name] = handler


for _skill in builtin.SKILLS:
    register_skill(_skill)
for _name, _handler in builtin.AGENTS.items():
    register_agent(_name, _handler)


def _settings(config):
    gateway = config.get("gateway") or {}
    skills = gateway.get("skills", DEFAULT_SKILLS)
    agent = gateway.get("agent", DEFAULT_AGENT)
    return list(skills or []), agent or None


def _warn(conn, message):
    logger = getattr(conn, "logger", None)
    if logger is not None:
        logger.bind(tag=TAG).warning(message)


async def dispatch(conn, text) -> bool:
    """True when a skill or the AI took the sentence; False leaves it to the upstream chat flow."""
    skill_names, agent_name = _settings(conn.config)
    for name in skill_names:
        skill = SKILLS.get(name)
        if skill is None:
            _warn(conn, f"未知技能，已跳过: {name}")
        elif await skill.handle(conn, text):
            return True
    if agent_name is None:
        return False
    agent = AGENTS.get(agent_name)
    if agent is None:
        _warn(conn, f"未知 AI，交给上游对话: {agent_name}")
        return False
    return bool(await agent(conn, text))
