"""Sprachschleife: Äußerungserkennung und Verarbeitung (ohne echte Audio-Hardware)."""
import asyncio

import pytest

np = pytest.importorskip("numpy")

from jarvis.voice.wakeword import BLOCK, Utterance, WakeWordLoop, to_wav  # noqa: E402


def test_utterance_ends_after_silence():
    u = Utterance(silence_threshold=100, silence_s=0.24, max_s=5)
    loud = (np.sin(np.linspace(0, 200, BLOCK)) * 3000).astype(np.int16)
    quiet = np.zeros(BLOCK, dtype=np.int16)
    assert not u.add(quiet)  # Stille vor dem Sprechen beendet nichts
    for _ in range(5):
        assert not u.add(loud)
    done = [u.add(quiet) for _ in range(3)]
    assert done[-1] is True
    assert len(to_wav(u.audio())) > 44


def test_utterance_max_length():
    u = Utterance(max_s=0.16)
    loud = (np.ones(BLOCK) * 5000).astype(np.int16)
    assert not u.add(loud)
    assert u.add(loud)


class FakeVoice:
    def __init__(self, text):
        self.text = text

    async def transcribe(self, audio, suffix, language):
        return {"text": self.text}

    async def speak(self, text):
        raise RuntimeError("keine Server-Stimme")


@pytest.mark.parametrize("spoken,expect", [("Wie spät ist es", "Uhr"), ("", "")])
def test_wake_handle_runs_agent(client, spoken, expect):
    loop = WakeWordLoop(client.jarvis, FakeVoice(spoken), asyncio.new_event_loop())
    out = asyncio.run(loop.handle(b"RIFF"))
    assert (expect in out) if expect else out == ""


def test_wakeword_endpoint_reports_missing_deps(client):
    r = client.post("/api/voice/wakeword", json={"enabled": True}, headers=client.admin)
    assert r.status_code in (200, 501)
    if r.status_code == 501:
        assert r.json()["error"]["code"] == "wakeword_unavailable"
