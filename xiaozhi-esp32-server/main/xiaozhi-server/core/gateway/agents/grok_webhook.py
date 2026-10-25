"""Grok Bot over its Webhook: the sentence is posted, the answer comes back later.

Submission (dedupe, config check, request ids) is in core/handle/grokBotHandle.py; answers
arrive as files (or the HTTP callback, core/api/bot_reply_handler.py) and are picked up by
the watcher in core/handle/grokBotReply.py, which speaks them through `say_reply`.
Config: `grok_bot` in .config.yaml (`enabled`, `config_file` with the Webhook url and token).
"""
import asyncio

from core.gateway.agent import HANDING_OVER, WAITING_FOR_REPLY, Agent
from core.gateway.agent_session import Activity, AgentSession, Done, Error, ErrorKind, TextDelta
from core.handle import grokBotHandle as bot
from core.handle import grokBotPhrases as phrases


class GrokWebhookSession(AgentSession):
    """Nothing to keep between sentences: the Bot keeps its own conversation."""

    def __init__(self, conn):
        self.conn = conn

    @property
    def session_id(self):
        return None

    async def start(self):
        pass

    async def send(self, text):
        conn = self.conn
        config = conn.config.get("grok_bot", {})
        submission = bot.prepare_submission(text, conn.headers.get("device-id", "unknown"),
                                            config.get("config_file", ""))
        if isinstance(submission, str):
            yield Error(ErrorKind.UNKNOWN, "not submitted", voice=submission)
            return
        posting = asyncio.create_task(bot.post_submission(submission))
        # pending: the Bot was asked to send its answer back, so the board waits for it
        yield Activity(WAITING_FOR_REPLY if submission.pending else HANDING_OVER)
        status, reply = await posting
        if status == "accepted":
            if not submission.pending:
                yield TextDelta(reply)  # the answer stays in the Grok Bot chat
            yield Done()
        else:
            yield Error(ErrorKind.AUTH if status == "rejected" else ErrorKind.UNKNOWN, status, voice=reply)

    async def interrupt(self):
        pass

    async def close(self):
        pass


class GrokWebhookAgent(Agent):
    name = "grok_bot"
    title = "Grok Bot"
    ack = phrases.ACK
    accepted = "任务已提交，Bot 回复后会显示在屏幕上。"

    def enabled(self, config):
        return bool((config.get("grok_bot") or {}).get("enabled"))

    def warm(self, conn):
        from core.handle.grokBotReply import start_reply_watcher

        start_reply_watcher(conn)

    def on_listen(self, conn):
        from core.handle.grokBotReply import resume_bot_input

        resume_bot_input(conn)

    def session(self, conn):
        return GrokWebhookSession(conn)
