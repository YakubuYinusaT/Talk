"""The language model is the Meta Model API (Muse Spark) or any hosted model behind an OpenAI-style API: the request shape differs, the answers do not."""

import asyncio
import json

import httpx
import pytest
from pydantic import BaseModel

from sofa.clients.http import RetryingClient
from sofa.clients.llm import EXTRACT_MAX_TOKENS, META_REASONING_ROOM, PROVIDERS, LLMClient, strict_schema


class Reading(BaseModel):
    """What the model is asked to fill in for one turn of a call."""
    action: str = "unclear"
    area: str | None = None


class FakeResp:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class FakeHttp:
    """Stands in for the HTTP client: records every request and answers with the given model reply."""

    def __init__(self, content=None, body=None):
        self.body = body if body is not None else {"choices": [{"message": {"content": content}}]}
        self.payloads = []

    async def post(self, url, json):  # noqa: A002
        self.payloads.append((url, json))
        return FakeResp(self.body)


ANSWER = '{"action": "find_clinic", "area": "Surulere"}'
SAID = "Please help me find the nearest clinic for antenatal care."


def client(provider, content=ANSWER, url="https://api.meta.ai", **kw):
    c = LLMClient(url, "some-model", "k", provider, **kw)
    c.http = FakeHttp(content)
    return c


def test_the_two_providers_are_meta_and_an_openai_style_endpoint():
    assert PROVIDERS == ("meta", "openai")


def test_an_unknown_provider_is_refused_with_the_choices_named():
    for name in ("nonsense", "local", ""):
        with pytest.raises(ValueError, match="meta or openai"):
            LLMClient("https://llm.example", "some-model", "k", name)


def test_a_real_address_gets_a_client_that_sends_the_key_and_the_stand_in_address_stays_inside_the_process():
    real = LLMClient("https://api.meta.ai/", "muse-spark-1.3", "secret-value")
    assert isinstance(real.http, RetryingClient) and real.base == "https://api.meta.ai"          # no double slash in the request address
    assert real.http.headers["authorization"] == "Bearer secret-value"
    inside = LLMClient("inprocess://mock", "muse-spark-1.3")
    assert inside.base == "http://mock" and not isinstance(inside.http, RetryingClient)


def test_meta_gets_the_strict_format_the_shortest_thinking_pass_and_room_for_thinking_tokens():
    c = client("meta")
    obj, raw = asyncio.run(c.extract(Reading, "SYSTEM", SAID))
    url, payload = c.http.payloads[0]
    fmt = payload["response_format"]["json_schema"]
    assert (obj.action, obj.area) == ("find_clinic", "Surulere") and raw == json.loads(ANSWER)
    assert url == "https://api.meta.ai/v1/chat/completions"
    assert fmt["strict"] is True and fmt["schema"]["additionalProperties"] is False
    assert fmt["schema"]["required"] == ["action", "area"]                   # strict mode wants every field required
    assert payload["reasoning_effort"] == "minimal" and payload["max_tokens"] == EXTRACT_MAX_TOKENS + META_REASONING_ROOM    # thinking tokens share the cap
    assert payload["prompt_cache_key"] == "talk"
    assert "max_completion_tokens" not in payload and "temperature" not in payload


def test_the_system_text_and_the_caller_words_are_sent_as_the_two_messages():
    c = client("meta")
    asyncio.run(c.extract(Reading, "SYSTEM TEXT", SAID))
    messages = c.http.payloads[0][1]["messages"]
    assert messages == [{"role": "system", "content": "SYSTEM TEXT"}, {"role": "user", "content": f"TRANSCRIPT: {SAID}"}]
    assert c.http.payloads[0][1]["model"] == "some-model"


def test_another_reading_of_the_same_audio_is_offered_to_the_model_as_well():
    c = client("meta")
    asyncio.run(c.extract(Reading, "SYSTEM", "I am in Sir Lerry", alternatives=["I am in Surulere", "I am in Sure Lerry"]))
    user = c.http.payloads[0][1]["messages"][1]["content"]
    assert user == "TRANSCRIPT: I am in Sir Lerry\nALSO HEARD (same audio, read another way): I am in Surulere | I am in Sure Lerry"


def test_meta_reasoning_effort_is_a_setting():
    c = client("meta", reasoning_effort="low")
    asyncio.run(c.extract(Reading, "SYSTEM", SAID))
    assert c.http.payloads[0][1]["reasoning_effort"] == "low"


def test_a_hosted_openai_style_model_gets_the_strict_format_and_none_of_the_meta_only_options():
    c = client("openai", url="https://llm.example")
    obj, _ = asyncio.run(c.extract(Reading, "SYSTEM", SAID))
    url, payload = c.http.payloads[0]
    fmt = payload["response_format"]["json_schema"]
    assert obj.action == "find_clinic" and url == "https://llm.example/v1/chat/completions"
    assert fmt["strict"] is True and fmt["schema"]["additionalProperties"] is False
    assert fmt["schema"]["required"] == ["action", "area"]
    assert payload["max_completion_tokens"] == EXTRACT_MAX_TOKENS
    for only_meta in ("max_tokens", "reasoning_effort", "prompt_cache_key", "temperature"):
        assert only_meta not in payload


def test_a_schema_given_by_the_caller_is_used_instead_of_the_one_the_model_class_makes():
    c = client("meta")
    asyncio.run(c.extract(Reading, "SYSTEM", SAID, json_schema={"type": "object", "properties": {"action": {"type": "string"}}}))
    assert c.http.payloads[0][1]["response_format"]["json_schema"]["schema"]["required"] == ["action"]


def test_the_extraction_has_room_to_finish_its_answer():
    """With too small a cap the real model's JSON was cut off mid-sentence and every turn was treated as not understood."""
    c = client("meta")
    asyncio.run(c.extract(Reading, "SYSTEM", SAID))
    assert c.http.payloads[0][1]["max_tokens"] >= 1000


def test_strict_schema_leaves_field_names_alone_and_drops_unsupported_keywords():
    out = strict_schema({"type": "object", "title": "X", "properties": {"title": {"type": "string", "minLength": 10, "default": ""},
                                                                      "n": {"type": "integer", "minimum": 1}}})
    assert list(out["properties"]) == ["title", "n"]         # a field called "title" is still there
    assert out["properties"]["title"] == {"type": "string"} and out["properties"]["n"] == {"type": "integer"}
    assert "title" not in out and out["required"] == ["title", "n"] and out["additionalProperties"] is False


def test_strict_schema_reaches_nested_objects_and_lists():
    out = strict_schema({"type": "object", "properties": {"choices": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string", "maxLength": 5}}}}}})
    inner = out["properties"]["choices"]["items"]
    assert inner == {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"], "additionalProperties": False}


# ---- an answer the model gets wrong is an empty reading, not a crash --------------------------------------------------------------------


def test_an_answer_that_is_not_json_is_an_empty_reading_with_the_reason():
    obj, raw = asyncio.run(client("meta", "I am sorry, I could not do that.").extract(Reading, "SYSTEM", SAID))
    assert obj == Reading() and "error" in raw


def test_an_answer_that_breaks_the_schema_is_an_empty_reading_with_the_reason():
    obj, raw = asyncio.run(client("meta", '{"action": ["not", "a", "string"], "area": null}').extract(Reading, "SYSTEM", SAID))
    assert obj == Reading() and "error" in raw


def test_an_answer_without_choices_is_an_empty_reading_with_the_reason():
    c = LLMClient("https://api.meta.ai", "some-model", "k", "meta")
    c.http = FakeHttp(body={"error": {"message": "overloaded"}})
    obj, raw = asyncio.run(c.extract(Reading, "SYSTEM", SAID))
    assert obj == Reading() and "error" in raw


@pytest.mark.parametrize("body", [
    {"choices": [{"message": {"content": None}}]},       # the model answered with no content at all
    {"choices": [{"message": {}}]},                       # a message with no content field
    {"choices": []},                                      # an empty list of choices
    {"choices": [None]},                                  # a choice that is not an object
    {"choices": [{"message": {"content": ["not", "text"]}}]},     # content that is not text
    ["not an object"],                                    # a reply that is not an object at all
])
def test_any_malformed_answer_from_the_model_service_is_an_empty_reading_with_the_reason(body):
    c = LLMClient("https://api.meta.ai", "some-model", "k", "meta")
    c.http = FakeHttp(body=body)
    obj, raw = asyncio.run(c.extract(Reading, "SYSTEM", SAID))
    assert obj == Reading() and "error" in raw


def test_an_error_status_from_the_model_service_is_raised_for_the_caller_to_handle():
    def refuse(request):
        return httpx.Response(429, json={"error": "slow down"})

    c = LLMClient("https://api.meta.ai", "some-model", "k", "meta")
    c.http = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(c.extract(Reading, "SYSTEM", SAID))


class Answers:
    """Stands in for the HTTP client and gives one prepared answer to each request, in order."""

    def __init__(self, *contents, delay=0.0):
        self.contents, self.delay, self.payloads = list(contents), delay, []

    async def post(self, url, json):  # noqa: A002
        self.payloads.append(json)
        if self.delay and len(self.payloads) > 1:
            await asyncio.sleep(self.delay)
        return FakeResp({"choices": [{"message": {"content": self.contents.pop(0)}}]})


def test_an_answer_that_does_not_fit_is_asked_for_once_more_with_the_reason():
    c = LLMClient("https://api.meta.ai", "some-model", "k", "meta")
    c.http = Answers("this is not JSON", ANSWER)
    obj, _ = asyncio.run(c.extract(Reading, "SYSTEM", SAID))
    assert obj.action == "find_clinic" and len(c.http.payloads) == 2
    assert "YOUR LAST ANSWER COULD NOT BE USED" in c.http.payloads[1]["messages"][0]["content"]
    assert c.stats == {"answers": 1, "rejected": 1, "repaired": 1, "failed": 0}


def test_a_second_answer_that_does_not_fit_either_leaves_an_empty_reading_and_no_third_try():
    c = LLMClient("https://api.meta.ai", "some-model", "k", "meta")
    c.http = Answers("not JSON", "still not JSON")
    obj, raw = asyncio.run(c.extract(Reading, "SYSTEM", SAID))
    assert obj == Reading() and "error" in raw and len(c.http.payloads) == 2 and c.stats["failed"] == 1


def test_a_slow_second_try_is_given_up_so_the_caller_is_not_kept_waiting(monkeypatch):
    import sofa.clients.llm as llm

    monkeypatch.setattr(llm, "REPAIR_SECONDS", 0.05)
    c = LLMClient("https://api.meta.ai", "some-model", "k", "meta")
    c.http = Answers("not JSON", ANSWER, delay=1.0)
    obj, _ = asyncio.run(c.extract(Reading, "SYSTEM", SAID))
    assert obj == Reading() and c.stats["failed"] == 1


def test_a_good_first_answer_is_never_asked_for_again():
    c = LLMClient("https://api.meta.ai", "some-model", "k", "meta")
    c.http = Answers(ANSWER)
    obj, _ = asyncio.run(c.extract(Reading, "SYSTEM", SAID))
    assert obj.action == "find_clinic" and len(c.http.payloads) == 1 and c.stats["rejected"] == 0
