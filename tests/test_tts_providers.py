"""The voice callers hear: the hosted voice (Spitch), the voice on this machine (Piper), the silent stand-in, and the routing that keeps a call spoken when the hosted voice fails."""

import asyncio
import io
import logging
import struct
import sys
import time
import types
import wave
from pathlib import Path

import httpx
import pytest

from sofa import audio as audio_module
from sofa.audio import AudioService
from sofa.clients import tts as tts_module
from sofa.clients.tts import FallbackAudio, PiperTTS, RoutedTTS, SpitchTTS, StandInTTS, build_local_voice, build_tts, join_wavs, split_sentences
from sofa.config import Settings

REAL_SLEEP = asyncio.sleep


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def no_voice_settings_from_the_environment(monkeypatch):
    """A developer machine may have real voice settings in its environment: these tests describe what happens without them, unless a test sets them."""
    for name in ("TTS_PROVIDER", "SPITCH_API_KEY", "SPITCH_VOICE_EN", "TTS_HOSTED_SPEED", "PIPER_MODEL", "PIPER_SPEED"):
        monkeypatch.delenv(name, raising=False)


def _wav_of(frames: int, loudness: int = 1) -> bytes:
    """A tiny 24 kHz WAV whose samples have a known value, so a test can tell which voice made a clip."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(bytes([loudness, 0]) * frames)
    return buf.getvalue()


def _clip(name: str, frames: int = 2400) -> bytes:
    """A clip whose loudness depends on the name of the voice that made it."""
    return _wav_of(frames, len(name) % 250 + 1)


def _frames(audio: bytes) -> int:
    with wave.open(io.BytesIO(audio)) as w:
        return w.getnframes()


def _transport(seen, status=200, content=None):
    """A stand-in for the voice service's server that records every request and answers with the given status."""
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, content=_wav_of(1600) if content is None else content, text=None if status == 200 else "the service said no")
    return httpx.MockTransport(handler)


def _spitch(seen, status=200, voice="jude", speed=1.0):
    voice = SpitchTTS("k3", voice, speed)
    voice.http = httpx.AsyncClient(base_url="https://api.spitch.app", transport=_transport(seen, status), headers={"Authorization": "Bearer k3"})
    return voice


class _Refused(Exception):
    """What the hosted voice raises when it answers 402: it carries the response, as an httpx error does."""

    def __init__(self, status):
        self.response = type("R", (), {"status_code": status, "text": "no credits left"})()


class _Voice:
    """A voice that makes a clip named after itself, counts how often it was asked, and fails when told to."""

    def __init__(self, name, fail=None):
        self.name, self.tag, self.fail, self.asked = name, name, fail, 0

    async def synthesize(self, text, language):
        self.asked += 1
        if self.fail:
            raise self.fail
        return _clip(self.name)


def _fake_piper(monkeypatch, made, with_config=True):
    """A stand-in for the piper package: it records how it was asked and writes a short clip."""
    class Config:
        def __init__(self, length_scale=1.0):
            self.length_scale = length_scale

    class Voice:
        @classmethod
        def load(cls, path):
            made["path"] = path
            return cls()

        def synthesize_wav(self, text, w, syn_config=None):
            made["text"], made["length_scale"] = text, getattr(syn_config, "length_scale", None)
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(b"\x01\x00" * 2205)

    module = types.ModuleType("piper")
    module.PiperVoice = Voice
    if with_config:
        module.SynthesisConfig = Config
    monkeypatch.setitem(sys.modules, "piper", module)


# ---- the hosted voice (Spitch) --------------------------------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_spitch_sends_the_key_and_the_voice_for_the_language_and_returns_the_clip():
    seen = []
    voice = _spitch(seen, speed=1.5)
    audio = await voice.synthesize("Good morning, how can I help you today?", "en")
    request = seen[0]
    assert request.url.path == "/v1/speech" and request.headers["authorization"] == "Bearer k3"
    body = request.content.replace(b" ", b"")
    assert b'"voice":"jude"' in body and b'"language":"en"' in body and b'"format":"wav"' in body
    assert b'"speed":1.2' in body                       # the pace is held between 0.7 and 1.2, whatever was asked for
    assert _frames(audio) == 1600


def test_the_pace_of_the_hosted_voice_is_kept_inside_the_range_the_service_accepts():
    assert SpitchTTS("k", "jude", 5.0).speed == 1.2
    assert SpitchTTS("k", "jude", 0.1).speed == 0.7
    assert SpitchTTS("k", "jude", 0.95).speed == 0.95


def test_a_streamed_wav_with_unknown_length_and_an_extra_chunk_is_repaired():
    from sofa.clients.tts import _repair_wav
    pcm = b"\x01\x00" * 2400
    raw = (b"RIFF" + b"\xff\xff\xff\xff" + b"WAVE" + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 24000, 48000, 2, 16)
           + b"spch" + struct.pack("<I", 4) + b"abcd" + b"data" + b"\xff\xff\xff\xff" + pcm)
    with wave.open(io.BytesIO(_repair_wav(raw))) as w:
        assert w.getframerate() == 24000 and w.getnframes() == 2400


def test_audio_that_is_not_a_wav_is_left_as_it_came():
    from sofa.clients.tts import _repair_wav
    assert _repair_wav(b"not a wav at all") == b"not a wav at all"


@pytest.mark.anyio
async def test_spitch_never_has_more_than_two_calls_running_and_asks_again_after_a_429(monkeypatch):
    running, peak, answers = 0, 0, {"n": 0}

    async def quick_sleep(seconds):
        await REAL_SLEEP(0)

    monkeypatch.setattr(asyncio, "sleep", quick_sleep)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await REAL_SLEEP(0.02)
        running -= 1
        answers["n"] += 1
        return httpx.Response(429 if answers["n"] == 1 else 200, content=_wav_of(100))

    voice = SpitchTTS("k", "jude")
    voice.http = httpx.AsyncClient(base_url="https://api.spitch.app", transport=httpx.MockTransport(handler))
    results = await asyncio.gather(*(voice.synthesize(f"Please wait while I look for sentence number {i}.", "en") for i in range(6)))
    assert len(results) == 6 and peak <= 2


@pytest.mark.anyio
async def test_spitch_asks_again_after_a_growing_pause_when_it_is_told_to_slow_down(monkeypatch):
    waits, answers = [], {"n": 0}

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        answers["n"] += 1
        return httpx.Response(429 if answers["n"] <= 3 else 200, content=_wav_of(100))

    voice = SpitchTTS("k", "jude")
    voice.http = httpx.AsyncClient(base_url="https://api.spitch.app", transport=httpx.MockTransport(handler))
    assert _frames(await voice.synthesize("Hello there, how are you today?", "en")) == 100
    assert answers["n"] == 4 and waits == [0.7, 1.5, 3.0]


@pytest.mark.anyio
async def test_a_voice_that_stays_too_busy_is_a_failure_after_the_last_try(monkeypatch):
    async def quick_sleep(seconds):
        await REAL_SLEEP(0)

    monkeypatch.setattr(asyncio, "sleep", quick_sleep)
    seen = []
    voice = _spitch(seen, status=429)
    with pytest.raises(httpx.HTTPStatusError):
        await voice.synthesize("Hello there, how are you today?", "en")
    assert len(seen) == 4                                   # the first try and three more


# ---- the voice on this machine (Piper) and the silent stand-in ------------------------------------------------------------------------


@pytest.mark.anyio
async def test_piper_speaks_a_wav_at_the_pace_asked(monkeypatch):
    made = {}
    _fake_piper(monkeypatch, made)
    voice = PiperTTS("/voices/en_GB-jenny_dioco-medium.onnx", speed=1.25)
    audio = await voice.synthesize("Hello there.", "en")
    with wave.open(io.BytesIO(audio)) as w:
        assert w.getframerate() == 22050 and w.getnframes() == 2205
    assert made["text"] == "Hello there." and made["length_scale"] == pytest.approx(0.8)
    assert voice.tag == "piper-en_GB-jenny_dioco-medium"


@pytest.mark.anyio
async def test_piper_names_itself_from_a_windows_path_and_copes_with_an_older_release(monkeypatch):
    made = {}
    _fake_piper(monkeypatch, made, with_config=False)
    voice = PiperTTS("C:\\voices\\en_US-lessac-medium.onnx")
    assert voice.tag == "piper-en_US-lessac-medium"
    assert _frames(await voice.synthesize("Hello there.", "en")) == 2205
    assert made["length_scale"] is None                     # an older release has no pace setting: the voice's own pace is used


@pytest.mark.anyio
async def test_the_stand_in_voice_makes_a_quiet_clip_a_third_of_a_second_for_every_word():
    voice = StandInTTS()
    clip = await voice.synthesize("Please tell me which area of Lagos you are in.", "en")
    with wave.open(io.BytesIO(clip)) as w:
        assert w.getframerate() == 8000 and w.getnframes() == int(8000 * 0.35 * 10)
        assert set(w.readframes(w.getnframes())) == {0}     # it is silence
    long_text = " ".join(["word"] * 100)
    assert _frames(await voice.synthesize(long_text, "en")) == 8000 * 12          # and never longer than twelve seconds


# ---- speaking one sentence at a time --------------------------------------------------------------------------------------------------


def test_sentences_are_spoken_one_by_one_and_a_piece_under_four_words_joins_its_neighbour():
    # "Okay." alone came out wrong 7 times in 7 on the first real calls, so it goes with the sentence after it.
    assert split_sentences("Okay. I have booked you at Yaba Lakeview Clinic for tomorrow at nine in the morning. Would you like anything else?") == [
        "Okay. I have booked you at Yaba Lakeview Clinic for tomorrow at nine in the morning.", "Would you like anything else?"]
    assert split_sentences("Done. I will send the details of your appointment to this phone by text message. Please arrive ten minutes early. Thank you for calling.") == [
        "Done. I will send the details of your appointment to this phone by text message.", "Please arrive ten minutes early.", "Thank you for calling."]
    assert split_sentences("Nice to meet you, Bola. Which area of Lagos are you in?") == ["Nice to meet you, Bola.", "Which area of Lagos are you in?"]
    assert split_sentences("Which area of Lagos are you in?") == ["Which area of Lagos are you in?"]
    assert split_sentences("Sent. Anything else?") == ["Sent. Anything else?"]
    assert split_sentences("Thank you for calling. Goodbye.") == ["Thank you for calling. Goodbye."]       # a short last sentence joins the one before it
    assert split_sentences("Amoxicillin five hundred milligram capsules are in stock at Everwell Pharmacy Surulere.") == [
        "Amoxicillin five hundred milligram capsules are in stock at Everwell Pharmacy Surulere."]


def test_joined_clips_have_a_quiet_gap_between_them_and_a_lead_in_before_the_first():
    joined = join_wavs([_wav_of(2400), _wav_of(1200)])
    assert _frames(joined) == 2400 + 1200 + int(24000 * 0.3) + int(24000 * 0.25)


@pytest.mark.anyio
async def test_each_piece_is_made_separately_and_joined_with_a_pause():
    calls = []

    class Hosted:
        tag = "h"

        async def synthesize(self, text, language):
            calls.append(text)
            return _wav_of(2400)

    out = await RoutedTTS(Hosted(), None).synthesize("Your appointment is booked for tomorrow at nine in the morning. Which other service would you like?", "en")
    assert calls == ["Your appointment is booked for tomorrow at nine in the morning.", "Which other service would you like?"]
    assert _frames(out) == 2400 * 2 + int(24000 * 0.3) + int(24000 * 0.25)       # one gap, and the lead-in


# ---- routing, and the hosted voice going wrong ---------------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_with_no_hosted_voice_the_voice_on_this_machine_speaks_and_with_neither_the_stand_in_does():
    local, standin = _Voice("local"), _Voice("standin")
    assert await RoutedTTS(None, standin, local=local).synthesize("Hello there, how can I help you?", "en") == _clip("local")
    assert await RoutedTTS(None, standin).synthesize("Hello there, how can I help you?", "en") == _clip("standin")
    assert local.asked == 1 and standin.asked == 1


@pytest.mark.anyio
async def test_a_failing_hosted_voice_falls_back_to_the_voice_on_this_machine_and_never_keeps_that_audio():
    class Broken:
        tag = "x"

        async def synthesize(self, text, language):
            raise httpx.HTTPStatusError("402", request=httpx.Request("POST", "https://x"), response=httpx.Response(402, text="no credit"))

    local = _Voice("local")
    out = await RoutedTTS(Broken(), _Voice("standin"), local=local).synthesize("Hello there, how can I help you?", "en")
    assert out == _clip("local") and isinstance(out, FallbackAudio)


@pytest.mark.anyio
async def test_a_voice_that_stays_refused_is_a_failure_and_the_status_is_logged(caplog):
    class Refused:
        tag = "t"

        async def synthesize(self, text, language):
            raise httpx.HTTPStatusError("429", request=httpx.Request("POST", "https://x"), response=httpx.Response(429, text="Too many requests"))

    class Standin:
        async def synthesize(self, text, language):
            return b"silence"

    with caplog.at_level(logging.WARNING, logger="sofa.tts"):
        out = await RoutedTTS(Refused(), Standin()).synthesize("Hello there, how can I help you?", "en")
    assert isinstance(out, FallbackAudio) and out == b"silence" and "HTTP 429" in caplog.text and "Too many requests" in caplog.text


@pytest.mark.anyio
async def test_when_the_hosted_voice_is_out_of_credit_the_voice_on_this_machine_speaks_and_the_hosted_one_is_left_alone_for_a_while():
    hosted, local, standin = _Voice("hosted", fail=_Refused(402)), _Voice("local"), _Voice("standin")
    routed = RoutedTTS(hosted, standin, local=local)
    first = await routed.synthesize("Hello there, how can I help you today?", "en")
    assert first == _clip("local") and isinstance(first, FallbackAudio)      # a stand-in: never kept as the phrase's permanent audio
    assert hosted.asked == 1 and routed.skip_until - time.monotonic() > 500   # a refusal for credit leaves the hosted voice alone for ten minutes
    await routed.synthesize("Another sentence for the caller to hear now.", "en")
    await routed.synthesize("And one more sentence after that one.", "en")
    assert hosted.asked == 1 and local.asked == 3 and standin.asked == 0


@pytest.mark.anyio
@pytest.mark.parametrize("status, longest", [(401, 600), (402, 600), (403, 600), (500, 20), (503, 20)])
async def test_the_pause_after_a_failure_depends_on_the_answer(status, longest):
    routed = RoutedTTS(_Voice("hosted", fail=_Refused(status)), _Voice("standin"), local=_Voice("local"))
    await routed.synthesize("Hello there, how can I help you today?", "en")
    pause = routed.skip_until - time.monotonic()
    assert longest - 2 < pause <= longest


@pytest.mark.anyio
async def test_a_network_fault_pauses_the_hosted_voice_for_the_short_time():
    routed = RoutedTTS(_Voice("hosted", fail=httpx.ConnectError("refused")), _Voice("standin"), local=_Voice("local"))
    assert await routed.synthesize("Hello there, how can I help you today?", "en") == _clip("local")
    assert 18 < routed.skip_until - time.monotonic() <= 20


@pytest.mark.anyio
async def test_the_hosted_voice_is_tried_again_after_the_pause():
    hosted, local = _Voice("hosted", fail=_Refused(500)), _Voice("local")
    routed = RoutedTTS(hosted, _Voice("standin"), local=local)
    await routed.synthesize("A sentence long enough to be one piece here.", "en")
    routed.skip_until = 0.0                                  # the pause is over
    hosted.fail = None
    again = await routed.synthesize("A sentence long enough to be one piece here.", "en")
    assert again == join_wavs([_clip("hosted")]) and not isinstance(again, FallbackAudio)


@pytest.mark.anyio
async def test_when_the_hosted_service_is_down_the_call_is_spoken_by_the_voice_on_this_machine(monkeypatch):
    """The outage story end to end: Spitch answers 503, the call carries on in Piper's voice, and the next sentence does not wait for Spitch to fail again."""
    _fake_piper(monkeypatch, {})
    seen = []
    hosted = _spitch(seen, status=503)
    routed = RoutedTTS(hosted, StandInTTS(), local=PiperTTS("/voices/en_GB-jenny_dioco-medium.onnx"))
    first = await routed.synthesize("Please help me find the nearest clinic for antenatal care.", "en")
    assert isinstance(first, FallbackAudio) and _frames(first) == 2205       # the clip is Piper's
    asked = len(seen)
    assert asked >= 1
    second = await routed.synthesize("Which area of Lagos are you in, please?", "en")
    assert isinstance(second, FallbackAudio) and len(seen) == asked          # Spitch was left alone


@pytest.mark.anyio
async def test_a_refused_key_at_the_hosted_service_leaves_it_alone_for_ten_minutes(monkeypatch):
    _fake_piper(monkeypatch, {})
    routed = RoutedTTS(_spitch([], status=401), StandInTTS(), local=PiperTTS("/voices/v.onnx"))
    await routed.synthesize("Hello there, how can I help you today?", "en")
    assert 598 < routed.skip_until - time.monotonic() <= 600


# ---- choosing the voice from the settings -------------------------------------------------------------------------------------------


def test_with_no_key_and_no_local_voice_the_silent_stand_in_is_used_so_a_fresh_checkout_still_starts():
    assert isinstance(build_tts(Settings(_env_file=None)), StandInTTS)
    assert isinstance(build_tts(Settings(_env_file=None, tts_provider="standin")), StandInTTS)
    assert isinstance(build_tts(Settings(_env_file=None, tts_provider="piper")), StandInTTS)       # a Piper voice was asked for, but no model file is set


def test_an_unknown_voice_provider_is_refused_with_the_choices_named():
    for name in ("nonsense", "robot"):
        with pytest.raises(ValueError, match="spitch, piper or standin"):
            build_tts(Settings(_env_file=None, tts_provider=name))


def test_a_spitch_key_gives_the_hosted_voice_for_english_only_and_the_chosen_voice_name():
    voice = build_tts(Settings(_env_file=None, tts_provider="spitch", spitch_api_key="a-private-key-value", spitch_voice_en="lina", tts_hosted_speed=1.1))
    assert isinstance(voice, RoutedTTS) and voice.local is None
    assert isinstance(voice.hosted, SpitchTTS) and voice.hosted.voice == "lina" and voice.hosted.speed == 1.1
    assert voice.tag == voice.hosted.tag and "lina" in voice.tag and "a-private-key-value" not in voice.tag      # the tag names the voice, never the key


def test_a_voice_on_this_machine_is_only_built_when_a_model_exists_and_loads(tmp_path, monkeypatch):
    assert build_local_voice(Settings(_env_file=None)) is None                                        # none set
    assert build_local_voice(Settings(_env_file=None, piper_model=str(tmp_path / "missing.onnx"))) is None   # set, but the file is not there
    model = tmp_path / "v.onnx"
    model.write_bytes(b"x")
    monkeypatch.setitem(sys.modules, "piper", None)                                                   # the package is not installed
    assert build_local_voice(Settings(_env_file=None, piper_model=str(model))) is None
    _fake_piper(monkeypatch, {})
    assert build_local_voice(Settings(_env_file=None, piper_model=str(model))).tag == "piper-v"


def test_build_tts_gives_the_hosted_voice_its_local_back_up(tmp_path, monkeypatch):
    model = tmp_path / "v.onnx"
    model.write_bytes(b"x")
    _fake_piper(monkeypatch, {})
    voice = build_tts(Settings(_env_file=None, tts_provider="spitch", spitch_api_key="k", piper_model=str(model)))
    assert isinstance(voice, RoutedTTS) and isinstance(voice.hosted, SpitchTTS) and voice.local is not None


def test_a_spitch_provider_with_no_key_speaks_with_the_local_voice_when_there_is_one(tmp_path, monkeypatch):
    model = tmp_path / "v.onnx"
    model.write_bytes(b"x")
    _fake_piper(monkeypatch, {})
    voice = build_tts(Settings(_env_file=None, tts_provider="spitch", piper_model=str(model)))
    assert isinstance(voice, RoutedTTS) and voice.hosted is None and voice.tag == "piper-v"
    assert isinstance(build_tts(Settings(_env_file=None, tts_provider="piper", piper_model=str(model))), RoutedTTS)


def test_the_stand_in_provider_ignores_a_local_voice(tmp_path, monkeypatch):
    model = tmp_path / "v.onnx"
    model.write_bytes(b"x")
    _fake_piper(monkeypatch, {})
    assert isinstance(build_tts(Settings(_env_file=None, tts_provider="standin", piper_model=str(model))), StandInTTS)


# ---- the stored audio ---------------------------------------------------------------------------------------------------------------


def test_the_audio_cache_key_changes_with_the_voice(tmp_path):
    base = AudioService.key("Hello", "en")
    try:
        AudioService(Settings(_env_file=None, storage_dir=str(tmp_path)), type("T", (), {"tag": "spitch-en-jude"})())
        assert AudioService.key("Hello", "en") != base
    finally:
        AudioService.voice_tag = ""
    assert AudioService.key("Hello", "en") == base


@pytest.mark.anyio
async def test_audio_from_the_standin_voice_is_kept_for_minutes_not_for_good(tmp_path, monkeypatch):
    class Voice:
        tag = "t"

        def __init__(self):
            self.fails, self.calls = True, 0

        async def synthesize(self, text, language):
            self.calls += 1
            return FallbackAudio(b"silence") if self.fails else b"real voice"

    voice = Voice()
    service = AudioService(Settings(storage_dir=str(tmp_path), _env_file=None), voice)
    try:
        _, path = await service.speak("Are you still there?", "en")
        assert Path(path).read_bytes() == b"silence" and voice.calls == 1
        await service.speak("Are you still there?", "en")
        assert voice.calls == 1                               # within the couple of minutes it is reused
        voice.fails = False
        clock = time.time() + audio_module.FALLBACK_KEPT_SECONDS + 5
        monkeypatch.setattr(audio_module.time, "time", lambda: clock)
        _, path = await service.speak("Are you still there?", "en")
        assert Path(path).read_bytes() == b"real voice" and voice.calls == 2         # asked again, and now kept for good
        await service.speak("Are you still there?", "en")
        assert voice.calls == 2 and not list((tmp_path / "audio_out").glob("*.fallback"))      # and the marker is gone with the temporary audio
    finally:
        AudioService.voice_tag = ""


def test_only_the_voices_that_are_in_use_exist():
    voices = {name for name in dir(tts_module) if name.endswith("TTS")}
    assert voices == {"PiperTTS", "RoutedTTS", "SpitchTTS", "StandInTTS"}
