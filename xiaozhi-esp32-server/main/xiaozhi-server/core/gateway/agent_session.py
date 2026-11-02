"""Agent 会话的统一接口。

复制自 justhalfbit/xiaozhi-hub-server `main/xiaozhi-server/core/agent/agent_session.py`
（commit adb936d，MIT），内容未改，只加了这段来源说明。本项目怎么用见 core/gateway/agent.py。

上层（LLM provider）只关心三件事：发一句话拿回一段段文字、打断、关闭。
Claude 用 claude-agent-sdk 实现，Grok Bot 用云端网关实现，以后的 Codex 用 app-server 实现，都遵循这里的接口和事件。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator, Optional, Union


class ErrorKind(str, Enum):
    NOT_INSTALLED = "not_installed"
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    BILLING = "billing"
    SERVER = "server"
    SESSION_MISSING = "session_missing"
    PROCESS_EXITED = "process_exited"
    TIMEOUT = "timeout"
    STALLED = "stalled"
    UNKNOWN = "unknown"


# 出错时播报给用户的话，保持简短口语化
VOICE_ERROR_MESSAGES = {
    ErrorKind.NOT_INSTALLED: "电脑上没有找到 Claude Code，请先安装并登录。",
    ErrorKind.AUTH: "Claude Code 还没登录或者登录过期了，请在电脑上重新登录。",
    ErrorKind.RATE_LIMIT: "Claude 现在用量到上限了，稍后再试吧。",
    ErrorKind.BILLING: "Claude 的账户额度好像不够了，请检查一下账户。",
    ErrorKind.SERVER: "Claude 那边暂时有点问题，稍后再试吧。",
    ErrorKind.SESSION_MISSING: "没有找到之前的对话，我们重新开始吧。",
    ErrorKind.PROCESS_EXITED: "Claude Code 意外退出了，再说一次试试。",
    ErrorKind.TIMEOUT: "这件事做得太久，我先停下了。想接着做的话，跟我说继续就行。",
    ErrorKind.STALLED: "Claude 那边一直没有回应，可能是网络或服务有点慢，我先停下了。稍后跟我说继续，就能接着做。",
    ErrorKind.UNKNOWN: "出了点小问题，再说一次试试。",
}


@dataclass
class TextDelta:
    text: str


@dataclass
class Activity:
    """Agent 仍在工作（思考、调用工具等），但没有产出要读出来的文字。用于判断是否卡住。

    tools_running：正在执行、还没返回结果的工具数；-1 表示不知道。工具执行期间（例如跑一条很慢的命令）
    Agent 可能很久没有任何事件，这不算卡住。

    label 在 STARTING_LABELS 里时，表示会话已经建好、但 Agent 还没开始干活（刚启动、请求被限流或过载正在重试）。
    这之后直接出错，就是"还没开始干活就出错"（没登录、额度用完、重试用完等）。
    """

    label: str = ""
    tools_running: int = -1


# 还没开始干活的 Activity：init 是会话刚启动，api_retry 是请求被限流或过载、正在重试
STARTING_LABELS = ("init", "api_retry")


@dataclass
class Done:
    session_id: Optional[str] = None
    interrupted: bool = False


@dataclass
class Error:
    kind: ErrorKind
    detail: str = ""
    voice: str = ""  # 播报给用户的话；留空用上面 Claude 的默认文案（其他 Agent 传自己的）

    @property
    def voice_message(self) -> str:
        return self.voice or VOICE_ERROR_MESSAGES.get(self.kind, VOICE_ERROR_MESSAGES[ErrorKind.UNKNOWN])


AgentEvent = Union[TextDelta, Activity, Done, Error]


class AgentSessionError(Exception):
    def __init__(self, kind: ErrorKind, detail: str = ""):
        super().__init__(detail or kind.value)
        self.kind = kind
        self.detail = detail


class AgentSession(ABC):
    """一个常驻的 Agent 进程及其对话上下文。所有方法都在同一个事件循环里调用。"""

    @property
    @abstractmethod
    def session_id(self) -> Optional[str]:
        """可用于以后接续（resume）的会话 ID；还没产生时为 None。"""

    @abstractmethod
    async def start(self) -> None:
        """启动进程。接续的会话不存在时抛出 AgentSessionError(SESSION_MISSING)。"""

    @abstractmethod
    def send(self, text: str) -> AsyncIterator[AgentEvent]:
        """发送一句用户消息，产出若干 TextDelta，最后以 Done 或 Error 结束。"""

    @abstractmethod
    async def interrupt(self) -> None:
        """打断当前回答；进程和上下文保留。"""

    @abstractmethod
    async def close(self) -> None:
        """结束进程。"""
