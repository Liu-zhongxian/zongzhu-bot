from core.utils.logger import logger


class XiaoAIConversationController:
    PLAYER_STOP_HEADERS = {"Play", "PlayList", "PushAudio", "Template.PlayInfo"}

    def __init__(self):
        self.continuous_conversation_mode = True
        self.max_listening_retries = 2
        self.exit_command_keywords = ["停止", "退下", "退出", "下去吧"]
        self.exit_prompt = "再见，主人"
        self.continuous_conversation_keywords = ["开启连续对话"]
        self.conversing = False
        self.current_retries = 0

    def apply_runtime_config(self, config: dict):
        self.continuous_conversation_mode = config.get(
            "continuous_conversation_mode", True
        )
        self.max_listening_retries = config.get("max_listening_retries", 2)
        self.exit_command_keywords = config.get(
            "exit_command_keywords", ["停止", "退下", "退出", "下去吧"]
        )
        self.exit_prompt = config.get("exit_prompt", "再见，主人")
        self.continuous_conversation_keywords = config.get(
            "continuous_conversation_keywords", ["开启连续对话"]
        )

    def reset_retries(self):
        self.current_retries = 0

    def is_active(self) -> bool:
        return self.conversing or self.current_retries > 0

    async def handle_text_command(self, text: str, speaker):
        if any(cmd in text for cmd in self.exit_command_keywords):
            if not self.is_active():
                logger.debug(
                    f"[XiaoAI] 忽略退出指令，当前不在小爱连续对话中: {text}"
                )
                return
            logger.info("[XiaoAI] 👋 收到退出指令，立即退出连续对话模式")
            self.stop()
            await speaker.play(text=self.exit_prompt)
            return

        if any(keyword in text for keyword in self.continuous_conversation_keywords):
            logger.info("[XiaoAI] 👋 收到开启连续对话指令，开启连续对话模式")
            self.conversing = True

    async def handle_listening_timeout(self, speaker):
        if not (
            self.continuous_conversation_mode
            and self.conversing
            and self.current_retries > 0
        ):
            return

        if self.current_retries < self.max_listening_retries:
            self.current_retries += 1
            logger.info(
                f"[XiaoAI] 🔄 重新唤醒小爱继续监听 "
                f"({self.current_retries}/{self.max_listening_retries})"
            )
            await speaker.wake_up(awake=True, silent=True)
            return

        logger.info(
            f"[XiaoAI] 💤 达到重试上限({self.max_listening_retries}次)，退出连续对话模式"
        )
        self.stop()
        await speaker.play(text=self.exit_prompt)

    def handle_audio_player_instruction(self, header_name: str):
        if not self.is_active():
            logger.debug(
                f"[XiaoAI] 忽略播放器指令 {header_name}，当前不在小爱连续对话中"
            )
            return

        if header_name in self.PLAYER_STOP_HEADERS:
            logger.info(
                f"[XiaoAI] 收到播放器指令 {header_name}，退出小爱连续对话模式"
            )
            self.stop()
            return

        logger.debug(
            f"[XiaoAI] 忽略 AudioPlayer 事件，避免误退出小爱连续对话: {header_name}"
        )

    async def handle_playing_status(self, playing_status: str, speaker):
        if not (
            self.continuous_conversation_mode
            and playing_status == "idle"
            and self.conversing
        ):
            return

        await speaker.wake_up(awake=True, silent=False)
        self.current_retries = 1
        logger.info(
            f"[XiaoAI] 首次进入连续对话模式 "
            f"({self.current_retries}/{self.max_listening_retries})"
        )
        logger.info("[XiaoAI] 🎯 TTS播放完毕，重新唤醒小爱等待下一句...")

    def stop(self):
        if not self.is_active():
            return

        logger.info("[XiaoAI] 停止小爱连续对话")
        self.conversing = False
        self.current_retries = 0
