"""Lokale Sprachschleife für Windows: "Hey Jarvis" -> Aufnahme -> faster-whisper -> Agent -> Sprachausgabe.

Optional (``pip install -r requirements-voice.txt``). Läuft in der angemeldeten Benutzersitzung,
greift NUR nach Aktivierung in den Einstellungen auf das Mikrofon zu und zeigt seinen Zustand
über den Eventbus an (``voice.state`` – die Oberfläche zeigt dann "Ich höre zu").

Ablauf:
1. openWakeWord prüft 80-ms-Audioblöcke auf das vortrainierte Modell "hey_jarvis".
2. Nach Erkennung wird bis zu einer Sprechpause (max. 15 s) aufgenommen.
3. faster-whisper transkribiert lokal; der Text geht an den Agenten (Quelle "desktop").
4. Die Antwort wird mit Piper (oder ElevenLabs) gesprochen; ohne Server-TTS übernimmt die Oberfläche.
"""
from __future__ import annotations

import asyncio
import io
import logging
import threading
import time
import wave
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core import Jarvis
    from . import VoiceService

log = logging.getLogger("jarvis.voice")
SAMPLE_RATE = 16000
BLOCK = 1280  # 80 ms bei 16 kHz – Blockgröße von openWakeWord


def rms(samples) -> float:
    import numpy as np
    return float(np.sqrt(np.mean(np.square(samples.astype(np.float32))))) if len(samples) else 0.0


def to_wav(samples) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


class Utterance:
    """Sammelt Audio nach dem Wake Word, bis eine Sprechpause erkannt wird."""

    def __init__(self, silence_threshold: float = 350.0, silence_s: float = 1.2, max_s: float = 15.0):
        self.blocks: list = []
        self.silence_threshold = silence_threshold
        self.silence_blocks = int(silence_s * SAMPLE_RATE / BLOCK)
        self.max_blocks = int(max_s * SAMPLE_RATE / BLOCK)
        self._quiet = 0
        self._heard_speech = False

    def add(self, block) -> bool:
        """Gibt True zurück, wenn die Äußerung abgeschlossen ist."""
        self.blocks.append(block)
        loud = rms(block) > self.silence_threshold
        self._heard_speech |= loud
        self._quiet = 0 if loud else self._quiet + 1
        return (self._heard_speech and self._quiet >= self.silence_blocks) or len(self.blocks) >= self.max_blocks

    def audio(self):
        import numpy as np
        return np.concatenate(self.blocks) if self.blocks else np.zeros(0, dtype=np.int16)


class WakeWordLoop:
    def __init__(self, app: Jarvis, voice: VoiceService, loop: asyncio.AbstractEventLoop,
                 detector_factory: Callable | None = None, threshold: float = 0.5):
        self.app = app
        self.voice = voice
        self.loop = loop
        self.threshold = threshold
        self._detector_factory = detector_factory
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def available() -> bool:
        from . import _has
        return _has("openwakeword") and _has("sounddevice") and _has("numpy")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="jarvis-wakeword", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _state(self, state: str, **extra) -> None:
        self.app.bus.publish("voice.state", {"state": state, **extra})

    def _detector(self):
        if self._detector_factory:
            return self._detector_factory()
        from openwakeword.model import Model  # type: ignore
        try:
            return Model(wakeword_models=["hey_jarvis"])
        except Exception:
            import openwakeword  # type: ignore
            openwakeword.utils.download_models(["hey_jarvis"])
            return Model(wakeword_models=["hey_jarvis"])

    def _run(self) -> None:
        import sounddevice as sd  # type: ignore

        detector = self._detector()
        self._state("wake_listening")
        log.info("Wake-Word-Erkennung aktiv ('Hey Jarvis')")
        utter: Utterance | None = None
        cooldown_until = 0.0
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=BLOCK) as stream:
            while not self._stop.is_set():
                block, _ = stream.read(BLOCK)
                block = block[:, 0]
                if utter is not None:
                    if utter.add(block):
                        audio = utter.audio()
                        utter = None
                        self._state("thinking")
                        asyncio.run_coroutine_threadsafe(self.handle(to_wav(audio)), self.loop)
                        cooldown_until = time.time() + 2
                    continue
                scores = detector.predict(block)
                if time.time() > cooldown_until and max(scores.values(), default=0) >= self.threshold:
                    self._state("listening")
                    utter = Utterance()
        self._state("off")

    async def handle(self, wav: bytes) -> str:
        try:
            text = (await self.voice.transcribe(wav, ".wav", "de"))["text"].strip()
        except Exception as exc:
            log.warning("Transkription fehlgeschlagen: %s", exc)
            self._state("error", message=str(exc))
            return ""
        if not text:
            self._state("wake_listening")
            return ""
        self.app.bus.publish("voice.transcript", {"text": text})
        out = await self.app.agent.run(text, source="desktop")
        self.app.bus.publish("voice.reply", {"text": out["text"], "conversation_id": out["conversation_id"]})
        try:
            audio, _mime = await self.voice.speak(out["text"])
            await asyncio.to_thread(self._play, audio)
        except RuntimeError:
            pass  # keine Server-Stimme -> Oberfläche liest per Browser-Sprachausgabe vor
        self._state("wake_listening")
        return out["text"]

    @staticmethod
    def _play(wav_bytes: bytes) -> None:
        import numpy as np
        import sounddevice as sd  # type: ignore
        with wave.open(io.BytesIO(wav_bytes)) as w:
            data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            sd.play(data, w.getframerate())
            sd.wait()
