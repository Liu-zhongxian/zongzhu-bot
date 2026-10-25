"""Gateway: a sentence from the board goes to the first skill that takes it, else to the current AI.

Config (`gateway` in .config.yaml, optional):

    gateway:
      skills: [local_music]   # tried in this order; [] = none
      agent: grok_bot         # the AI that gets the rest; empty = upstream chat model
      call_names:             # optional: replaces a module's own call names
        grok_bot: [硬件]

Calling an AI by name at the start ("嗨 硬件，帮我……") hands the rest straight to it and makes
it this board's AI from then on (kept in data/agent_sessions.json); the name alone gets "我在。".

Without the section the order is the one before the gateway: local music, then the Bot.
Skills are in core/gateway/skills/ (see skill.py), AIs in core/gateway/agents/ (see agent.py).
"""
import time
import uuid

from core.gateway import agent_store, builtin, status, waiting
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


def agent_call_names(config) -> dict:
    """{AI module name: [call names]} for the AIs that are switched on."""
    custom = (config.get("gateway") or {}).get("call_names")
    custom = custom if isinstance(custom, dict) else {}
    return {name: custom.get(name, agent.names(config)) for name, agent in AGENTS.items() if agent.enabled(config)}


def agent_name(conn):
    """This board's AI: the one it last called by name, else the configured one (None: upstream chat)."""
    chosen = getattr(conn, "gateway_agent", None)
    if chosen is None:
        device = getattr(conn, "device_id", None)
        chosen = conn.gateway_agent = (agent_store.get(device) if device else "") or ""
    agent = AGENTS.get(chosen)
    if agent is not None and agent.enabled(conn.config):
        return chosen
    return _settings(conn.config)[1]


def active_agent(conn):
    """This board's AI when it is known and switched on, else None."""
    agent = AGENTS.get(agent_name(conn))
    return agent if agent is not None and agent.enabled(conn.config) else None


def hotwords(config) -> list:
    names = [word for value in agent_call_names(config).values()
             for word in ([value] if isinstance(value, str) else value or ())]
    return names + [word for skill in active_skills(config) for word in skill.hotwords(config)]


def warm(conn):
    """A board connected: synthesize the fixed replies (AI first), then let each module start up."""
    import asyncio

    from core.handle import grokBotPhrases

    agent = active_agent(conn)
    modules = ([agent] if agent else []) + active_skills(conn.config)
    texts = [text for module in modules for text in module.phrases(conn.config)]
    if texts:
        asyncio.create_task(grokBotPhrases.warm(conn, list(dict.fromkeys(texts))))
    for module in modules:
        module.warm(conn)
    if agent and agent.answers_later:
        waiting.start(conn, agent)


def on_listen(conn):
    waiting.resume_input(conn)
    agent = active_agent(conn)
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
    call = None if kind else _call_name(conn, text)
    if call:
        layer, target, handled = await _answer_call(conn, text, *call)
    else:
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


def _call_name(conn, text):
    """(AI module name, rest) when the sentence starts by calling an AI, else None."""
    from core.gateway.call_names import match_call_name
    from core.handle.grokBotHandle import extract_command, strip_wake_phrase

    command = extract_command(text)
    if not command:
        return None
    wake = getattr(conn, "device_wake_word", None)
    had_wake, rest = strip_wake_phrase(command, [wake] if wake else ())
    return match_call_name(rest if had_wake else command, agent_call_names(conn.config))


async def _answer_call(conn, heard, name, rest):
    agent = AGENTS[name]
    if getattr(conn, "gateway_agent", None) != name:
        conn.gateway_agent = name
        if getattr(conn, "device_id", None):
            agent_store.put(conn.device_id, name)
        conn.logger.bind(tag=TAG).info(f"呼名：这块板子改用 {agent.label(conn.config)}")
        if agent.answers_later:
            waiting.start(conn, agent)
    if rest:
        if await hand_over(conn, agent, rest):
            return "agent", agent.label(conn.config), True
        return "upstream", "上游对话", False
    # Only the name: answer at once, send nothing to the AI
    from core.handle import grokBotPhrases as phrases
    from core.handle.intentHandler import speak_txt
    from core.handle.sendAudioHandle import send_stt_message

    conn.client_abort = False
    conn.sentence_id = uuid.uuid4().hex
    await send_stt_message(conn, heard)
    if not await phrases.speak(conn, phrases.HERE):
        speak_txt(conn, phrases.HERE)
    return "call", agent.label(conn.config), True


async def _route(conn, text):
    skill_names = _settings(conn.config)[0]
    current = agent_name(conn)
    for name in skill_names:
        skill = SKILLS.get(name)
        if skill is None:
            _warn(conn, f"未知技能，已跳过: {name}")
        elif await skill.handle(conn, text):
            return "skill", getattr(skill, "title", "") or name, True
    if current is None:
        return "upstream", "上游对话", False
    agent = AGENTS.get(current)
    if agent is None:
        _warn(conn, f"未知 AI，交给上游对话: {current}")
        return "upstream", "上游对话", False
    if await hand_over(conn, agent, text):
        return "agent", agent.label(conn.config), True
    return "upstream", "上游对话", False
