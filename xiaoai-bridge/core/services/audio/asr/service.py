"""ASR provider selector."""

from core.services.audio.asr.doubao import DoubaoASR
from core.services.audio.asr.sherpa import SherpaASR
from core.utils.config import ConfigManager


class _ASRService:
    """Dispatch ASR requests to local Sherpa models or Doubao cloud ASR."""

    DOUBAO_MODEL = "doubao"

    def _model(self) -> str:
        model = ConfigManager.instance().get_app_config("asr.model", "sense_voice")
        return str(model).strip().lower()

    def uses_doubao(self) -> bool:
        return self._model() == self.DOUBAO_MODEL

    def should_warmup_local_model(self) -> bool:
        return not self.uses_doubao()

    def ensure_loaded(self) -> None:
        if self.should_warmup_local_model():
            SherpaASR._ensure_loaded()

    def asr(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        if self.uses_doubao():
            return DoubaoASR.asr(pcm_bytes, sample_rate=sample_rate)
        return SherpaASR.asr(pcm_bytes, sample_rate=sample_rate)


ASRService = _ASRService()
