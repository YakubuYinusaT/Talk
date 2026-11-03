"""Calling Talk from the browser on the Try it page: the visitor's speech goes through the same speech recognition, front desk and voice as a phone call,
inside the same limits as a typed conversation. The page offers a call first and a chat second, with the phone numbers when they are set."""

import base64

from sofa.models import Call
from sofa.routes import tryit


def spoken(text: str) -> str:
    """What the stand-in speech recogniser hears as `text`, sent the way the page sends a recording."""
    return base64.b64encode(f"MOCK[en]:{text}".encode()).decode()


def open_call(client):
    got = client.post("/try/start", json={"mode": "call"})
    assert got.status_code == 200, got.text
    return got.json()


def test_the_page_offers_a_call_first_and_a_chat_second(client):
    page = client.get("/try").text
    assert page.index('id="tab-call"') < page.index('id="tab-chat"') and 'aria-selected="true" aria-controls="call-mode"' in page
    assert "Start call" in page


def test_the_page_shows_both_phone_numbers_when_they_are_set(client, happ):
    s = happ.state.svc.settings
    s.test_number, s.test_number_international = "+234 700 000 0001", "+1 415 555 0100"
    page = client.get("/try").text
    assert 'href="tel:+2347000000001"' in page and 'href="tel:+14155550100"' in page


def test_a_call_starts_with_the_greeting_voiced(client):
    opened = open_call(client)
    assert opened["greeting"] and opened["audio"] and opened["audio"][0].startswith("/audio/") and "voice" in opened


def test_what_the_visitor_says_is_heard_answered_and_voiced(client):
    session = open_call(client)["session"]
    got = client.post("/try/speak", json={"session": session, "audio": spoken("Please help me find the nearest clinic for antenatal care.")})
    assert got.status_code == 200, got.text
    answer = got.json()
    assert answer["heard"] == "Please help me find the nearest clinic for antenatal care."
    assert "which area of Lagos" in answer["reply"] and answer["audio"][0].startswith("/audio/")
    heard = next(s for s in answer["trace"] if s["step"] == "heard")
    assert heard["model"] != "typed"                       # the speech recogniser heard it: nothing was typed
    assert "Heard" in answer["steps_html"]


def test_a_browser_call_is_a_test_call_from_a_reserved_number(client, hdb):
    session = open_call(client)["session"]
    client.post("/try/speak", json={"session": session, "audio": spoken("Hello, do you have amoxicillin in stock, please?")})
    assert hdb.scalar(__import__("sqlalchemy").select(Call)).from_number.startswith("+2349990")      # no real number is ever texted from a browser call


def test_only_a_wav_recording_is_accepted(client):
    session = open_call(client)["session"]
    got = client.post("/try/speak", json={"session": session, "audio": base64.b64encode(b"<html>not audio</html>").decode()})
    assert got.status_code == 415


def test_a_recording_that_is_too_long_is_refused(client):
    session = open_call(client)["session"]
    got = client.post("/try/speak", json={"session": session, "audio": "A" * (tryit.MAX_AUDIO_BYTES * 2)})
    assert got.status_code == 413


def test_audio_that_is_not_base64_is_refused(client):
    session = open_call(client)["session"]
    got = client.post("/try/speak", json={"session": session, "audio": "this is not base64 at all!"})
    assert got.status_code == 400


def test_a_spoken_turn_counts_towards_the_same_limit_as_a_typed_one(client, happ):
    happ.state.svc.settings.try_max_turns = 1
    session = open_call(client)["session"]
    assert client.post("/try/speak", json={"session": session, "audio": spoken("Hello, do you have amoxicillin in stock, please?")}).status_code == 200
    assert client.post("/try/turn", json={"session": session, "text": "Thank you."}).status_code == 429


def test_a_call_from_the_website_streams_each_step_then_the_reply(client):
    import json

    session = client.post("/try/start", json={"mode": "call"}).json()["session"]
    got = client.post("/try/speak", json={"session": session, "audio": spoken("Which pharmacy in Surulere has paracetamol?"), "stream": True})
    assert got.status_code == 200 and got.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in got.text.splitlines() if line.strip()]
    steps = [e.get("step") for e in events if "step" in e]
    assert steps[:2] == ["hearing", "heard"] and "voicing" in steps
    assert events[1]["text"] == "Which pharmacy in Surulere has paracetamol?"
    done = events[-1]["done"]
    assert "Everwell Pharmacy Surulere" in done["reply"] and done["audio"]
    assert all("phone" not in e and "caller" not in e for e in events[:-1])


def test_a_streamed_call_that_is_refused_says_why(client):
    import json

    got = client.post("/try/speak", json={"session": "no-such-session", "audio": spoken("Hello"), "stream": True})
    events = [json.loads(line) for line in got.text.splitlines() if line.strip()]
    assert events[-1].get("error") and "expired" in events[-1]["error"]
