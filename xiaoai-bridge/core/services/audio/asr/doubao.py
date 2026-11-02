"""Doubao Volcano Engine ASR provider.

This provider keeps the same input contract as the local Sherpa ASR:
raw PCM int16 mono bytes in, recognized text out.
"""

import base64
import io
import time
import uuid
import wave
from typing import Any

from core.utils.logger import logger


class _DoubaoASR:
    """Volcano Engine Doubao recorded-file ASR client."""

    STANDARD_SUBMIT_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
    STANDARD_QUERY_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
    FLASH_RECOGNIZE_URL = (
        "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash"
    )

    VALID_MODES = {"standard", "flash"}

    def _cfg(self, key: str, default: Any = None) -> Any:
        from core.utils.config import ConfigManager

        return ConfigManager.instance().get_app_config(f"asr.doubao.{key}", default)

    def _mode(self) -> str:
        mode = str(self._cfg("mode", "standard")).strip().lower()
        if mode not in self.VALID_MODES:
            raise ValueError(
                f"Unknown asr.doubao.mode={mode!r}. Supported: standard, flash"
            )
        return mode

    def _timeout(self, key: str, default: float) -> float:
        try:
            return float(self._cfg(key, default))
        except (TypeError, ValueError):
            return default

    def _headers(self, request_id: str, include_sequence: bool = False) -> dict[str, str]:
        app_key = str(self._cfg("app_key", "")).strip()
        access_key = str(self._cfg("access_key", "")).strip()
        resource_id = str(self._cfg("resource_id", "")).strip()

        if not app_key:
            raise ValueError("Missing asr.doubao.app_key")
        if not access_key:
            raise ValueError("Missing asr.doubao.access_key")
        if not resource_id:
            raise ValueError("Missing asr.doubao.resource_id")

        headers = {
            "Content-Type": "application/json",
            "X-Api-App-Key": app_key,
            "X-Api-Access-Key": access_key,
            "X-Api-Resource-Id": resource_id,
            "X-Api-Request-Id": request_id,
        }
        if include_sequence:
            headers["X-Api-Sequence"] = "-1"
        return headers

    def _build_audio(self, pcm_bytes: bytes, sample_rate: int) -> dict[str, Any]:
        wav_bytes = self._pcm_to_wav(pcm_bytes, sample_rate)
        audio: dict[str, Any] = {
            "format": "wav",
            "data": base64.b64encode(wav_bytes).decode("ascii"),
        }

        language = str(self._cfg("language", "") or "").strip()
        if language:
            audio["language"] = language
        return audio

    @staticmethod
    def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_bytes)
        return buffer.getvalue()

    def _build_payload(self, pcm_bytes: bytes, sample_rate: int) -> dict[str, Any]:
        return {
            "user": {"uid": str(self._cfg("uid", self._cfg("app_key", "")))},
            "audio": self._build_audio(pcm_bytes, sample_rate),
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
            },
        }

    @staticmethod
    def _header_status(response: Any) -> tuple[str, str, str]:
        return (
            response.headers.get("X-Api-Status-Code", ""),
            response.headers.get("X-Api-Message", ""),
            response.headers.get("X-Tt-Logid", ""),
        )

    def _raise_for_api_error(self, response: Any, action: str) -> None:
        status_code, message, logid = self._header_status(response)
        body = response.text[:500] if response.text else ""
        raise RuntimeError(
            f"Doubao ASR {action} failed: http={response.status_code}, "
            f"status={status_code}, message={message}, logid={logid}, body={body}"
        )

    def _extract_text(self, data: dict[str, Any]) -> str:
        result = data.get("result")
        if isinstance(result, dict):
            text = result.get("text")
            if isinstance(text, str):
                return text.strip()
        if isinstance(result, list):
            return "".join(
                item.get("text", "")
                for item in result
                if isinstance(item, dict)
            ).strip()
        return ""

    def asr(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        mode = self._mode()
        if mode == "standard":
            return self._recognize_standard(pcm_bytes, sample_rate)
        return self._recognize_flash(pcm_bytes, sample_rate)

    def _recognize_standard(self, pcm_bytes: bytes, sample_rate: int) -> str:
        import requests

        request_id = str(uuid.uuid4())
        payload = self._build_payload(pcm_bytes, sample_rate)
        submit_timeout = self._timeout("submit_timeout", 10)
        query_timeout = self._timeout("query_timeout", 10)
        poll_interval = self._timeout("poll_interval", 0.5)
        max_wait_seconds = self._timeout("max_wait_seconds", 20)

        logger.asr_event(
            "Doubao ASR submit",
            f"mode=standard, request_id={request_id}",
        )

        response = requests.post(
            self.STANDARD_SUBMIT_URL,
            headers=self._headers(request_id, include_sequence=True),
            json=payload,
            timeout=submit_timeout,
        )
        status_code, message, logid = self._header_status(response)
        logger.asr_event(
            "Doubao ASR submit response",
            f"status={status_code}, message={message}, logid={logid}",
        )
        if response.status_code != 200 or status_code != "20000000":
            self._raise_for_api_error(response, "standard submit")

        deadline = time.monotonic() + max_wait_seconds
        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            query_response = requests.post(
                self.STANDARD_QUERY_URL,
                headers=self._headers(request_id),
                json={},
                timeout=query_timeout,
            )
            status_code, message, logid = self._header_status(query_response)
            logger.asr_event(
                "Doubao ASR query response",
                f"status={status_code}, message={message}, logid={logid}",
            )

            if query_response.status_code != 200:
                self._raise_for_api_error(query_response, "standard query")
            if status_code == "20000000":
                text = self._extract_text(query_response.json())
                logger.debug(f"[ASR] Doubao recognized: {text}", module="ASR")
                return text
            if status_code in {"20000001", "20000002"}:
                continue
            if status_code == "20000003":
                logger.debug("[ASR] Doubao detected silent audio", module="ASR")
                return ""
            self._raise_for_api_error(query_response, "standard query")

        raise TimeoutError(
            f"Doubao ASR standard query timed out after {max_wait_seconds}s, "
            f"request_id={request_id}"
        )

    def _recognize_flash(self, pcm_bytes: bytes, sample_rate: int) -> str:
        import requests

        request_id = str(uuid.uuid4())
        payload = self._build_payload(pcm_bytes, sample_rate)
        submit_timeout = self._timeout("submit_timeout", 10)

        logger.asr_event(
            "Doubao ASR recognize",
            f"mode=flash, request_id={request_id}",
        )

        response = requests.post(
            self.FLASH_RECOGNIZE_URL,
            headers=self._headers(request_id, include_sequence=True),
            json=payload,
            timeout=submit_timeout,
        )
        status_code, message, logid = self._header_status(response)
        logger.asr_event(
            "Doubao ASR recognize response",
            f"status={status_code}, message={message}, logid={logid}",
        )

        if response.status_code != 200 or status_code != "20000000":
            if status_code == "20000003":
                logger.debug("[ASR] Doubao detected silent audio", module="ASR")
                return ""
            self._raise_for_api_error(response, "flash recognize")

        text = self._extract_text(response.json())
        logger.debug(f"[ASR] Doubao recognized: {text}", module="ASR")
        return text


DoubaoASR = _DoubaoASR()
