__all__ = ["ASRService", "SherpaASR"]


def __getattr__(name):
    if name == "ASRService":
        from core.services.audio.asr.service import ASRService

        return ASRService
    if name == "SherpaASR":
        from core.services.audio.asr.sherpa import SherpaASR

        return SherpaASR
    raise AttributeError(name)
