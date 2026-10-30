"""Sherpa-ONNX offline ASR with configurable model backend.

Provides local speech-to-text recognition for the OpenClaw conversation flow.
The model is lazily loaded on first use to avoid blocking startup.

Supported backends (set via APP_CONFIG["asr"]["model"]):
  - "sense_voice" (default): SenseVoice multilingual model
  - "paraformer": Paraformer Chinese model
  - "fire_red_asr": FireRedASR AED model
"""

import os

import numpy as np
import sherpa_onnx

from core.utils.config import ConfigManager
from core.utils.file import get_model_file_path
from core.utils.logger import logger

_BACKENDS = {
    "sense_voice": {
        "dir_keyword": "sense-voice",
        "factory": "from_sense_voice",
        "extra_kwargs": {"language": "auto", "use_itn": True},
        "model_files": {"model": {True: "model.int8.onnx", False: "model.onnx"}},
    },
    "paraformer": {
        "dir_keyword": "paraformer",
        "factory": "from_paraformer",
        "extra_kwargs": {},
        "model_files": {"paraformer": {True: "model.int8.onnx", False: "model.onnx"}},
    },
    "fire_red_asr": {
        "dir_keyword": "fire-red-asr",
        "factory": "from_fire_red_asr",
        "extra_kwargs": {},
        "model_files": {
            "encoder": {True: "encoder.int8.onnx", False: "encoder.onnx"},
            "decoder": {True: "decoder.int8.onnx", False: "decoder.onnx"},
        },
    },
}


class _SherpaASR:
    """Wrapper around sherpa_onnx.OfflineRecognizer with configurable backend."""

    def __init__(self):
        self._recognizer = None

    def _get_backend(self) -> str:
        cfg = ConfigManager.instance()
        backend = cfg.get_app_config("asr.model", "sense_voice")
        if backend not in _BACKENDS:
            raise ValueError(
                f"Unknown ASR model '{backend}'. "
                f"Supported: {', '.join(_BACKENDS)}"
            )
        return backend

    def _use_int8(self) -> bool:
        cfg = ConfigManager.instance()
        return cfg.get_app_config("asr.int8", True)

    def _get_required_model_files(self, backend: str) -> dict[str, str]:
        spec = _BACKENDS[backend]
        use_int8 = self._use_int8()
        return {
            arg_name: filenames[use_int8]
            for arg_name, filenames in spec["model_files"].items()
        }

    def _dir_has_required_files(self, path: str, required_files: dict[str, str]) -> bool:
        return all(
            os.path.isfile(os.path.join(path, filename))
            for filename in required_files.values()
        )

    def _find_model_dir(self, keyword: str, required_files: dict[str, str]) -> str:
        """Scan core/models/ for a directory matching the backend keyword."""
        models_root = get_model_file_path("")
        cfg = ConfigManager.instance()
        model_dir_name = cfg.get_app_config("asr.model_dir")

        # If model_dir is explicitly configured, use it directly
        if model_dir_name:
            explicit_path = os.path.join(models_root, model_dir_name)
            if self._dir_has_required_files(explicit_path, required_files):
                return explicit_path
            missing = [
                filename
                for filename in required_files.values()
                if not os.path.isfile(os.path.join(explicit_path, filename))
            ]
            raise FileNotFoundError(
                f"Configured model_dir '{model_dir_name}' not found or missing "
                f"required files {missing} in {models_root}."
            )

        # Otherwise, scan for first matching directory
        for entry in os.scandir(models_root):
            if entry.is_dir() and keyword in entry.name:
                if self._dir_has_required_files(entry.path, required_files):
                    return entry.path

        raise FileNotFoundError(
            f"No '{keyword}' model found in {models_root}. "
            f"Please place the matching model directory under core/models/ with files: "
            f"{', '.join(required_files.values())}."
        )

    def _ensure_loaded(self):
        """Lazily initialize the OfflineRecognizer on first use."""
        if self._recognizer is not None:
            return

        backend = self._get_backend()
        spec = _BACKENDS[backend]
        required_files = self._get_required_model_files(backend)

        model_dir = self._find_model_dir(spec["dir_keyword"], required_files)
        model_kwargs = {
            arg_name: os.path.join(model_dir, filename)
            for arg_name, filename in required_files.items()
        }
        tokens_path = os.path.join(model_dir, "tokens.txt")

        if not os.path.isfile(tokens_path):
            raise FileNotFoundError(
                f"Missing tokens.txt in model dir: {model_dir}"
            )

        # Build homophone replacer kwargs if files exist
        hr_kwargs = {}
        models_root = get_model_file_path("")
        hr_dict = os.path.join(models_root, "dict")
        hr_fst = os.path.join(models_root, "replace.fst")
        hr_lexicon = os.path.join(models_root, "lexicon.txt")
        if os.path.isdir(hr_dict) and os.path.isfile(hr_fst):
            hr_kwargs["hr_dict_dir"] = hr_dict
            hr_kwargs["hr_rule_fsts"] = hr_fst
            if os.path.isfile(hr_lexicon):
                hr_kwargs["hr_lexicon"] = hr_lexicon

        factory = getattr(sherpa_onnx.OfflineRecognizer, spec["factory"])
        self._recognizer = factory(
            **model_kwargs,
            tokens=tokens_path,
            num_threads=2,
            debug=False,
            provider="cpu",
            **spec["extra_kwargs"],
            **hr_kwargs,
        )
        logger.asr_event(
            "语音识别服务启动",
            f"模型={backend}, 路径={model_dir}, int8={self._use_int8()}",
        )

    def asr(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        """Recognize speech from raw PCM int16 audio bytes.

        Args:
            pcm_bytes: Raw PCM audio data (int16, mono).
            sample_rate: Sample rate of the audio (default 16000).

        Returns:
            Recognized text string, or empty string if nothing recognized.
        """
        self._ensure_loaded()

        samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        samples = samples.astype(np.float32) / 32768.0

        stream = self._recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        self._recognizer.decode_stream(stream)

        text = stream.result.text.strip()

        # Apply custom text replacements from config
        if text:
            cfg = ConfigManager.instance()
            replacements = cfg.get_app_config("asr.replacements", {})
            for old, new in replacements.items():
                text = text.replace(old, new)
            logger.debug(f"[ASR] Recognized: {text}", module="ASR")
        else:
            logger.debug("[ASR] No speech recognized", module="ASR")
        return text


SherpaASR = _SherpaASR()
