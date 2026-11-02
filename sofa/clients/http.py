import asyncio
import logging
import ssl

import httpx

log = logging.getLogger("sofa.http")

# Connection-level failures: a dropped or garbled secure connection, a refused connection.
# Not timeouts (a retry would make the caller wait twice as long) and not HTTP error answers (the host did answer).
RETRYABLE = (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError,
             httpx.CloseError, ssl.SSLError, ConnectionError)


class RetryingClient(httpx.AsyncClient):
    """An HTTP client that tries a request again when the connection itself broke. The model and voice calls (speech to text, the language
    model, text to speech) can safely be repeated, and one bad connection must not cost a caller a turn."""

    def __init__(self, *args, retries: int = 2, **kwargs):
        super().__init__(*args, **kwargs)
        self.retries = retries

    async def post(self, *args, **kwargs):
        for attempt in range(self.retries + 1):
            try:
                return await super().post(*args, **kwargs)
            except RETRYABLE as exc:
                if attempt == self.retries:
                    raise
                log.warning("connection broke (%s); trying again (%d of %d)", type(exc).__name__, attempt + 1, self.retries)
                await asyncio.sleep(0.2 * (attempt + 1))


def http_for(url: str, api_key: str = "") -> tuple[httpx.AsyncClient, str]:
    """Return (client, base_url). inprocess://mock routes straight into the in-process stand-in service (mocks/), so nothing leaves this machine.
    api_key is sent as a Bearer token."""
    if url.startswith("inprocess://"):
        from mocks.model_mock import app as mock_app

        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_app), timeout=30)
        return client, "http://mock"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return RetryingClient(timeout=30, headers=headers), url.rstrip("/")
