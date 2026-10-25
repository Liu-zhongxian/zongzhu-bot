"""The skill and AI this project had before the gateway, wrapped unchanged."""
from core.gateway.skill import Skill


class LocalMusicSkill(Skill):
    name = "local_music"
    title = "点歌"

    async def handle(self, conn, text):
        from core.handle.localCommandHandle import handle_local_command

        return await handle_local_command(conn, text)


async def grok_bot(conn, text):
    from core.handle.grokBotHandle import handle_grok_bot

    return await handle_grok_bot(conn, text)


SKILLS = [LocalMusicSkill()]
AGENTS = {"grok_bot": grok_bot}
