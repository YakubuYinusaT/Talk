"""One broken connection to a model or voice service must not cost a caller a turn."""

import asyncio
import ssl

import httpx
import pytest

from sofa.clients import http as http_module
from sofa.clients.http import RetryingClient, http_for


@pytest.fixture(autouse=True)
def waits(monkeypatch):
    """The pause between two tries is recorded instead of waited for, so these tests run at once and can check how the pause grows."""
    recorded = []

    async def fake_sleep(seconds):
        recorded.append(seconds)

    monkeypatch.setattr(http_module.asyncio, "sleep", fake_sleep)
    return recorded


def client(handler, retries=2):
    return RetryingClient(transport=httpx.MockTransport(handler), retries=retries)


def run(coro):
    return asyncio.run(coro)


def test_a_broken_connection_is_tried_again_and_then_succeeds(waits):
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ReadError("connection garbled")
        return httpx.Response(200, json={"ok": True})

    r = run(client(handler).post("http://models.example/x", json={}))
    assert r.json() == {"ok": True} and len(calls) == 3
    assert waits == [0.2, 0.4]                                # a little longer before each new try


def test_an_ssl_error_is_retried_too():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise ssl.SSLError("sslv3 alert bad record mac")
        return httpx.Response(200)

    assert run(client(handler).post("http://models.example/x")).status_code == 200 and len(calls) == 2


@pytest.mark.parametrize("fault", [httpx.ConnectError("refused"), httpx.RemoteProtocolError("server disconnected"), httpx.WriteError("broken pipe"), ConnectionResetError("reset")])
def test_each_kind_of_broken_connection_is_tried_again(fault):
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise fault
        return httpx.Response(200)

    assert run(client(handler).post("http://models.example/x")).status_code == 200 and len(calls) == 2


def test_it_gives_up_after_the_retries_and_says_why(waits):
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("refused")

    with pytest.raises(httpx.ConnectError):
        run(client(handler, retries=2).post("http://models.example/x"))
    assert len(calls) == 3 and len(waits) == 2


def test_with_no_retries_the_first_failure_is_final():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("refused")

    with pytest.raises(httpx.ConnectError):
        run(client(handler, retries=0).post("http://models.example/x"))
    assert len(calls) == 1


def test_an_error_answer_from_the_host_is_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500)

    assert run(client(handler).post("http://models.example/x")).status_code == 500 and len(calls) == 1


def test_a_timeout_is_not_retried_because_the_caller_would_wait_twice():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("too slow")

    with pytest.raises(httpx.ReadTimeout):
        run(client(handler).post("http://models.example/x"))
    assert len(calls) == 1


# ---- choosing the client for an address --------------------------------------------------------------------------------------------


def test_a_real_address_gets_a_retrying_client_with_the_key_and_no_trailing_slash():
    http, base = http_for("https://api.meta.ai/", "a-private-key-value")
    assert isinstance(http, RetryingClient) and base == "https://api.meta.ai"
    assert http.headers["authorization"] == "Bearer a-private-key-value"
    assert http.retries == 2


def test_without_a_key_no_authorization_header_is_sent():
    http, _ = http_for("https://api.meta.ai")
    assert "authorization" not in http.headers


def test_the_in_process_address_reaches_the_stand_in_service_without_leaving_this_machine():
    async def visit():
        http, base = http_for("inprocess://mock", "ignored-key")
        try:
            return base, (await http.get(f"{base}/health")).json()
        finally:
            await http.aclose()

    base, answer = run(visit())
    assert base == "http://mock" and answer["ok"] is True
