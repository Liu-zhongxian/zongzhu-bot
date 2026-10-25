"""Gateway: a sentence from the board goes to the first skill that takes it, else to the current AI.

Config (`gateway` in .config.yaml, optional):

    gateway:
      skills: [local_music]   # tried in this order; [] = none
      agent: grok_bot         # the AI that gets the rest; empty = upstream chat model

Without the section the order is the one before the gateway: local music, then the Bot.
Skills are in core/gateway/skills/ (see skill.py), AIs in core/gateway/agents/ (see agent.py).
"""
import time

from core.gateway import builtin, status
from core.gateway.agent import Agent, hand_over
from core.gateway.skill import Skill

TAG = "gateway"
DEFAULT_SKILLS = ["local_music"]
DEFAULT_AGENT = "grok_bot"

SKILLS: dict = {}
AGENTS: dict = {}


def register_skill(skill: Skill):
    SKILLS[skill.name] = skill


def register_agent(agent: Agent):
    AGENTS[agent.name] = agent
    status.AGENT_NAMES[agent.name] = agent.title or agent.name


for _skill in builtin.SKILLS:
    register_skill(_skill)
for _agent in builtin.AGENTS:
    register_agent(_agent)


def _settings(config):
    gateway = config.get("gateway") or {}
    skills = gateway.get("skills", DEFAULT_SKILLS)
    agent = gateway.get("agent", DEFAULT_AGENT)
    return list(skills or []), agent or None


def active_skills(config):
    """The skills in the configured order that are switched on; unknown names are left out."""
    skills = (SKILLS.get(name) for name in _settings(config)[0])
    return [skill for skill in skills if skill is not None and skill.enabled(config)]


def active_agent(config):
    """The configured AI when it is known and switched on, else None."""
    agent = AGENTS.get(_settings(config)[1])
    return agent if agent is not None and agent.enabled(config) else None


def hotwords(config) -> list:
    return [word for skill in active_skills(config) for word in skill.hotwords(config)]


def warm(conn):
    """A board connected: synthesize the fixed replies (AI first), then let each module start up."""
    import asyncio

    from core.handle import grokBotPhrases

    agent = active_agent(conn.config)
    modules = ([agent] if agent else []) + active_skills(conn.config)
    texts = [text for module in modules for text in module.phrases(conn.config)]
    if texts:
        asyncio.create_task(grokBotPhrases.warm(conn, list(dict.fromkeys(texts))))
    for module in modules:
        module.warm(conn)


def on_listen(conn):
    agent = active_agent(conn.config)
    for module in ([agent] if agent else []) + active_skills(conn.config):
        module.on_listen(conn)


def _warn(conn, message):
    logger = getattr(conn, "logger", None)
    if logger is not None:
        logger.bind(tag=TAG).warning(message)


async def dispatch(conn, text) -> bool:
    """True when a skill or the AI took the sentence; False leaves it to the upstream chat flow."""
    record = status.begin(conn, text)
    kind = status.classify(conn, text)
    conn.gateway_not_sent = None
    layer, target, handled = await _route(conn, text)
    if handled and layer == "agent" and getattr(conn, "bot_ui_waiting", False):
        conn.gateway_wait_since = time.time()
    if kind == "wake":
        # Upstream greets with a stand-in sentence ("嘿，你好呀"); show the word the board heard
        record["text"] = getattr(conn, "device_wake_word", None) or text
    if kind:
        layer, target = kind, {"wake": "唤醒问候", "filter": "不提交"}[kind]
    elif layer == "agent" and conn.gateway_not_sent:
        # The AI took the sentence but did not send it (a repeat within 30s, missing config...)
        layer, target = "filter", status.not_sent_reason(conn.gateway_not_sent)
    status.finish(record, layer, target)
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
    if await hand_over(conn, agent, text):
        return "agent", agent.title or agent_name, True
    return "upstream", "上游对话", False
