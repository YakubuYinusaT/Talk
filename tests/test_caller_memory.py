"""Sofa remembers a person from one call to the next: a caller by their number, a browser by a random identifier in a cookie. Only where they are and the clinic of
their last booking are kept, under a one-way key, never the number itself and never why they needed care."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from sofa.models import CallerMemory
from tests.support import CALLER, call
from tests.test_orchestrator import greeting_wordings

FIRST_CALL = ["I am in Surulere. When is the next available slot at a clinic?", "The first one, please.", "Yes, please."]


def test_a_caller_who_rings_again_is_welcomed_back_and_not_asked_where_they_are(client):
    first = call(client, FIRST_CALL)
    assert "Your appointment is confirmed at Surulere Care Clinic" in first[3]
    again = call(client, ["Which pharmacy has paracetamol?"])
    assert again[0] in greeting_wordings("greet_caller_known")
    assert "Everwell Pharmacy Surulere" in again[1] and "which area" not in again[1].lower()


def test_a_caller_who_asks_to_book_again_is_offered_the_clinic_of_their_last_visit(client):
    call(client, FIRST_CALL)
    again = call(client, ["I would like to book another appointment, please."])
    assert "Surulere Care Clinic" in again[1]


def test_another_number_is_a_stranger(client):
    call(client, FIRST_CALL)
    other = call(client, ["Which pharmacy has paracetamol?"], caller="+2348055550002")
    assert other[0] in greeting_wordings("greet_caller")
    assert "Everwell Pharmacy Surulere" not in other[1]


def test_the_memory_holds_no_phone_number_and_no_reason_for_care(client, hdb):
    call(client, ["I am in Surulere. I need antenatal care. When is the next available slot?", "The first one, please.", "Yes, please."])
    rows = hdb.scalars(select(CallerMemory)).all()
    assert rows
    for row in rows:
        assert CALLER.lstrip("+") not in row.key + row.data and "55550001" not in row.key + row.data
        assert "antenatal" not in row.data and "Surulere" in row.data


def test_a_memory_older_than_the_limit_is_forgotten(client, hdb):
    call(client, FIRST_CALL)
    for row in hdb.scalars(select(CallerMemory)):
        row.updated_at = datetime.now(timezone.utc) - timedelta(days=91)
    hdb.commit()
    again = call(client, ["Which pharmacy has paracetamol?"])
    assert again[0] in greeting_wordings("greet_caller")


def test_nothing_is_remembered_when_memory_is_off(client, happ, hdb):
    happ.state.svc.settings.caller_memory_days = 0
    call(client, FIRST_CALL)
    assert not hdb.scalars(select(CallerMemory)).all()
    assert call(client, ["Hello."])[0] in greeting_wordings("greet_caller")


def test_the_same_browser_is_remembered_and_another_browser_is_not(happ, client):
    started = client.post("/try/start", json={})
    assert "talk_demo" in started.cookies or client.cookies.get("talk_demo")
    reply = client.post("/try/turn", json={"session": started.json()["session"], "text": "I am in Surulere. Which pharmacy has paracetamol?"}).json()["reply"]
    assert "Everwell Pharmacy Surulere" in reply

    back = client.post("/try/start", json={}).json()
    assert back["greeting"] in greeting_wordings("greet_caller_known")
    reply = client.post("/try/turn", json={"session": back["session"], "text": "Which pharmacy has paracetamol?"}).json()["reply"]
    assert "Everwell Pharmacy Surulere" in reply

    with TestClient(happ) as stranger:
        assert stranger.post("/try/start", json={}).json()["greeting"] in greeting_wordings("greet_caller")
