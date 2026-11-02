"""Grok Bot over its Webhook: the sentence is posted, the answer comes back later.

Submission (dedupe, config check, request ids) is in core/handle/grokBotHandle.py; answers
arrive as files in `reply_dir` (written by the Bot, or by the HTTP callback in
core/api/bot_reply_handler.py), see core/handle/grokBotReply.py. The gateway's waiting.py
asks this module for them and does the waiting screen.
Config: `grok_bot` in .config.yaml (`enabled`, `config_file`: a JSON file with the Webhook
`url` and `token`, `reply_dir`, `reply_wait_seconds`, `approval_hint_seconds`).
"""
import asyncio
import json
from pathlib import Path

from core.gateway.agent import HANDING_OVER, WAITING_FOR_REPLY, Agent, Reply
from core.gateway.agent_session import Activity, AgentSession, Done, Error, ErrorKind, TextDelta
from core.handle import grokBotHandle as bot
from core.handle import grokBotPhrases as phrases
from core.handle import grokBotReply as replies

# Bot replies normally arrive within ~15s; a longer wait is often an approval
# prompt in the Grok UI, which the server cannot see.
APPROVAL_HINT_SECONDS = 30
APPROVAL_HINT = "等待时间较长。\n如果 Grok 界面在请求授权，请在那里确认。"


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
    answers_later = True
    call_names = ("Grok Bot", "Grok")  # without `grok_bot.bot_name`

    def enabled(self, config):
        return bool((config.get("grok_bot") or {}).get("enabled"))

    def bot_name(self, config):
        """The name the Bot has in the Grok app (`grok_bot.bot_name`, e.g. 硬件): its call name."""
        return str((config.get("grok_bot") or {}).get("bot_name") or "").strip()

    def label(self, config):
        name = self.bot_name(config)
        return f"{self.title} · {name}" if name else self.title

    def done_prefix(self, conn):
        return f"{self.bot_name(conn.config) or 'Bot'}做完了："

    def names(self, config):
        name = self.bot_name(config)
        return (name,) if name else self.call_names

    def session(self, conn):
        return GrokWebhookSession(conn)

    # Waiting (core/gateway/waiting.py). The Webhook file is read each time, so editing it
    # takes effect without a restart; a missing or broken file raises and the gateway retries.
    def _webhook(self, conn):
        return json.loads(Path(conn.config.get("grok_bot", {}).get("config_file", "")).read_text(encoding="utf-8"))

    def _device(self, conn):
        return conn.headers.get("device-id", "unknown")

    def watches(self, conn):
        return bool(self._webhook(conn).get("reply_dir"))

    def waiting_since(self, conn):
        webhook = self._webhook(conn)
        return replies.latest_request(webhook["reply_dir"], self._device(conn),
                                      webhook.get("reply_wait_seconds", replies.REPLY_WAIT_SECONDS))

    def next_reply(self, conn):
        directory, device = self._webhook(conn)["reply_dir"], self._device(conn)
        found = replies.next_reply(directory, device)
        if found is not None:
            pending, request_id, text, created = found
            return Reply(request_id, text, created, ref=("first", pending))
        found = replies.next_follow_up(directory, device)
        if found is not None:
            path, request_id, text = found
            return Reply(request_id, "Bot 补充：" + text, ref=("more", path))
        return None

    def delivered(self, conn, reply):
        kind, path = reply.ref
        if kind == "first":
            replies.mark_sent(path, reply.request_id)
        else:
            replies.mark_follow_up_sent(path)

    def slow_hint(self, conn):
        seconds = self._webhook(conn).get("approval_hint_seconds", APPROVAL_HINT_SECONDS)
        return (seconds, APPROVAL_HINT) if seconds else None
