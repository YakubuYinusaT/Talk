import asyncio
import json
import logging

from pydantic import ValidationError

from .http import http_for

log = logging.getLogger("sofa.llm")

PROVIDERS = ("meta", "openai")

DROPPED = {"title", "default", "minLength", "maxLength", "minimum", "maximum"}  # keywords the strict hosted formats do not accept


def strict_schema(schema):
    """A hosted provider's strict mode wants every property required and no extra ones, and a smaller set of keywords."""
    if isinstance(schema, list):
        return [strict_schema(x) for x in schema]
    if not isinstance(schema, dict):
        return schema
    out = {}
    for k, v in schema.items():
        if k in DROPPED:
            continue
        # the names under "properties" are the caller's own field names: never filtered, only their schemas are
        out[k] = {n: strict_schema(sub) for n, sub in v.items()} if k == "properties" else strict_schema(v)
    if out.get("type") == "object" and "properties" in out:
        out["required"] = list(out["properties"])
        out["additionalProperties"] = False
    return out


EXTRACT_MAX_TOKENS = 400  # the front desk's understanding and wording answers


REPAIR_SECONDS = 4.0  # the longest a caller waits for the second try at an answer that did not fit the format
# What an answer that is not shaped as asked looks like: no content at all (None), no choices, a list where text should be, text that is not JSON, or JSON
# that does not fit the model class.
SHAPE_ERRORS = (ValidationError, json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError)

META_REASONING_ROOM = 800  # on Meta's models the thinking tokens count against max_tokens: the cap leaves room for them, and only what is used is billed


class LLMClient:
    """Chat completions that answer in JSON. llm_provider="meta" is the Meta Model API (Muse Spark); "openai" is any hosted model behind an OpenAI-style API.
    The address inprocess://mock is the stand-in model that runs inside this process."""

    def __init__(self, url: str, model: str, api_key: str = "", provider: str = "meta", reasoning_effort: str = "minimal"):
        if provider not in PROVIDERS:
            raise ValueError(f"unknown LLM_PROVIDER {provider!r} (use meta or openai)")
        self.http, self.base = http_for(url, api_key)
        self.model = model
        self.meta = provider == "meta"
        self.reasoning_effort = reasoning_effort
        self.stats = {"answers": 0, "rejected": 0, "repaired": 0, "failed": 0}   # shown on /health, so a rising rate of bad answers is seen

    def schema_format(self, name: str, schema: dict) -> dict:
        """The answer-format option for a JSON schema, in the shape the hosted API accepts."""
        return {"response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": strict_schema(schema)}}}

    async def _chat(self, system: str, user: str, max_tokens: int = 200, **extra) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            **extra,
        }
        if self.meta:
            payload.update(max_tokens=max_tokens + META_REASONING_ROOM, reasoning_effort=self.reasoning_effort,   # the shortest thinking pass: a caller is waiting
                           prompt_cache_key="talk")  # a stable key sends Talk's calls to the same place, so the long fixed start of each prompt is reused
        else:
            payload["max_completion_tokens"] = max_tokens  # newer hosted models use this name, and some accept no temperature
        resp = await self.http.post(f"{self.base}/v1/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def extract(self, model, system: str, transcript: str, alternatives: list[str] | None = None, json_schema: dict | None = None):
        """Guided JSON for any small pydantic model. Returns (model instance, raw json). An answer that does not fit the format is asked for once more, saying
        why, and if the second answer does not fit either, or is slow, the result is an empty instance and the rules carry on."""
        constraint = self.schema_format("params", json_schema or model.model_json_schema())
        user = f"TRANSCRIPT: {transcript}"
        if alternatives:  # another reading of the same audio
            user += "\nALSO HEARD (same audio, read another way): " + " | ".join(alternatives)
        self.stats["answers"] += 1
        try:
            return self._read(model, await self._chat(system, user, max_tokens=EXTRACT_MAX_TOKENS, **constraint))
        except SHAPE_ERRORS as exc:
            first = exc
        self.stats["rejected"] += 1
        log.warning("extraction rejected, asking once more: %s", first)
        again = (f"{system}\nYOUR LAST ANSWER COULD NOT BE USED ({str(first)[:160]}). Answer again with JSON only, exactly in the format asked, with every field present.")
        try:
            got = self._read(model, await asyncio.wait_for(self._chat(again, user, max_tokens=EXTRACT_MAX_TOKENS, **constraint), timeout=REPAIR_SECONDS))
        except (asyncio.TimeoutError, Exception) as exc:     # a second bad answer, a slow one or a failed request: the rules carry on, and the call goes on
            self.stats["failed"] += 1
            log.warning("extraction failed after a second try: %s", type(exc).__name__)
            return model(), {"error": str(first)}
        self.stats["repaired"] += 1
        return got

    async def see(self, model, system: str, image: bytes, mime: str, caption: str = ""):
        """What a photo shows, read by the model, as an instance of `model`. Returns an empty instance when it cannot be read."""
        import base64

        content = [{"type": "text", "text": f"CAPTION: {caption or 'none'}"},
                   {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(image).decode()}"}}]
        payload = {"model": self.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
                   **self.schema_format("photo", model.model_json_schema())}
        if self.meta:
            payload.update(max_tokens=EXTRACT_MAX_TOKENS + META_REASONING_ROOM, reasoning_effort=self.reasoning_effort)
        else:
            payload["max_completion_tokens"] = EXTRACT_MAX_TOKENS
        try:
            resp = await self.http.post(f"{self.base}/v1/chat/completions", json=payload)
            resp.raise_for_status()
            return self._read(model, resp.json()["choices"][0]["message"]["content"])[0]
        except Exception as exc:     # a photo that cannot be read costs the person nothing: they are asked to type instead
            log.warning("a photo could not be read: %s", type(exc).__name__)
            return model()

    @staticmethod
    def _read(model, content):
        raw = json.loads(content)
        return model.model_validate(raw), raw
