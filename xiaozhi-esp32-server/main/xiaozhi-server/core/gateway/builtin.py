"""The skill and AI this project had before the gateway."""
from core.gateway.skills.music import MusicSkill


async def grok_bot(conn, text):
    from core.handle.grokBotHandle import handle_grok_bot

    return await handle_grok_bot(conn, text)


SKILLS = [MusicSkill()]
AGENTS = {"grok_bot": grok_bot}
