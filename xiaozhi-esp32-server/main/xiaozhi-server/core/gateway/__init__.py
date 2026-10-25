"""Gateway: a sentence from the board goes to the first skill that takes it, else to the current AI.

Config (`gateway` in .config.yaml, optional):

    gateway:
      skills: [local_music]   # tried in this order; [] = none
      agent: grok_bot         # the AI that gets the rest; empty = upstream chat model

Without the section the order is the one before the gateway: local music, then the Bot.
"""
import time

from core.gateway import builtin, status
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
    record = status.begin(conn, text)
    kind = status.classify(conn, text)
    layer, target, handled = await _route(conn, text)
    if handled and layer == "agent" and getattr(conn, "bot_ui_waiting", False):
        conn.gateway_wait_since = time.time()
    status.finish(record, kind or layer, {"wake": "唤醒问候", "filter": "不提交"}.get(kind, target))
    return handled


async def _route(conn, text):
    skill_names, agent_name = _settings(conn.config)
    for name in skill_names:
        skill = SKILLS.get(name)
        if skill is None:
            _warn(conn, f"未知技能，已跳过: {name}")
        elif await skill.handle(conn, text):
            return "skill", getattr(skill, "title", "") or name, True
    if agent_name is None:
        return "upstream", "上游对话", False
    agent = AGENTS.get(agent_name)
    if agent is None:
        _warn(conn, f"未知 AI，交给上游对话: {agent_name}")
        return "upstream", "上游对话", False
    if await agent(conn, text):
        return "agent", status.AGENT_NAMES.get(agent_name, agent_name), True
    return "upstream", "上游对话", False
