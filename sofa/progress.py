"""The steps of a turn as they happen, for a page that shows them live (the Call on the Try it page): heard, deciding, asking a provider, writing the reply,
voicing it. A turn that nobody is watching tells nobody. Only the kind of step and a few safe details travel: never a phone number or a secret."""

import asyncio
from contextvars import ContextVar

listening: ContextVar[asyncio.Queue | None] = ContextVar("talk_progress", default=None)
SAFE = ("action", "op", "provider", "text")


def tell(step: str, **data) -> None:
    queue = listening.get()
    if queue is not None:
        queue.put_nowait({"step": step, **{k: v for k, v in data.items() if k in SAFE and v not in (None, "")}})
