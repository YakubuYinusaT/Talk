"""The Try it page: a conversation typed in the browser, with the steps Talk took beside each reply, and the guards that keep it cheap and safe.

The conversations below are written the way a caller really speaks over several turns: a polite request, an answer to each question Talk asks, and a polite closing."""

import asyncio
import json
import re
from types import SimpleNamespace

from sqlalchemy import select

from sofa.models import Call, Notification
from sofa.routes import tryit
from sofa.services.notify import send_sms
from sofa.web import ui

SAY = "Hello, do you have amoxicillin in stock, please?"
RESERVED = "+2349990"

# The conversation that finds a clinic for antenatal care in Surulere and books the private one for tomorrow morning.
BOOK_THE_PRIVATE_CLINIC = ["Please help me find the nearest clinic for antenatal care.", "I am in Surulere.", "Yes, please book the private clinic.", "Tomorrow morning, please.",
                           "Yes, please go ahead."]
EMERGENCY = "Please, my brother is not breathing, we are in Ikeja."
ASK_ABOUT_PARKING = "Please ask the cancer centre about parking."
KNOWN_STEPS = ["heard", "urgency", "understood", "meant", "read", "travel", "held", "asked", "booked", "request", "replied", "decided", "guard", "payment",
               "ordered"]


def start(client, **headers):
    return client.post("/try/start", json={}, headers=headers)


def turn(client, session, text, **headers):
    return client.post("/try/turn", json={"session": session, "text": text}, headers=headers)


def converse(client, lines, **headers):
    """Opens a typed conversation, says each line in turn, and returns the session and what came back for each line."""
    session = start(client, **headers).json()["session"]
    answers = []
    for line in lines:
        got = turn(client, session, line, **headers)
        assert got.status_code == 200, (line, got.text)
        answers.append(got.json())
    return session, answers


def kinds_of(answer) -> list[str]:
    return [step["step"] for step in answer["trace"]]


def lines_of(script) -> list[str]:
    """The sentences of one example, whether an example is kept as a title with its lines or as a plain list of lines."""
    return script["lines"] if isinstance(script, dict) else list(script)


def desk_of(client, provider_name: str) -> str:
    """The page of the front desk of a provider, found from the name the trace gives it."""
    address = ui.desk_of(provider_name)
    assert address, provider_name
    return client.get(address).text


def run_in_order(kinds: list[str], wanted: list[str]) -> bool:
    """Whether the steps in `wanted` all occur in `kinds`, in that order (other steps may lie between them)."""
    position = 0
    for kind in kinds:
        if position < len(wanted) and kind == wanted[position]:
            position += 1
    return position == len(wanted)


# ---- the page and its examples ----------------------------------------------------------------------------------------------------------------


def test_the_page_has_the_conversation_the_examples_and_the_trace(client):
    page = client.get("/try").text
    assert page.count("<h1") == 1 and ">Try it</h1>" in page
    for ident in ("try-app", "log", "say-form", "say", "send", "restart", "script-panel", "script-next", "scripts-data", "inside"):
        assert f'id="{ident}"' in page, ident
    assert page.count('data-script="') == len(tryit.SCRIPTS)
    assert "Examples" in page and "Trace" in page and "/static/try.js" in page


def test_the_page_holds_cues_only_and_no_paragraphs_of_explanation(client):
    main = client.get("/try").text.split("<main")[1]
    text = re.sub(r"<(script|style|svg|noscript)\b.*?</\1>", " ", main, flags=re.S)
    words = len(re.sub(r"<[^>]+>", " ", text).split())
    assert words <= 70, words
    for old in ('class="flash"', 'class="eyebrow"', 'class="lede"'):
        assert old not in main


def test_examples_exist_and_each_is_a_list_of_natural_sentences():
    assert len(tryit.SCRIPTS) >= 3
    several = 0
    for script in tryit.SCRIPTS:
        lines = lines_of(script)
        assert lines, script
        several += 1 if len(lines) >= 2 else 0
        for line in lines:
            assert isinstance(line, str) and line[0].isupper() and line.endswith((".", "?", "!")), line      # a whole sentence, not a clipped command
            assert len(line) <= tryit.MAX_CHARS, line
            assert len(line.split()) <= 25, line            # one thing at a time, the way a person speaks on the telephone
    assert several >= len(tryit.SCRIPTS) - 1               # all but at most one short example (such as an emergency) take several turns


def test_the_examples_include_a_booking_a_stock_question_and_an_emergency():
    everything = " ".join(" ".join(lines_of(script)) for script in tryit.SCRIPTS).lower()
    for need in ("book", "stock", "breathing"):
        assert need in everything, need


def test_the_examples_travel_to_the_page_as_data_in_the_same_order(client):
    page = client.get("/try").text
    found = re.search(r'<script type="application/json" id="scripts-data">(.*?)</script>', page, re.S).group(1)
    sent = json.loads(found.replace("&#34;", '"').replace("&#39;", "'").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))
    assert [lines_of(s) for s in sent] == [lines_of(s) for s in tryit.SCRIPTS]


def test_every_example_can_be_stepped_through_from_the_start_and_each_line_gets_a_reply_and_a_trace(client):
    for script in tryit.SCRIPTS:
        session = start(client).json()["session"]
        for line in lines_of(script):
            got = turn(client, session, line)
            assert got.status_code == 200, (script, line, got.text)
            body = got.json()
            assert body["reply"].strip() and 'class="trace"' in body["steps_html"], (script, line)
            kinds = kinds_of(body)
            assert kinds[0] == "heard" and kinds[-1] == "replied", (script, line, kinds)
            if body["ended"]:
                break


# ---- one typed turn ---------------------------------------------------------------------------------------------------------------------------


def test_a_typed_turn_returns_the_reply_and_the_steps(client):
    session = start(client).json()
    assert session["greeting"] and session["max_turns"]
    got = turn(client, session["session"], SAY)
    assert got.status_code == 200
    body = got.json()
    assert body["reply"] and body["turns_left"] == session["max_turns"] - 1
    assert 'class="trace"' in body["steps_html"] and "Understood" in body["steps_html"]
    assert "Heard" in body["steps_html"] and "Typed in the box" in body["steps_html"]


def test_the_start_gives_a_fresh_unguessable_session_each_time_and_a_polite_greeting(client):
    first, second = start(client).json(), start(client).json()
    assert first["session"] != second["session"] and len(first["session"]) >= 16
    assert first["greeting"].strip() and first["greeting"][0].isupper() and first["greeting"].rstrip().endswith((".", "?"))


def test_the_trace_of_a_turn_runs_from_what_was_heard_to_what_was_replied_with_the_time_of_each_step(client):
    _, answers = converse(client, ["Hello, do you have amoxicillin in stock, please?", "Amoxicillin five hundred milligram capsules."])
    for body in answers:
        kinds = kinds_of(body)
        assert kinds[0] == "heard" and kinds[-1] == "replied" and "understood" in kinds
        times = [step["at_ms"] for step in body["trace"]]
        assert times == sorted(times)      # the steps are in the order they happened
    assert answers[0]["trace"][0]["text"] == "Hello, do you have amoxicillin in stock, please?" and answers[0]["trace"][0]["model"] == "typed"


def test_a_conversation_shows_each_step_as_it_occurs_from_the_search_to_the_booking(client):
    _, answers = converse(client, BOOK_THE_PRIVATE_CLINIC)
    first, second, _third, fourth, last = answers
    assert kinds_of(first) == ["heard", "understood", "read", "replied"]                         # no provider is asked until Talk knows the area
    assert "need" in first["trace"][2] and first["trace"][2]["need"] == "antenatal care"
    assert kinds_of(second)[:3] == ["heard", "understood", "read"] and kinds_of(second).count("asked") >= 2 and kinds_of(second)[-1] == "replied"
    assert second["trace"][2]["area"] == "Surulere"
    assert all(step["op"] == "search" for step in second["trace"] if step["step"] == "asked")
    assert [s["op"] for s in fourth["trace"] if s["step"] == "asked"] == ["slots"]
    assert run_in_order(kinds_of(last), ["heard", "understood", "asked", "booked", "replied"])
    assert [s["op"] for s in last["trace"] if s["step"] == "asked"] == ["book"]
    assert all(kind in KNOWN_STEPS for answer in answers for kind in kinds_of(answer))


def test_the_steps_come_back_as_html_that_names_each_one_and_links_the_booking_to_the_providers_own_book(client):
    _, answers = converse(client, BOOK_THE_PRIVATE_CLINIC)
    html = answers[-1]["steps_html"]
    for title in ("Heard", "Understood", "Asked", "Booked", "Replied"):
        assert f'<span class="trace-name">{title}</span>' in html, title
    booked = next(step for step in answers[-1]["trace"] if step["step"] == "booked")
    assert booked["provider"] == "Eko Care Private Clinics" and booked["place"] == "Surulere Care Clinic" and re.fullmatch(r"APT-[A-Z0-9]{4}", booked["code"])
    assert f"Booking {booked['code']}" in html and 'href="/synthetic/eko-care/"' in html and "Appointment book" in html


def test_a_medicine_question_asks_the_pharmacy_chain_and_reads_the_medicine(client):
    _, answers = converse(client, ["Hello, do you have amoxicillin in stock, please?", "Amoxicillin five hundred milligram capsules."])
    asked = [step for answer in answers for step in answer["trace"] if step["step"] == "asked"]
    assert any(step["op"] == "stock" and step["provider"] == "Everwell Pharmacies" for step in asked), asked
    assert any(step.get("drug") for answer in answers for step in answer["trace"] if step["step"] == "read")


# ---- what a visitor does here shows up at the provider's own front desk ----------------------------------------------------------------------


def test_a_booking_made_here_appears_in_the_chosen_providers_own_appointment_book(client, happ):
    _, answers = converse(client, BOOK_THE_PRIVATE_CLINIC)
    booked = next(step for step in answers[-1]["trace"] if step["step"] == "booked")
    desk = desk_of(client, booked["provider"])
    assert f'id="visit-{booked["code"]}"' in desk and "Surulere Care Clinic" in desk and "Tomorrow" in desk
    rows = happ.state.providers["eko-care"].state.store.db.execute("SELECT * FROM appointments WHERE status = 'booked'").fetchall()
    assert [r["code"] for r in rows] == [booked["code"]]
    assert booked["code"] not in client.get("/synthetic/state-phc/").text        # and it is in nobody else's book


def test_a_booking_made_here_is_cancelled_in_the_providers_book_when_the_visitor_asks(client, happ):
    converse(client, BOOK_THE_PRIVATE_CLINIC + ["Please can you cancel my appointment for tomorrow?", "Yes, please."])
    assert happ.state.providers["eko-care"].state.store.db.execute("SELECT * FROM appointments WHERE status = 'booked'").fetchall() == []


def test_an_emergency_typed_here_gives_112_first_and_files_an_urgent_request_on_the_nearest_desk_without_any_phone_number(client, happ, hdb):
    _, answers = converse(client, [EMERGENCY])
    body = answers[0]
    assert "call 112 now" in body["reply"].split(". ")[0]
    assert any(step["step"] == "urgency" and step["level"] == "emergency" for step in body["trace"])
    filed = next(step for step in body["trace"] if step["step"] == "request")
    assert filed["kind"] == "emergency" and filed["urgent"] is True and re.fullmatch(r"REQ-[A-Z0-9]{4}", filed["code"])
    assert "Request filed" in body["steps_html"] and "marked urgent" in body["steps_html"]
    desk = desk_of(client, filed["provider"])
    assert f'id="request-{filed["code"]}"' in desk and "Urgent" in desk and "not breathing" in desk and "1 waiting, 1 urgent" in desk
    typed = hdb.scalars(select(Call)).first().from_number
    assert typed.startswith(RESERVED) and typed not in desk and typed.lstrip("+") not in desk and RESERVED.lstrip("+") not in desk      # the desk sees a short reference, never the number


def test_a_question_for_the_staff_typed_here_appears_in_the_requests_of_that_provider_without_a_phone_number(client, happ, hdb):
    _, answers = converse(client, [ASK_ABOUT_PARKING])
    filed = next(step for step in answers[0]["trace"] if step["step"] == "request")
    assert filed["kind"] == "question" and filed["urgent"] is False and filed["provider"].startswith("Oncology Care Centre Ikeja")
    desk = desk_of(client, filed["provider"])
    assert f'id="request-{filed["code"]}"' in desk and "parking" in desk and "1 waiting" in desk and "Urgent</span>" not in desk
    typed = hdb.scalars(select(Call)).first().from_number
    assert typed not in desk and typed.lstrip("+") not in desk


def test_a_request_is_filed_with_one_provider_and_not_copied_to_the_others(client):
    _, answers = converse(client, [ASK_ABOUT_PARKING])
    filed = next(step for step in answers[0]["trace"] if step["step"] == "request")
    others = [slug for slug in ("state-phc", "eko-care", "everwell") if filed["code"] in client.get(f"/synthetic/{slug}/").text]
    assert others == []


# ---- the guards -------------------------------------------------------------------------------------------------------------------------------


def test_it_takes_json_only_and_only_a_json_object(client):
    assert client.post("/try/start", content="not json", headers={"content-type": "text/plain"}).status_code == 415
    assert client.post("/try/start", data={"session": "x"}).status_code == 415
    assert client.post("/try/start", content="{broken", headers={"content-type": "application/json"}).status_code == 400
    assert client.post("/try/start", json=["a", "list"]).status_code == 400
    assert client.post("/try/turn", content="text", headers={"content-type": "text/plain"}).status_code == 415
    assert client.post("/try/turn", json="a string").status_code == 400
    session = start(client).json()["session"]
    for body in ({"session": session}, {"text": SAY}, {"session": session, "text": 7}, {"session": 7, "text": SAY}):
        assert client.post("/try/turn", json=body).status_code == 400, body


def test_a_message_may_have_at_most_three_hundred_characters(client):
    assert tryit.MAX_CHARS == 300
    session = start(client).json()["session"]
    too_long = turn(client, session, "x" * 301)
    assert too_long.status_code == 400 and "300 characters" in too_long.json()["error"]
    assert turn(client, session, "Hello, please. " + "a" * 285).status_code == 200            # exactly three hundred is accepted


def test_a_message_of_nothing_or_of_control_characters_is_refused_politely(client):
    session = start(client).json()["session"]
    for text in ("", "   ", "\x00\x07\x1b"):
        refused = turn(client, session, text)
        assert refused.status_code == 400 and refused.json()["error"] == "Please type a message."


def test_the_refusals_are_short_and_say_when_to_start_over(client, happ):
    assert turn(client, "no-such-session", SAY).status_code == 404
    assert "start over" in turn(client, "no-such-session", SAY).json()["error"].lower()
    session = start(client).json()["session"]
    happ.state.svc.settings.try_max_turns = 1
    assert turn(client, session, SAY).status_code == 200
    over = turn(client, session, SAY)
    assert over.status_code == 429 and "start over" in over.json()["error"].lower()      # try.js stops the conversation on exactly these words


def test_a_conversation_is_limited_to_the_number_of_messages_the_settings_allow(client, happ):
    happ.state.svc.settings.try_max_turns = 3
    session = start(client).json()
    assert session["max_turns"] == 3
    lefts = [turn(client, session["session"], SAY).json()["turns_left"] for _ in range(3)]
    assert lefts == [2, 1, 0]
    assert turn(client, session["session"], SAY).status_code == 429
    assert turn(client, start(client).json()["session"], SAY).status_code == 200            # a new conversation has its own count


def test_one_network_address_may_send_only_so_many_messages_in_an_hour_and_others_are_not_held_back(client, happ):
    happ.state.svc.settings.try_turns_per_hour = 3
    session = start(client, **{"x-forwarded-for": "203.0.113.5"}).json()["session"]
    for _ in range(3):
        assert turn(client, session, SAY, **{"x-forwarded-for": "203.0.113.5"}).status_code == 200
    limited = turn(client, session, SAY, **{"x-forwarded-for": "203.0.113.5"})
    assert limited.status_code == 429 and "this hour" in limited.json()["error"]
    elsewhere = start(client, **{"x-forwarded-for": "198.51.100.7"}).json()["session"]
    assert turn(client, elsewhere, SAY, **{"x-forwarded-for": "198.51.100.7"}).status_code == 200


def test_a_visitor_cannot_escape_the_hourly_limit_by_writing_a_false_address_in_front_of_the_real_one(client, happ):
    happ.state.svc.settings.try_turns_per_hour = 2
    session = start(client, **{"x-forwarded-for": "203.0.113.5"}).json()["session"]
    for n in range(2):
        assert turn(client, session, SAY, **{"x-forwarded-for": f"10.0.0.{n}, 203.0.113.5"}).status_code == 200
    assert turn(client, session, SAY, **{"x-forwarded-for": "10.0.0.99, 203.0.113.5"}).status_code == 429


def test_one_address_may_start_only_so_many_conversations_in_an_hour(client, happ):
    happ.state.svc.settings.try_turns_per_hour = 3        # the number of conversations is a quarter of the messages, and never fewer than five
    for _ in range(5):
        assert start(client, **{"x-forwarded-for": "203.0.113.9"}).status_code == 200
    sixth = start(client, **{"x-forwarded-for": "203.0.113.9"})
    assert sixth.status_code == 429 and "Too many conversations" in sixth.json()["error"]
    assert start(client, **{"x-forwarded-for": "198.51.100.1"}).status_code == 200


def test_the_limit_for_everyone_together_is_ten_times_the_limit_for_one_address(client, happ):
    happ.state.svc.settings.try_turns_per_hour = 1
    for n in range(10):
        address = {"x-forwarded-for": f"192.0.2.{n + 1}"}
        assert turn(client, start(client, **address).json()["session"], SAY, **address).status_code == 200
    address = {"x-forwarded-for": "192.0.2.200"}
    refused = turn(client, start(client, **address).json()["session"], SAY, **address)
    assert refused.status_code == 429 and "this hour" in refused.json()["error"]


def test_the_hourly_count_starts_again_after_an_hour(client, happ, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(tryit, "now", lambda: clock[0])
    happ.state.svc.settings.try_turns_per_hour = 1
    session = start(client).json()["session"]
    assert turn(client, session, SAY).status_code == 200
    assert turn(client, session, SAY).status_code == 429
    clock[0] += tryit.HOUR + 1
    fresh = start(client).json()["session"]
    assert turn(client, fresh, SAY).status_code == 200


def test_a_conversation_expires_after_the_minutes_the_settings_allow(client, happ, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(tryit, "now", lambda: clock[0])
    happ.state.svc.settings.try_session_minutes = 10
    session = start(client).json()["session"]
    clock[0] += 9 * 60
    assert turn(client, session, SAY).status_code == 200            # still alive just before the end
    clock[0] += 2 * 60
    gone = turn(client, session, SAY)
    assert gone.status_code == 404 and "expired" in gone.json()["error"] and "start over" in gone.json()["error"].lower()


def test_only_so_many_conversations_may_be_alive_at_once(client, monkeypatch):
    monkeypatch.setattr(tryit, "MAX_SESSIONS", 2)
    assert start(client).status_code == 200 and start(client).status_code == 200
    busy = start(client)
    assert busy.status_code == 503 and "busy" in busy.json()["error"]


def test_a_second_message_is_refused_while_talk_is_still_replying_to_the_first(client, happ):
    session = start(client).json()["session"]
    happ.state.try_state["sessions"][session]["busy"] = True
    refused = turn(client, session, SAY)
    assert refused.status_code == 409 and "still replying" in refused.json()["error"]


def test_a_call_that_has_ended_takes_no_more_messages(client, happ):
    session = start(client).json()["session"]
    happ.state.try_state["sessions"][session]["ended"] = True
    refused = turn(client, session, SAY)
    assert refused.status_code == 409 and "start over" in refused.json()["error"].lower()


def test_when_the_page_is_switched_off_it_and_both_endpoints_are_not_found(client, happ):
    happ.state.svc.settings.try_page_enabled = False
    assert client.get("/try").status_code == 404
    assert client.post("/try/start", json={}).status_code == 404
    assert client.post("/try/turn", json={"session": "x", "text": SAY}).status_code == 404


def test_no_long_number_leaves_in_a_reply_or_in_the_steps(client):
    session = start(client).json()["session"]
    body = turn(client, session, "My number is 08055550101, please.").json()
    assert "08055550101" not in body["reply"] and "08055550101" not in body["steps_html"] and "08055550101" not in str(body["trace"])


def test_nothing_that_is_sent_back_holds_a_phone_number_or_a_secret(client, happ):
    secret = happ.state.svc.settings.at_callback_secret
    session = start(client)
    everything = session.text
    for line in BOOK_THE_PRIVATE_CLINIC:
        everything += turn(client, session.json()["session"], line).text
    assert RESERVED not in everything and RESERVED.lstrip("+") not in everything and "+234" not in everything and secret not in everything
    assert re.search(r"\d{6,}", everything) is None


# ---- the reserved test numbers ----------------------------------------------------------------------------------------------------------------


def test_a_typed_conversation_is_a_test_call_from_a_reserved_number(client, hdb):
    start(client)
    call = hdb.scalars(select(Call)).first()
    assert call.is_test is True and re.fullmatch(r"\+2349990\d{6}", call.from_number)


def test_the_text_message_of_a_booking_made_here_is_recorded_as_sent_and_never_given_to_the_text_message_service(client, happ, hdb, monkeypatch):
    async def never(*_args, **_kwargs):
        raise AssertionError("the text-message service must not be called for a reserved number")

    monkeypatch.setattr(happ.state.svc.sms, "send", never)
    converse(client, BOOK_THE_PRIVATE_CLINIC)
    notes = list(hdb.scalars(select(Notification)))
    assert notes and all(n.to_number.startswith(RESERVED) and n.status == "mock_sent" and n.provider_message_id is None for n in notes)
    assert any("Surulere Care Clinic" in n.body for n in notes)


def test_a_reserved_number_never_receives_a_real_text_but_an_ordinary_number_does(hdb):
    sent = []

    async def send(to, body):
        sent.append(to)
        return "sent", "message-1"

    services = SimpleNamespace(sms=SimpleNamespace(send=send))
    reserved = asyncio.run(send_sms(hdb, services, to=f"{RESERVED}123", body="Your booking is confirmed.", template="health_notice"))
    ordinary = asyncio.run(send_sms(hdb, services, to="+2348055550001", body="Your booking is confirmed.", template="health_notice"))
    assert reserved.status == "mock_sent" and ordinary.status == "sent"
    assert sent == ["+2348055550001"]
