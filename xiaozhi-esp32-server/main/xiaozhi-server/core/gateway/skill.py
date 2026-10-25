class Skill:
    """A fixed phrase done on this Mac (music, volume), without any AI.

    `handle` returns True when it took the sentence; False passes it on to the next
    skill and finally to the current AI. Each skill checks its own config switch.
    The other methods are optional; the gateway collects them from the skills that are on.
    """

    name = ""
    title = ""  # shown on the gateway page

    def enabled(self, config) -> bool:
        return True

    def hotwords(self, config) -> list:
        """Words the speech recognition should favour (only some recognisers use them)."""
        return []

    def phrases(self, config) -> tuple:
        """Fixed replies synthesized when a board connects, so they play at once."""
        return ()

    def warm(self, conn):
        """A board connected: start whatever the skill needs in the background."""

    def on_listen(self, conn):
        """The board started listening (button or wake word)."""

    async def handle(self, conn, text: str) -> bool:
        raise NotImplementedError
