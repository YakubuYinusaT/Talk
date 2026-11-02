import asyncio
import logging

from .http import RetryingClient

log = logging.getLogger("sofa.tts")


def _wav(pcm: bytes, rate: int) -> bytes:
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _repair_wav(raw: bytes) -> bytes:
    """Some services stream a WAV whose header says the length is unknown (0xFFFFFFFF), with extra chunks before the audio.
    Walk the chunks, take what is really there, and write a normal header so players and length checks agree."""
    import struct
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        return raw
    pos, rate, channels = 12, 24000, 1
    while pos + 8 <= len(raw):
        name, size = raw[pos:pos + 4], struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        body = pos + 8
        if name == b"fmt " and body + 16 <= len(raw):
            channels, rate = struct.unpack("<HI", raw[body + 2:body + 8])
        elif name == b"data":
            pcm = raw[body:body + size] if body + size <= len(raw) else raw[body:]
            pcm = pcm[: len(pcm) - len(pcm) % (2 * channels)]
            return _wav(pcm, rate) if channels == 1 else raw
        pos = body + size + (size & 1)
    return raw


class StandInTTS:
    """The voice used when no hosted voice is set up: it makes a quiet clip of the right length (a third of a second a word), inside this process. A fresh checkout and the
    tests run with it; a caller hears silence, so a real call needs the hosted voice or a voice on this machine."""
    tag = "stand-in"

    async def synthesize(self, text: str, language: str) -> bytes:
        words = max(1, len(str(text).split()))
        rate, seconds = 8000, min(12.0, 0.35 * words)
        return _wav(b"\x00\x00" * int(rate * seconds), rate)


class SpitchTTS:
    """Spitch, a Nigerian company, provides the hosted voice. Talk uses its English voice, and each request to POST /v1/speech returns a WAV file."""

    def __init__(self, api_key: str, voice: str, speed: float = 1.0):
        self.voice, self.speed = voice, min(1.2, max(0.7, speed))
        self._slots = asyncio.Semaphore(2)  # Tier 1 allows 3 calls at once; two leaves room for the one still being counted as a call finishes
        self.tag = f"spitch-en{voice}-{self.speed}"  # the same name as before, so that audio that was already made is still found
        self.http = RetryingClient(base_url="https://api.spitch.app", timeout=30.0,
                                  headers={"Authorization": f"Bearer {api_key}"})

    async def synthesize(self, text: str, language: str) -> bytes:
        body = {"text": text, "language": "en", "voice": self.voice, "speed": self.speed, "format": "wav"}
        async with self._slots:
            for pause in (0.7, 1.5, 3.0, None):  # "too many at once" is asked again after a growing pause, up to three times, before it counts as a failure
                resp = await self.http.post("/v1/speech", json=body)
                if resp.status_code != 429 or pause is None:
                    break
                await asyncio.sleep(pause)
        resp.raise_for_status()
        return _repair_wav(resp.content)


class AzureBusy(Exception):
    """The free tier's limit on voice requests in a minute is reached: the reply is spoken by the voice on this machine instead of waiting."""


class AzureTTS:
    """Microsoft Azure Speech, with its Nigerian English voices (en-NG-EzinneNeural and en-NG-AbeoNeural). Each reply is one request, because the free tier
    allows only 20 requests a minute, and Talk keeps under that by counting its own requests: when one more would go over, it does not wait, so the reply
    is spoken at once by the voice on this machine."""

    whole = True            # the reply is voiced in one request, not a sentence at a time
    PER_MINUTE = 18         # under the free tier's 20 requests a minute, with room to spare
    min_interval = 60 / PER_MINUTE   # the pace at which the warm-up asks for one phrase after another

    def __init__(self, key: str, region: str, voice: str = "en-NG-EzinneNeural", speed: float = 1.0):
        from collections import deque

        self.voice, self.speed = voice, min(1.2, max(0.7, speed))
        self.tag = f"azure-{voice}-{self.speed}"
        self.url = f"https://{region.strip().lower()}.tts.speech.microsoft.com/cognitiveservices/v1"
        self.http = RetryingClient(timeout=20.0, headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/ssml+xml",
                                                          "X-Microsoft-OutputFormat": "riff-16khz-16bit-mono-pcm", "User-Agent": "talk-health"})
        self._sent = deque()

    def ssml(self, text: str) -> str:
        from xml.sax.saxutils import escape, quoteattr

        rate = f"{round((self.speed - 1) * 100):+d}%"
        return (f"<speak version='1.0' xml:lang='en-NG'><voice name={quoteattr(self.voice)}><prosody rate='{rate}'>{escape(str(text))}</prosody>"
                f"</voice></speak>")

    def _take_slot(self) -> None:
        import time

        now = time.monotonic()
        while self._sent and now - self._sent[0] >= 60:
            self._sent.popleft()
        if len(self._sent) >= self.PER_MINUTE:
            raise AzureBusy("the free tier's requests for this minute are used up")
        self._sent.append(now)

    async def synthesize(self, text: str, language: str) -> bytes:
        self._take_slot()
        resp = await self.http.post(self.url, content=self.ssml(text).encode("utf-8"))
        resp.raise_for_status()
        return _repair_wav(resp.content)


class PiperTTS:
    """A voice that runs on this machine (Piper, open source): no account, no credit, no network. English only. It speaks when the hosted voice cannot, so a
    caller hears a real voice instead of silence; it is also quick on a plain CPU (a sentence in well under a second)."""


    def __init__(self, model_path: str, speed: float = 1.0):
        from piper import PiperVoice  # a package this machine may not have: build_tts only asks for it when a model is set

        self.voice = PiperVoice.load(model_path)
        self.length_scale = 1.0 / min(1.3, max(0.7, speed))
        self.tag = "piper-" + model_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].replace(".onnx", "")
        self._slots = asyncio.Semaphore(2)

    def _speak(self, text: str) -> bytes:
        import io
        import wave

        try:
            from piper import SynthesisConfig
            config = SynthesisConfig(length_scale=self.length_scale)
        except ImportError:  # an older release without the setting: the voice's own pace
            config = None
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            if config is not None:
                self.voice.synthesize_wav(text, w, syn_config=config)
            else:
                self.voice.synthesize_wav(text, w)
        return buf.getvalue()

    async def synthesize(self, text: str, language: str) -> bytes:
        async with self._slots:
            return await asyncio.to_thread(self._speak, text)


MIN_WORDS = 4         # a piece shorter than this is joined to its neighbour
PAUSE_SECONDS = 0.3   # quiet between two spoken sentences
LEAD_SECONDS = 0.25   # quiet before the first word: players that wake their speaker on play swallow the start of a clip ("Done." went unheard)


def split_sentences(text: str) -> list[str]:
    """One piece per sentence, each made and spoken on its own, one after the other, because a long text read in one go loses its last sentence
    (a closing question like "Anything else?" went unheard). A piece under four words is joined to its neighbour: measured on the first real
    calls, the voice puts junk in front of very short clips ("Okay." came out wrong 7 times in 7, "Got it." 4 in 8) and not in longer ones (0 in 24)."""
    import re
    pieces = [p.strip() for p in re.split(r"(?<=[.?!])\s+", text.strip()) if p.strip()]
    while len(pieces) > 1:
        short = next((i for i, p in enumerate(pieces) if len(p.split()) < MIN_WORDS), None)
        if short is None:
            break
        j = short + 1 if short + 1 < len(pieces) else short - 1  # the sentence after it, or for the last one the sentence before
        lo, hi = sorted((short, j))
        pieces[lo:hi + 1] = [pieces[lo] + " " + pieces[hi]]
    return pieces


def join_wavs(wavs: list[bytes], pause: float = PAUSE_SECONDS, lead: float = LEAD_SECONDS) -> bytes:
    """Put WAV clips (same format) one after another with a quiet gap between them, and a little quiet before the first."""
    import io
    import wave
    frames, params = [], None
    for raw in wavs:
        with wave.open(io.BytesIO(raw)) as w:
            if params is None:
                params = w.getparams()
            frames.append(w.readframes(w.getnframes()))
    def quiet(seconds: float) -> bytes:
        return bytes(int(params.framerate * seconds) * params.sampwidth * params.nchannels)
    return _wav_params(quiet(lead) + quiet(pause).join(frames), params)


def _wav_params(pcm: bytes, params) -> bytes:
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(params.nchannels)
        w.setsampwidth(params.sampwidth)
        w.setframerate(params.framerate)
        w.writeframes(pcm)
    return buf.getvalue()


class FallbackAudio(bytes):
    """Audio made by the stand-in voice because the hosted one failed. It is spoken this once and never kept as the phrase's permanent audio."""


class RoutedTTS:
    """Speaks with the hosted voice when there is one. When the hosted voice fails, a voice on this machine (`local`, if there is one) speaks instead, and
    the silent stand-in speaks when there is neither; after a refusal for credit or a key, or a network fault, the hosted voice is left alone
    for a while, so each sentence does not wait for a failure first. With no hosted voice the voice on this machine is the voice."""

    PAUSE_AFTER = {401: 600, 402: 600, 403: 600}  # seconds the hosted voice is not asked after this answer (no credit, a bad key): asking again only waits
    PAUSE_OTHER = 20

    def __init__(self, hosted, default, local=None):
        self.hosted, self.default, self.local = hosted, default, local
        self.tag = (hosted or local or default).tag
        self.skip_until = 0.0

    async def synthesize(self, text: str, language: str) -> bytes:
        import time

        if self.hosted is None:
            if self.local is not None:
                return await self.local.synthesize(text, language)
            return await self.default.synthesize(text, language)
        if time.monotonic() >= self.skip_until:
            try:
                pieces = [text] if getattr(self.hosted, "whole", False) else (split_sentences(text) or [text])   # Azure takes the whole reply at once
                clips = await asyncio.gather(*(self.hosted.synthesize(piece, language) for piece in pieces))
                return join_wavs(list(clips))
            except Exception as exc:  # out of credit, a network fault: a caller still hears a voice rather than a broken call
                response = getattr(exc, "response", None)
                status = response.status_code if response is not None else None
                pause = self.PAUSE_AFTER.get(status, self.PAUSE_OTHER)
                self.skip_until = time.monotonic() + pause
                log.warning("the hosted voice failed (%s%s); using the %s for %d s", type(exc).__name__,
                            f", HTTP {status}: {response.text[:120]}" if response is not None else "", "voice on this machine" if self.local else "stand-in voice", pause)
        if self.local is not None:
            return FallbackAudio(await self.local.synthesize(text, language))
        return FallbackAudio(await self.default.synthesize(text, language))


def build_tts(settings):
    """The hosted voice (Spitch or Azure) when its key is set, with a voice on this machine (Piper) as back-up; the voice on this machine alone when only it is set; the
    silent stand-in when neither is. Never a reason to fail at start-up: a fresh checkout runs with no keys."""
    standin = StandInTTS()
    provider = (settings.tts_provider or "spitch").strip().lower()
    if provider not in ("spitch", "azure", "piper", "standin"):
        raise ValueError(f"unknown TTS_PROVIDER {provider!r} (use spitch, azure, piper or standin)")
    local = build_local_voice(settings) if provider != "standin" else None
    hosted = None
    if provider == "spitch":
        if settings.spitch_api_key:
            hosted = SpitchTTS(settings.spitch_api_key, settings.spitch_voice_en, settings.tts_hosted_speed)
        else:
            log.warning("TTS_PROVIDER=spitch but SPITCH_API_KEY is not set: %s", "using the voice on this machine" if local else "using the silent stand-in voice")
    if provider == "azure":
        if settings.azure_speech_key and settings.azure_speech_region:
            hosted = AzureTTS(settings.azure_speech_key, settings.azure_speech_region, settings.azure_voice, settings.tts_hosted_speed)
        else:
            log.warning("TTS_PROVIDER=azure but AZURE_SPEECH_KEY or AZURE_SPEECH_REGION is not set: %s",
                        "using the voice on this machine" if local else "using the silent stand-in voice")
    if hosted is None and local is None:
        return standin
    return RoutedTTS(hosted, standin, local=local)


def build_local_voice(settings):
    """The voice on this machine, if a model is set and the package is there. Never a reason to fail at start-up: without it the stand-in is the fallback."""
    import os

    model = (getattr(settings, "piper_model", "") or "").strip()
    if not model:
        return None
    if not os.path.exists(model):
        log.warning("PIPER_MODEL is set but %s does not exist: no voice on this machine", model)
        return None
    try:
        voice = PiperTTS(model, getattr(settings, "piper_speed", 1.0))
    except Exception as exc:
        log.warning("the voice on this machine could not be loaded (%s: %s)", type(exc).__name__, str(exc)[:160])
        return None
    log.info("voice on this machine: %s", voice.tag)
    return voice
