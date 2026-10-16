"""
仅上报聊天记录，不进行记忆总结
"""

from ..base import MemoryProviderBase, logger

TAG = __name__


class MemoryProvider(MemoryProviderBase):
    def __init__(self, config, summary_memory=None):
        super().__init__(config)

    async def save_memory(self, msgs, session_id=None):
        logger.bind(tag=TAG).debug("mem_report_only mode: No memory saving or summarization is performed.")
        return None

    async def query_memory(self, query: str) -> str:
        logger.bind(tag=TAG).debug("mem_report_only mode: No memory query is performed.")
        return ""