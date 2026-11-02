"""What the tests share: the numbers and the clock they use, the stand-in internet between Talk and the providers, and the helper that places a call."""

from datetime import datetime

import httpx

from scripts.simulate_call import run_call

SECRET, TALK_NUMBER, CALLER = "test-secret", "+2348000009999", "+2348055550001"
OTHER = "+2348055550002"
FIXED = datetime(2026, 10, 27, 10, 15)   # a Tuesday morning in Lagos


class Providers(httpx.AsyncBaseTransport):
    """The internet between Talk and the providers: each https://health.example/synthetic/<name>/rpc goes to the provider app of that name."""

    def __init__(self, apps):
        self.apps, self.down, self.seen, self.before_book = apps, set(), [], None

    async def handle_async_request(self, request):
        slug = request.url.path.split("/")[2]
        self.seen.append((slug, request.content.decode()))
        if self.before_book and '"tool":"book"' in request.content.decode():
            hook, self.before_book = self.before_book, None
            hook()
        if slug in self.down:
            return httpx.Response(503, json={"error": "down"})
        inner = httpx.Request(request.method, request.url.copy_with(path="/rpc"), headers=request.headers, content=request.content)
        return await httpx.ASGITransport(app=self.apps[slug]).handle_async_request(inner)


def call(client, lines, caller=CALLER):
    """Places a call to the orchestrator number, says each line in turn, and returns everything Talk said, the greeting first."""
    return run_call(client, lines, caller, TALK_NUMBER, SECRET, echo=lambda *_: None)


def appointments(happ, slug):
    return [dict(r) for r in happ.state.providers[slug].state.store.db.execute("SELECT * FROM appointments WHERE status = 'booked'").fetchall()]
