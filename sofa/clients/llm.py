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
        """Guided JSON for any small pydantic model. Returns (model instance, raw json); a bad answer is an empty instance."""
        try:
            constraint = self.schema_format("params", json_schema or model.model_json_schema())
            user = f"TRANSCRIPT: {transcript}"
            if alternatives:  # another reading of the same audio
                user += "\nALSO HEARD (same audio, read another way): " + " | ".join(alternatives)
            raw = json.loads(await self._chat(system, user, max_tokens=EXTRACT_MAX_TOKENS, **constraint))
            return model.model_validate(raw), raw
        except (ValidationError, json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError) as exc:
            # Any answer that is not shaped as asked is an empty reading: no content at all (None), no choices, a list where text should be, or text that is not JSON.
            log.warning("extraction rejected: %s", exc)
            return model(), {"error": str(exc)}
