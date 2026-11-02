"""The Live calls page: off unless switched on, and when on it shows recent calls without exposing phone numbers or long strings of digits."""

import re

from sqlalchemy import select

from sofa.models import Call, CallTurn
from sofa.web.ui import mask_phone, scrub
from tests.support import CALLER, call

SAID = "Hello, do you have amoxicillin in stock, please?"


def badges_of(page: str) -> list[str]:
    return re.findall(r'<span class="badge[^"]*">(?:<svg.*?</svg>)?([^<]+)</span>', page, re.S)


def test_the_page_does_not_exist_unless_it_is_switched_on(client):
    assert client.get("/demo").status_code == 404


def test_masking_and_scrubbing():
    assert mask_phone("+2348055550101") == "**********0101"
    assert scrub("my reference is 2012345678 and my other number 123456") == "my reference is [hidden] and my other number [hidden]"
    assert scrub("I have had a fever for 3 days") == "I have had a fever for 3 days"


def test_an_empty_page_says_so_in_one_line_and_points_to_try_it(client, happ):
    happ.state.svc.settings.demo_page_enabled = True
    page = client.get("/demo").text
    assert "No calls yet." in page and 'href="/try"' in page
    assert page.count("<h1") == 1 and "Updated at" in page


def test_the_page_shows_the_figures_and_a_call_with_the_number_masked(client, happ):
    happ.state.svc.settings.demo_page_enabled = True
    call(client, [SAID, "Amoxicillin five hundred milligram capsules, please."])
    page = client.get("/demo").text
    for label in ("Calls, last 24 hours", "Visits booked", "Staff requests", "Texts sent"):
        assert label in page
    assert CALLER not in page and CALLER[-4:] in page
    assert "Turn 1" in page and "Turn 2" in page and "Asked" in page      # the steps of each turn are there, whatever the setting for words


def test_what_was_said_is_hidden_unless_the_page_is_told_to_show_it(client, happ):
    settings = happ.state.svc.settings
    settings.demo_page_enabled = True
    call(client, [SAID, "Amoxicillin five hundred milligram capsules, please."])
    hidden = client.get("/demo").text
    assert 'data-words="hidden"' in hidden and "Words hidden" in hidden
    assert "do you have amoxicillin in stock" not in hidden and 'class="words"' not in hidden
    settings.demo_show_calls = True
    shown = client.get("/demo").text
    assert 'data-words="shown"' in shown and "Words shown" in shown
    assert "do you have amoxicillin in stock" in shown and CALLER not in shown


def test_a_conversation_typed_on_try_it_carries_its_own_badge(client, happ):
    happ.state.svc.settings.demo_page_enabled = True
    session = client.post("/try/start", json={}).json()["session"]
    assert client.post("/try/turn", json={"session": session, "text": SAID}).status_code == 200
    assert "Try it" in badges_of(client.get("/demo").text)


def test_a_long_number_in_a_reply_never_reaches_the_page(client, happ, hdb):
    settings = happ.state.svc.settings
    settings.demo_page_enabled = settings.demo_show_calls = True
    row = Call(provider_session_id="s", from_number="+2348055550101", to_number="+2347000000000")
    hdb.add(row)
    hdb.flush()
    hdb.add(CallTurn(call_id=row.id, seq=1, asr_model="meta", transcript="my number is 08055550101", reply_text="Thank you. I will text 08055550101 shortly."))
    hdb.commit()
    page = client.get("/demo").text
    assert "08055550101" not in page and "[hidden]" in page
    assert hdb.scalars(select(CallTurn)).first().transcript == "my number is 08055550101"      # the record itself is untouched


def test_the_page_is_read_only_and_asks_nothing_of_the_visitor(client, happ):
    happ.state.svc.settings.demo_page_enabled = True
    assert client.post("/demo").status_code == 405
    page = client.get("/demo").text
    assert "<form" not in page.split("<main")[1]


def test_each_turn_shows_the_steps_talk_took_in_the_order_they_happened(client, happ):
    happ.state.svc.settings.demo_page_enabled = True
    call(client, [SAID, "Amoxicillin five hundred milligram capsules, please."])
    page = client.get("/demo").text
    names = re.findall(r'<span class="trace-name">([^<]+)</span>', page)
    assert names, "the steps of the turns are listed"
    first_turn = names[: names.index("Replied") + 1]
    assert first_turn[0] == "Heard" and "Understood" in first_turn and first_turn[-1] == "Replied"
    assert first_turn.index("Understood") < first_turn.index("Asked") < first_turn.index("Replied")


def test_a_booking_made_on_a_call_is_counted_and_its_steps_name_the_provider_that_confirmed_it(client, happ):
    happ.state.svc.settings.demo_page_enabled = True
    call(client, ["Please help me find the nearest clinic for antenatal care.", "I am in Surulere.", "Yes, please book the private clinic.", "Tomorrow morning, please.",
                  "Yes, please go ahead."])
    page = client.get("/demo").text
    figures = dict(re.findall(r'(Calls, last 24 hours|Visits booked|Staff requests|Texts sent)\s*</?[^>]*>\s*(?:<[^>]+>\s*)*(\d+)', page))
    assert figures.get("Visits booked") == "1" and figures.get("Calls, last 24 hours") == "1"
    assert "Booked" in re.findall(r'<span class="trace-name">([^<]+)</span>', page)
    assert "Eko Care Private Clinics" in page and 'href="/synthetic/eko-care/"' in page      # the step links to the provider's own appointment book


def test_the_place_and_time_of_a_booking_stay_hidden_while_the_words_are_hidden(client, happ):
    settings = happ.state.svc.settings
    settings.demo_page_enabled = True
    call(client, ["Please help me find the nearest clinic for antenatal care.", "I am in Surulere.", "Yes, please book the private clinic.", "Tomorrow morning, please.",
                  "Yes, please go ahead."])
    hidden = client.get("/demo").text
    assert "Surulere Care Clinic" not in hidden and "antenatal" not in hidden and "Booking APT-" in hidden
    settings.demo_show_calls = True
    assert "Surulere Care Clinic" in client.get("/demo").text


def test_a_typed_number_on_try_it_is_masked_like_any_other(client, happ, hdb):
    happ.state.svc.settings.demo_page_enabled = True
    session = client.post("/try/start", json={}).json()["session"]
    client.post("/try/turn", json={"session": session, "text": SAID})
    typed = hdb.scalars(select(Call).order_by(Call.created_at.desc())).first().from_number
    assert typed.startswith("+2349990")
    page = client.get("/demo").text
    assert typed not in page and typed[-4:] in page
