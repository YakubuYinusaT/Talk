"""A recording is downloaded only over https from the telephony provider's own hosts, with every redirect checked, and one that is not on the provider's server yet is asked for again, a little later each time."""

import httpx
import pytest

from sofa.audio import check_recording_address, fetch_recording, mock_recording_url

ALLOWED = ("africastalking.com", "at-internal.com")


@pytest.fixture
def anyio_backend():
    return "asyncio"


def client(statuses):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        status = statuses[min(len(seen), len(statuses) - 1)]
        seen.append(status)
        return httpx.Response(status, content=b"AUDIO" if status == 200 else b"")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


def routed(table):
    """A client that answers each address from a table of (status, headers), and records the addresses it was asked for."""
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        status, headers = table[str(request.url)]
        return httpx.Response(status, headers=headers, content=b"AUDIO" if status == 200 else b"")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), asked


# ---- asking again for a recording that is not there yet -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_recording_that_appears_after_two_misses_is_fetched():
    http, seen = client([404, 404, 200])
    assert await fetch_recording("https://x/y.mp3", wait=0, http=http) == b"AUDIO"
    assert seen == [404, 404, 200]


@pytest.mark.anyio
async def test_a_recording_that_never_appears_fails_after_the_attempts():
    http, seen = client([404])
    with pytest.raises(httpx.HTTPStatusError):
        await fetch_recording("https://x/y.mp3", attempts=3, wait=0, http=http)
    assert len(seen) == 3


@pytest.mark.anyio
async def test_a_real_error_such_as_a_bad_request_is_not_retried():
    http, seen = client([400])
    with pytest.raises(httpx.HTTPStatusError):
        await fetch_recording("https://x/y.mp3", wait=0, http=http)
    assert len(seen) == 1


@pytest.mark.anyio
async def test_a_busy_server_is_asked_again():
    http, seen = client([503, 429, 200])
    assert await fetch_recording("https://x/y.mp3", wait=0, http=http) == b"AUDIO"
    assert seen == [503, 429, 200]


@pytest.mark.anyio
async def test_a_connection_that_breaks_once_is_asked_again():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, content=b"AUDIO")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await fetch_recording("https://x/y.mp3", wait=0, http=http) == b"AUDIO" and len(calls) == 2


@pytest.mark.anyio
async def test_a_server_that_cannot_be_reached_at_all_fails_with_a_clear_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.ConnectError, match="could not be reached"):
        await fetch_recording("https://x/y.mp3", attempts=2, wait=0, http=http)


@pytest.mark.anyio
async def test_the_address_without_the_stray_T_is_tried_when_the_one_sent_is_not_found():
    """The first real call: ...e20aT.mp3 was 404 and ...e20a.mp3 was 200."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=b"AUDIO") if str(request.url).endswith("e20a.mp3") else httpx.Response(404)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await fetch_recording("https://gigantic.example.com/bdba7c3cc1ea786e726d936d4e47e20aT.mp3", wait=0, http=http) == b"AUDIO"
    assert seen[0].endswith("e20aT.mp3") and seen[-1].endswith("e20a.mp3")


@pytest.mark.anyio
async def test_a_simulated_recording_is_read_from_its_own_address_with_no_download():
    assert await fetch_recording(mock_recording_url("Please help me find the nearest clinic for antenatal care."), allowed=ALLOWED) == b"MOCK[en]:Please help me find the nearest clinic for antenatal care."


# ---- only https, only the provider's hosts ---------------------------------------------------------------------------------------


def test_the_provider_hosts_and_their_sub_domains_are_accepted_over_https():
    for url in ("https://africastalking.com/a.mp3", "https://voice.africastalking.com/a.mp3", "https://x.at-internal.com/a.mp3", "https://VOICE.AfricasTalking.com/a.mp3"):
        check_recording_address(url, ALLOWED)


def test_an_address_over_plain_http_or_on_another_host_is_refused():
    for url in ("http://voice.africastalking.com/a.mp3",            # not https
                "https://evil.example/a.mp3",                       # not the provider
                "https://africastalking.com.evil.example/a.mp3",    # the provider's name only at the front
                "https://notafricastalking.com/a.mp3",              # a host that merely ends with the same letters
                "https://voice.africastalking.com@evil.example/a.mp3",   # a user name that looks like the host
                "ftp://voice.africastalking.com/a.mp3",
                "file:///etc/passwd",
                "a.mp3"):
        with pytest.raises(ValueError, match="not downloaded"):
            check_recording_address(url, ALLOWED)


def test_an_empty_list_of_hosts_means_no_restriction():
    check_recording_address("http://anywhere.example/a.mp3", ())


@pytest.mark.anyio
async def test_a_recording_on_another_host_is_never_requested():
    http, seen = client([200])
    with pytest.raises(ValueError):
        await fetch_recording("https://evil.example/a.mp3", wait=0, http=http, allowed=ALLOWED)
    with pytest.raises(ValueError):
        await fetch_recording("http://voice.africastalking.com/a.mp3", wait=0, http=http, allowed=ALLOWED)
    assert seen == []


@pytest.mark.anyio
async def test_a_recording_on_a_provider_host_is_downloaded():
    http, seen = client([200])
    assert await fetch_recording("https://voice.africastalking.com/a.mp3", wait=0, http=http, allowed=ALLOWED) == b"AUDIO" and seen == [200]


# ---- redirects are checked one by one ------------------------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_redirect_to_a_provider_host_is_followed():
    http, asked = routed({"https://voice.africastalking.com/a.mp3": (302, {"location": "https://files.africastalking.com/b.mp3"}),
                          "https://files.africastalking.com/b.mp3": (200, {})})
    assert await fetch_recording("https://voice.africastalking.com/a.mp3", wait=0, http=http, allowed=ALLOWED) == b"AUDIO"
    assert asked == ["https://voice.africastalking.com/a.mp3", "https://files.africastalking.com/b.mp3"]


@pytest.mark.anyio
async def test_a_relative_redirect_stays_on_the_same_host_and_is_followed():
    http, asked = routed({"https://voice.africastalking.com/a.mp3": (301, {"location": "/b.mp3"}), "https://voice.africastalking.com/b.mp3": (200, {})})
    assert await fetch_recording("https://voice.africastalking.com/a.mp3", wait=0, http=http, allowed=ALLOWED) == b"AUDIO"


@pytest.mark.anyio
async def test_a_redirect_to_another_host_is_refused_before_it_is_requested():
    http, asked = routed({"https://voice.africastalking.com/a.mp3": (302, {"location": "https://evil.example/steal.mp3"})})
    with pytest.raises(ValueError, match="evil.example"):
        await fetch_recording("https://voice.africastalking.com/a.mp3", wait=0, http=http, allowed=ALLOWED)
    assert asked == ["https://voice.africastalking.com/a.mp3"]


@pytest.mark.anyio
async def test_a_redirect_from_https_down_to_plain_http_is_refused():
    http, asked = routed({"https://voice.africastalking.com/a.mp3": (302, {"location": "http://voice.africastalking.com/b.mp3"})})
    with pytest.raises(ValueError):
        await fetch_recording("https://voice.africastalking.com/a.mp3", wait=0, http=http, allowed=ALLOWED)
    assert len(asked) == 1


@pytest.mark.anyio
async def test_a_chain_of_redirects_that_never_ends_is_given_up():
    http, asked = routed({"https://voice.africastalking.com/a.mp3": (302, {"location": "https://voice.africastalking.com/a.mp3"})})
    with pytest.raises(httpx.HTTPStatusError):
        await fetch_recording("https://voice.africastalking.com/a.mp3", wait=0, http=http, allowed=ALLOWED)
    assert len(asked) <= 6                                          # a few hops, not a loop


@pytest.mark.anyio
async def test_when_hosts_are_listed_the_download_client_does_not_follow_redirects_by_itself(monkeypatch):
    """With a list of hosts every hop is checked by Talk, so the client it makes for itself must not follow a redirect on its own."""
    made = []
    real = httpx.AsyncClient

    def spy(**kw):
        made.append(kw)
        return real(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"AUDIO")), **kw)

    monkeypatch.setattr("sofa.audio.httpx.AsyncClient", spy)
    assert await fetch_recording("https://voice.africastalking.com/a.mp3", wait=0, allowed=ALLOWED) == b"AUDIO"
    assert made[0]["follow_redirects"] is False
    assert await fetch_recording("https://anywhere.example/a.mp3", wait=0) == b"AUDIO"
    assert made[1]["follow_redirects"] is True
