"""G17：网关页面"工作原理"：按现在的配置说明一句话怎么走。只读配置，数字都是配置里的，不是统计。"""
from core.gateway import status


def _selected(config, kind):
    name = (config.get("selected_module") or {}).get(kind) or ""
    return name, (config.get(kind) or {}).get(name) or {}


def view(config) -> dict:
    from core import gateway
    from core.gateway import FILLERS, active_skills
    from core.gateway.xiaoai import server as speaker_server
    from core.utils import asr_text

    vad_name, vad = _selected(config, "VAD")
    asr_name, asr = _selected(config, "ASR")
    tts_name, tts = _selected(config, "TTS")
    silence = vad.get("min_silence_duration_ms")
    agent = gateway.AGENTS.get(gateway._settings(config)[1] or "")  # 默认交给的 AI（板子各自叫过别的名字时以板子为准）
    agent = agent if agent is not None and agent.enabled(config) else None
    skills = [{"name": getattr(s, "title", "") or s.name} for s in active_skills(config)]
    calls = [{"agent": gateway.AGENTS[name].label(config), "names": [names] if isinstance(names, str) else list(names)}
             for name, names in gateway.agent_call_names(config).items()]
    boards = [(info.get("wake"), status.board_name(info.get("type")))
              for info in status._boards.values() if info.get("type") not in status.BRIDGE_TYPES | status.SIMULATED_TYPES]
    speaker = ((config.get("gateway") or {}).get("xiaoai") or {}).get("enabled")
    return {
        "steps": [
            {"icon": "🎙", "name": "收音", "value": vad_name or "—",
             "note": f"静音 {silence / 1000:g} 秒算说完" if isinstance(silence, (int, float)) else ""},
            {"icon": "📝", "name": "识别", "value": asr_name or "—",
             "note": f"类型 {asr.get('type') or asr_name} · {len(asr_text.hotwords_of(config))} 个热词"},
            {"icon": "🧹", "name": "纠错和过滤", "value": f"{len(asr_text.corrections_of(config))} 条纠错",
             "note": "去掉重复的唤醒词；只有语气词（" + "、".join(sorted(FILLERS)[:4]) + "……）的不交"},
            {"icon": "🔀", "name": "分派", "value": "三层，见下", "note": "前一层不接就交给下一层"},
            {"icon": "🔊", "name": "合成和播放", "value": tts_name or "—",
             "note": " · ".join(x for x in (tts.get("voice") or tts.get("private_voice") or "", "常用短句提前合成") if x)},
        ],
        "skills": skills,
        "calls": calls,
        "agent": agent.label(config) if agent else "",
        "boards": sorted({(w or "", n) for w, n in boards}),
        "speaker": {"on": bool(speaker), "wake_words": speaker_server.wake_words(config) if speaker else []},
    }
