class Skill:
    """A fixed phrase done on this Mac (music, volume), without any AI.

    `handle` returns True when it took the sentence; False passes it on to the next
    skill and finally to the current AI. Each skill checks its own config switch.
    """

    name = ""

    async def handle(self, conn, text: str) -> bool:
        raise NotImplementedError
