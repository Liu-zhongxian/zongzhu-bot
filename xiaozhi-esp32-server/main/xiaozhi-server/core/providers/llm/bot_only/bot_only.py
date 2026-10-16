"""Local fallback for Bot forwarding mode; never creates an API client."""
from core.providers.llm.base import LLMProviderBase


class LLMProvider(LLMProviderBase):
    def __init__(self, config):
        pass

    def response(self, session_id, dialogue, **kwargs):
        yield "请直接说出你要交给 Bot 的事情。"
