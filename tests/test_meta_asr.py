"""Speech to text from Meta's Muse Voice Transcribe: the request is what Meta's API expects, a heard sentence is good enough to act on, and silence is not."""

import asyncio
import json

import httpx
import pytest

from sofa.clients.asr import MAX_KEYWORD, MetaASRClient
from sofa.config import Settings
from sofa.container import build_asr

REAL_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def no_speech_settings_from_the_environment(monkeypatch):
    """A developer machine may have real settings in its environment: these tests describe what happens without them, unless a test sets them."""
    for name in ("ASR_URL", "ASR_PROVIDER", "ASR_API_KEY", "ASR_MODEL", "ASR_KEYWORDS", "LLM_API_KEY", "SERVICES_ENABLED", "SYNTHETIC_HOSPITAL"):
        monkeypatch.delenv(name, raising=False)


def client_with(handler, **kw):
    """A recogniser whose HTTP calls go to `handler` instead of the internet. Returns (client, the requests it received)."""
    seen = []

    def respond(request):
        seen.append(request)
        return handler(request)

    c = MetaASRClient("https://api.meta.ai", "meta-key", **kw)
    c.http = REAL_CLIENT(transport=httpx.MockTransport(respond))
    return c, seen


def request_part(request) -> dict:
    """The JSON part named "request" from the multipart body the recogniser sent."""
    body = request.content.decode("latin-1")
    return json.loads(body.split("\r\n\r\n", 1)[1].split("\r\n--", 1)[0])


def test_the_request_is_what_metas_api_expects():
    c, seen = client_with(lambda r: httpx.Response(200, json={"sessionId": "s", "transcript": "  book  an appointment in Surulere ", "audioDurationMs": 1500, "turns": []}),
                          keywords=("Surulere", "antenatal", ""))
    out = asyncio.run(c.transcribe(b"RIFFwav", "en"))
    request = seen[0]
    assert str(request.url) == "https://api.meta.ai/v1/asr/transcribe" and request.headers["accept"] == "application/json"
    body = request.content.decode("latin-1")
    assert 'name="request"' in body and 'name="audio"' in body and "audio/wav" in body and "RIFFwav" in body
    assert request_part(request) == {"model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV", "mode": "ENDPOINTING", "languageBias": ["English"], "keywords": ["Surulere", "antenatal"]}
    assert (out.text, out.language, out.model) == ("book an appointment in Surulere", "en", "muse-voice-transcribe-1.0") and out.confidence > -1.3


def test_the_request_has_no_keyword_list_when_there_are_no_keywords():
    c, seen = client_with(lambda r: httpx.Response(200, json={"transcript": "hello"}))
    asyncio.run(c.transcribe(b"RIFFwav", "en"))
    assert "keywords" not in request_part(seen[0])


def test_a_keyword_longer_than_thirty_characters_is_left_out_because_the_api_refuses_it():
    long_word = "x" * (MAX_KEYWORD + 1)
    exact = "y" * MAX_KEYWORD
    c, seen = client_with(lambda r: httpx.Response(200, json={"transcript": "hello"}), keywords=(long_word, exact, "Aguda", "Aguda"))
    asyncio.run(c.transcribe(b"RIFFwav", "en"))
    assert MAX_KEYWORD == 30 and request_part(seen[0])["keywords"] == [exact, "Aguda"]            # too long: dropped; a repeat: said once


def test_at_most_a_hundred_and_fifty_keywords_are_sent():
    c = MetaASRClient("https://api.meta.ai", "meta-key", keywords=tuple(f"word{i}" for i in range(400)))
    assert len(c.keywords) == 150 and c.keywords[0] == "word0"


def test_the_model_is_a_setting():
    c, seen = client_with(lambda r: httpx.Response(200, json={"transcript": "hello"}), model="muse-voice-transcribe-2.0")
    out = asyncio.run(c.transcribe(b"RIFFwav", "en"))
    assert request_part(seen[0])["model"] == "muse-voice-transcribe-2.0" and out.model == "muse-voice-transcribe-2.0"


def test_the_key_is_sent_as_a_bearer_token_and_the_address_loses_its_trailing_slash():
    c = MetaASRClient("https://api.meta.ai/", "meta-key")
    assert c.base == "https://api.meta.ai" and c.http.headers["authorization"] == "Bearer meta-key" and not c.stand_in


def test_silence_is_not_acted_on():
    c, _ = client_with(lambda r: httpx.Response(200, json={"sessionId": "s", "transcript": "", "audioDurationMs": 900, "turns": []}))
    out = asyncio.run(c.transcribe(b"RIFFwav", "en"))
    assert out.text == "" and out.confidence < -1.3           # below the gate the voice route uses, so it is treated as not heard


def test_an_answer_with_no_transcript_field_is_treated_as_not_heard():
    c, _ = client_with(lambda r: httpx.Response(200, json={"sessionId": "s"}))
    out = asyncio.run(c.transcribe(b"RIFFwav", "en"))
    assert out.text == "" and out.confidence < -1.3


def test_an_error_from_meta_is_raised_for_the_voice_route_to_handle():
    c, _ = client_with(lambda r: httpx.Response(401, json={"error": {"code": "invalid_api_key"}}))
    with pytest.raises(httpx.HTTPStatusError) as raised:
        asyncio.run(c.transcribe(b"RIFFwav", "en"))
    assert raised.value.response.status_code == 401


# ---- the stand-in recogniser used by the simulator and the tests -------------------------------------------------------------------


def test_the_stand_in_recogniser_reads_the_text_the_simulator_recorded_and_sends_nothing():
    c = MetaASRClient("inprocess://mock")
    assert c.stand_in and c.http is None
    out = asyncio.run(c.transcribe(b"MOCK[en]:Please  help me find the\nnearest clinic for antenatal care.", "en"))
    assert out.text == "Please help me find the nearest clinic for antenatal care." and out.model == "stand-in-asr" and out.confidence > -1.3


def test_the_stand_in_recogniser_hears_nothing_in_audio_that_is_not_a_simulated_recording():
    out = asyncio.run(MetaASRClient("inprocess://mock").transcribe(b"RIFF....WAVEfmt ", "en"))
    assert out.text == "" and out.confidence < -1.3


# ---- choosing the recogniser from the settings -------------------------------------------------------------------------------------


def test_the_recogniser_is_the_stand_in_until_an_address_is_set():
    plain = build_asr(Settings(_env_file=None))
    assert isinstance(plain, MetaASRClient) and plain.stand_in


def test_the_recogniser_is_given_the_health_names_and_keeps_every_keyword_within_the_limit():
    meta = build_asr(Settings(_env_file=None, asr_url="https://api.meta.ai", llm_api_key="k", services_enabled="health", asr_keywords="Talk"))
    assert isinstance(meta, MetaASRClient) and meta.base == "https://api.meta.ai"
    for name in ("Talk", "Surulere", "amoxicillin", "Oncology Care Centre Ikeja", "Aguda"):
        assert name in meta.keywords
    assert len(meta.keywords) <= 150 and all(len(k) <= 30 for k in meta.keywords)           # the API refuses a longer word
    assert len(set(meta.keywords)) == len(meta.keywords)


def test_without_the_health_network_only_the_words_in_the_settings_are_listened_for():
    plain = build_asr(Settings(_env_file=None, asr_url="https://api.meta.ai", llm_api_key="k", services_enabled="none", synthetic_hospital=False, asr_keywords="Talk, Surulere "))
    assert plain.keywords == ["Talk", "Surulere"]


def test_the_speech_key_is_the_language_model_key_unless_a_speech_key_is_set():
    shared = build_asr(Settings(_env_file=None, asr_url="https://api.meta.ai", llm_api_key="shared-key"))
    assert shared.http.headers["authorization"] == "Bearer shared-key"
    own = build_asr(Settings(_env_file=None, asr_url="https://api.meta.ai", llm_api_key="shared-key", asr_api_key="speech-key", asr_model="muse-voice-transcribe-2.0"))
    assert own.http.headers["authorization"] == "Bearer speech-key" and own.model == "muse-voice-transcribe-2.0"
