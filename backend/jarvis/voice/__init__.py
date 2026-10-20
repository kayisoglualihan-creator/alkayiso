"""Sprachdienste (serverseitig, optional).

* Speech-to-Text: faster-whisper (lokal). Installation: ``pip install faster-whisper``
* Text-to-Speech: Piper (lokal, ``pip install piper-tts`` + Stimmmodell .onnx) oder ElevenLabs (API-Schlüssel)
* Wake Word "Hey Jarvis": openWakeWord (siehe ``jarvis.voice.wakeword``)

Die Weboberfläche nutzt zusätzlich die Browser-Sprach-APIs (Web Speech API) – damit funktioniert
Sprachsteuerung auch ohne diese optionalen Pakete (Edge/Chrome unter Windows, Safari auf dem iPhone).
"""
from __future__ import annotations

import asyncio
import importlib.util
import io
import os
import tempfile
import wave
from pathlib import Path

import httpx


def _has(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


class VoiceService:
    def __init__(self, data_dir: Path, secrets, db):
        self.data_dir = data_dir
        self.secrets = secrets
        self.db = db
        self._whisper = None

    def status(self) -> dict:
        piper_model = self.piper_model()
        return {
            "stt_faster_whisper": _has("faster_whisper"),
            "tts_piper": _has("piper") and bool(piper_model),
            "piper_model": str(piper_model) if piper_model else None,
            "tts_elevenlabs": bool(self.secrets.get("elevenlabs_api_key")),
            "wakeword_openwakeword": _has("openwakeword"),
            "audio_io_sounddevice": _has("sounddevice"),
            "browser_speech": True,
            "whisper_model": self.db.get_setting("whisper_model", "small"),
        }

    def piper_model(self) -> Path | None:
        configured = self.db.get_setting("piper_model_path", "")
        if configured and Path(configured).is_file():
            return Path(configured)
        voices = self.data_dir / "voices"
        if voices.is_dir():
            for f in sorted(voices.glob("*.onnx")):
                return f
        return None

    # -- STT ----------------------------------------------------------------------
    def _load_whisper(self):
        if self._whisper is None:
            from faster_whisper import WhisperModel  # type: ignore
            size = self.db.get_setting("whisper_model", "small")
            device = os.environ.get("JARVIS_WHISPER_DEVICE", "auto")
            self._whisper = WhisperModel(size, device=device, compute_type="int8")
        return self._whisper

    async def transcribe(self, audio: bytes, suffix: str = ".webm", language: str | None = "de") -> dict:
        if not _has("faster_whisper"):
            raise RuntimeError("faster-whisper ist nicht installiert")

        def work() -> dict:
            model = self._load_whisper()
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
                fh.write(audio)
                path = fh.name
            try:
                segments, info = model.transcribe(path, language=language, vad_filter=True)
                text = " ".join(s.text.strip() for s in segments).strip()
                return {"text": text, "language": info.language}
            finally:
                os.unlink(path)

        return await asyncio.to_thread(work)

    # -- TTS ----------------------------------------------------------------------
    async def speak(self, text: str) -> tuple[bytes, str]:
        engine = self.db.get_setting("tts_engine", "auto")
        piper_ok = _has("piper") and bool(self.piper_model())
        eleven_ok = bool(self.secrets.get("elevenlabs_api_key"))
        if engine == "elevenlabs" and eleven_ok or engine == "auto" and not piper_ok and eleven_ok:
            return await self._elevenlabs(text), "audio/mpeg"
        if engine in ("auto", "piper") and piper_ok:
            return await asyncio.to_thread(self._piper, text), "audio/wav"
        raise RuntimeError("Keine serverseitige Sprachausgabe eingerichtet (Piper-Stimme oder ElevenLabs-Schlüssel)")

    def _piper(self, text: str) -> bytes:
        from piper import PiperVoice  # type: ignore
        voice = PiperVoice.load(str(self.piper_model()))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            voice.synthesize_wav(text, wav)
        return buf.getvalue()

    async def _elevenlabs(self, text: str) -> bytes:
        voice_id = self.db.get_setting("elevenlabs_voice_id", "21m00Tcm4TlvDq8ikWAM")
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                             headers={"xi-api-key": self.secrets.get("elevenlabs_api_key") or ""},
                             json={"text": text, "model_id": "eleven_multilingual_v2"})
            r.raise_for_status()
            return r.content
