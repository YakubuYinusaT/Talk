"""The hospital onboarding wizard: a visitor makes a simulated hospital, connects it to Talk, goes live, books the first appointment as a patient, confirms it as the front-desk
assistant, and Talk texts the patient. These tests walk the whole journey through the same pages and endpoints a browser uses, and check the rules around it: that a hospital is
seen only by the visitor who made it, that the limits hold, that a hospital expires and is removed, and that a secret appears only in its masked control."""

import re
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from sofa.config import Settings
from sofa.health import followups
from sofa.main import create_app
from sofa.models import DemoHospital, HealthAppointment, Notification
from sofa.onboarding import hospital_profile
from tests.support import FIXED, TALK_NUMBER, SECRET

STEP_FORM = {"name": "Olive Branch Community General Hospital", "address": "Olive Branch Road", "area": "Surulere", "owner": "state", "kind": "general hospital", "fee": "1500",
             "wait": "55", "hours": "always", "services": ["general consultation", "antenatal care", "malaria test"]}


@pytest.fixture
def onb(happ):
    """The wizard's own bookkeeping, with the hospitals' clock on the same Tuesday morning as the rest of the tests."""
    onboarding = happ.state.svc.onboarding
    onboarding.clock = lambda: FIXED
    return onboarding


@pytest.fixture
def web(happ, onb):
    """A visitor's browser: it keeps the cookie that the wizard gives it."""
    with TestClient(happ) as visitor:
        yield visitor


def other_visitor(happ) -> TestClient:
    return TestClient(happ)


def start(web, template="general", **extra):
    return web.post("/onboard/start", data={"template": template, **extra}, follow_redirects=False)


def secret_of(happ, slug) -> str:
    with happ.state.svc.session_factory() as db:
        return db.scalar(select(DemoHospital.secret).where(DemoHospital.slug == slug))


def hospital(happ) -> DemoHospital:
    with happ.state.svc.session_factory() as db:
        return db.scalars(select(DemoHospital).where(DemoHospital.state != "retired").order_by(DemoHospital.created_at.desc())).first()


def walk_to_connection(web, happ):
    """Steps 1 to 5: start, profile, checklist and assistant, information, and the connection with its test. Returns the hospital's row."""
    assert start(web).status_code == 303
    assert web.post("/onboard/step/2", data=STEP_FORM, follow_redirects=False).status_code == 303
    assert web.post("/onboard/step/3", data={"check_computer": "on", "check_internet": "on", "check_power": "on", "assistant_name": "Ngozi Adeyemi", "role": "Front desk assistant"},
                    follow_redirects=False).status_code == 303
    information = {**{f"open_{d}": "0" for d in range(7)}, **{f"close_{d}": "24" for d in range(7)}, "capacity": "2", "samples": "on", "title_0": "How appointments work",
                   "answer_0": "Appointments are given in half-hour slots. Please arrive on time.", "keywords_0": "appointment slot", "warning": "Please call 112 now if someone has collapsed or cannot breathe."}
    assert web.post("/onboard/step/4", data=information, follow_redirects=False).status_code == 303
    assert web.post("/onboard/step/5", data={"action": "connect"}, follow_redirects=False).status_code == 303
    assert web.post("/onboard/step/5", data={"action": "test"}, follow_redirects=False).status_code == 303
    return hospital(happ)


def go_live(web, happ):
    row = walk_to_connection(web, happ)
    assert web.post("/onboard/step/5", data={"action": "continue"}, follow_redirects=False).status_code == 303
    assert web.post("/onboard/step/6", data={}, follow_redirects=False).status_code == 303
    return hospital(happ)


def chat(web, lines):
    """The patient's conversation through the Try it endpoints, as the page's script does it. Returns what Talk said to each line."""
    session = web.post("/try/start", json={}).json()["session"]
    return [web.post("/try/turn", json={"session": session, "text": line}).json()["reply"] for line in lines]


# ---- the pages ---------------------------------------------------------------------------------------------------


def test_the_welcome_page_offers_three_templates_and_says_that_it_is_simulated(web):
    page = web.get("/onboard")
    assert page.status_code == 200
    for name in ("Community general hospital", "Maternity centre", "Children's clinic"):
        assert name in page.text or name.replace("'", "&#39;") in page.text
    assert "Simulated demonstration" in page.text and 'aria-current="step"' in page.text


def test_every_step_page_needs_a_hospital_and_is_opened_in_order(web):
    for n in range(2, 9):
        assert web.get(f"/onboard/step/{n}", follow_redirects=False).headers["location"] == "/onboard"
    start(web)
    assert web.get("/onboard/step/2").status_code == 200
    assert web.get("/onboard/step/4", follow_redirects=False).headers["location"] == "/onboard/step/2"      # step 4 is not open until steps 2 and 3 are done
    assert web.get("/onboard/step/9", follow_redirects=False).status_code == 404


def test_the_menu_has_the_wizard_and_every_page_says_it_is_simulated(web):
    page = web.get("/overview").text
    assert "Onboard a hospital" in page and 'href="/onboard"' in page
    start(web)
    web.post("/onboard/step/2", data=STEP_FORM)
    for n in (2, 3):
        text = web.get(f"/onboard/step/{n}").text
        assert "Simulated demonstration" in text and 'aria-current="step"' in text and "<h1" in text


def test_the_profile_is_checked_before_it_is_kept(web, happ):
    start(web)
    bad = {**STEP_FORM, "name": "Call me on 08031234567", "fee": "lots", "wait": "999", "services": [], "area": "Atlantis"}
    page = web.post("/onboard/step/2", data=bad)
    assert page.status_code == 400
    for fragment in ("phone number", "whole number", "from 0 to 240", "at least one service", "from the list"):
        assert fragment in page.text
    assert hospital(happ).profile["name"] == "Olive Branch Community General Hospital"          # nothing was changed
    good = web.post("/onboard/step/2", data={**STEP_FORM, "name": "Kingfisher Family Hospital"}, follow_redirects=False)
    assert good.status_code == 303 and hospital(happ).profile["name"] == "Kingfisher Family Hospital"


def test_free_text_is_cleaned_escaped_and_limited(web, happ):
    start(web)
    page = web.post("/onboard/step/2", data={**STEP_FORM, "name": "<script>alert(1)</script> Clinic"})
    assert page.status_code == 400 and "<script>alert(1)" not in page.text
    long_name = web.post("/onboard/step/2", data={**STEP_FORM, "name": "A" * 200})
    assert long_name.status_code == 400 and "70 characters" in long_name.text
    assert web.post("/onboard/step/2", data={**STEP_FORM, "name": "St Mary's Hospital (Surulere) & Sons"}, follow_redirects=False).status_code == 303
    page = web.get("/onboard/step/2").text
    assert "St Mary&#39;s Hospital (Surulere) &amp; Sons" in page


def test_the_checklist_needs_every_item_and_the_account_gets_a_hidden_key(web, happ):
    start(web)
    web.post("/onboard/step/2", data=STEP_FORM)
    missing = web.post("/onboard/step/3", data={"check_computer": "on", "assistant_name": "Ngozi", "role": "Front desk assistant"})
    assert missing.status_code == 400 and "tick all three items" in missing.text
    ok = web.post("/onboard/step/3", data={"check_computer": "on", "check_internet": "on", "check_power": "on", "assistant_name": "Ngozi", "role": "Nurse in charge"}, follow_redirects=True)
    assert ok.status_code == 200 and 'data-toast="Account created"' in ok.text
    key = hospital(happ).desk_key
    assert key and ok.text.count(key) == 1                                  # in the masked control, and nowhere else on the page
    assert re.search(r'<input type="password" id="desk-key" value="%s" readonly' % re.escape(key), ok.text)
    assert 'data-reveal="desk-key"' in ok.text


def test_the_information_step_previews_exactly_what_talk_may_say(web, happ):
    start(web)
    web.post("/onboard/step/2", data=STEP_FORM)
    web.post("/onboard/step/3", data={"check_computer": "on", "check_internet": "on", "check_power": "on", "assistant_name": "Ngozi", "role": "Front desk assistant"})
    page = web.get("/onboard/step/4").text
    assert 'id="preview"' in page and "Olive Branch Community General Hospital" in page
    assert "Appointments are given in half-hour slots" in page and 'class="say"' in page
    assert "Please come to our emergency department straight away" in page            # the warning signs, exactly as written
    changed = {**{f"open_{d}": "8" for d in range(7)}, **{f"close_{d}": "17" for d in range(7)}, "capacity": "1", "title_0": "Parking", "answer_0": "Parking is free behind the main gate.",
               "warning": "Please call 112 straight away if a person is bleeding badly."}
    fragment = web.post("/onboard/step/4/preview", data=changed)
    assert fragment.status_code == 200 and "Parking is free behind the main gate." in fragment.text
    assert "Please call 112 straight away if a person is bleeding badly." in fragment.text
    assert hospital(happ).profile["warning"].startswith("Please come to our emergency department")      # a preview keeps nothing


def test_the_information_is_checked(web, happ):
    start(web)
    web.post("/onboard/step/2", data=STEP_FORM)
    web.post("/onboard/step/3", data={"check_computer": "on", "check_internet": "on", "check_power": "on", "assistant_name": "Ngozi", "role": "Front desk assistant"})
    shut = {f"closed_{d}": "on" for d in range(7)}
    page = web.post("/onboard/step/4", data={**shut, "capacity": "2", "title_0": "Parking", "answer_0": "Parking is free behind the main gate.", "warning": "Please call 112 straight away."})
    assert page.status_code == 400 and "at least one day open" in page.text
    page = web.post("/onboard/step/4", data={"closed_5": "on", "closed_6": "on", **{f"open_{d}": "8" for d in range(5)}, **{f"close_{d}": "7" for d in range(5)}, "capacity": "2",
                                            "title_0": "Parking", "answer_0": "Parking is free behind the main gate.", "warning": "Please call 112 straight away."})
    assert page.status_code == 400 and "close after it opens" in page.text


# ---- the connection ------------------------------------------------------------------------------------------------


def test_the_connection_has_its_own_secret_shown_only_in_the_masked_control(web, happ, caplog):
    caplog.set_level("DEBUG")
    row = walk_to_connection(web, happ)
    secret = secret_of(happ, row.slug)
    assert len(secret) == 64 and secret != happ.state.svc.settings.provider_secret("state-phc")
    page = web.get("/onboard/step/5")
    assert page.status_code == 200 and page.text.count(secret) == 1
    assert re.search(r'<input type="password" id="signing-secret" value="%s" readonly' % secret, page.text)
    assert secret not in caplog.text and row.desk_key not in caplog.text
    for later in (2, 3, 4):
        assert secret not in web.get(f"/onboard/step/{later}").text


def test_the_test_makes_a_real_signed_call_and_a_wrong_secret_is_refused(web, happ):
    row = walk_to_connection(web, happ)
    connection = row.profile["connection"]
    assert connection["ok"] and [c["ok"] for c in connection["checks"]] == [True, True]
    assert "correctly signed question" in connection["checks"][0]["title"].lower() and "refused" in connection["checks"][1]["text"]
    page = web.get("/onboard/step/5").text
    assert "Connection works." in page and "Passed" in page
    # the hospital is a real provider: it answers only a request that carries its own signature
    from sofa.health.links import ProviderError, ToolSpec

    svc, spec = happ.state.svc, happ.state.svc.onboarding.spec_for(row)
    import asyncio
    from dataclasses import replace

    async def ask(candidate):
        with svc.session_factory() as db:
            return await svc.provider_links.call(db, candidate, ToolSpec(f"{spec.domain}.search", "search"), {"limit": 5}, {"phone": "+2349990000001"})

    assert asyncio.run(ask(spec)).data["facilities"][0]["name"] == "Olive Branch Community General Hospital"
    with pytest.raises(ProviderError, match="401"):
        asyncio.run(ask(replace(spec, signing_secret="not-the-secret")))


def test_continue_is_refused_until_the_connection_has_been_tested(web, happ):
    start(web)
    web.post("/onboard/step/2", data=STEP_FORM)
    web.post("/onboard/step/3", data={"check_computer": "on", "check_internet": "on", "check_power": "on", "assistant_name": "Ngozi", "role": "Front desk assistant"})
    information = {**{f"open_{d}": "0" for d in range(7)}, **{f"close_{d}": "24" for d in range(7)}, "capacity": "2", "title_0": "Parking", "answer_0": "Parking is free behind the main gate.",
                   "warning": "Please call 112 straight away."}
    web.post("/onboard/step/4", data=information)
    assert web.post("/onboard/step/5", data={"action": "continue"}).status_code == 400            # no connection yet
    web.post("/onboard/step/5", data={"action": "connect"})
    refused = web.post("/onboard/step/5", data={"action": "continue"})
    assert refused.status_code == 400 and "test the connection first" in refused.text
    assert web.get("/onboard/step/6", follow_redirects=False).headers["location"] == "/onboard/step/5"


# ---- going live, and the first appointment --------------------------------------------------------------------


def test_going_live_makes_talk_find_the_new_hospital_by_the_normal_path(web, happ):
    row = go_live(web, happ)
    page = web.get("/onboard/step/6").text
    assert 'id="glimpse"' in page and "What Talk reads" in page and "Olive Branch Community General Hospital" in page
    said = chat(web, ["Please help me find a clinic near me for antenatal care.", "I am in Surulere."])
    assert "Olive Branch Community General Hospital" in said[1]
    net = [seen for seen in happ.state.net.seen]
    assert not any(row.slug in body for _, body in net)                    # it was not asked through the stand-in internet of the four systems, but through its own signed link
    assert row.slug in happ.state.svc.onboarding.apps


def test_the_whole_journey_from_the_first_booking_to_the_confirmation_text(web, happ, onb):
    row = go_live(web, happ)
    session = web.post("/try/start", json={}).json()["session"]
    turns = [web.post("/try/turn", json={"session": session, "text": line}).json() for line in hospital_profile.suggested_conversation(row.profile)]
    assert "Olive Branch Community General Hospital" in turns[1]["reply"] and turns[-1]["action"] == "health_booked"
    assert re.search(r"APT-[A-Z0-9]{4}|booking code is", turns[-1]["reply"])
    assert any(step["step"] == "asked" and step["provider"] == row.profile["name"] for step in turns[1]["trace"])      # the model's trace shows the new hospital being read
    # the first appointment is on the new hospital's own front desk
    journey = web.get("/onboard/api/journey").json()
    assert journey["booked"] and not journey["confirmed"] and journey["appointments"][0]["status"] == "booked"
    code = journey["appointments"][0]["code"]
    desk = web.get(f"/synthetic/{row.slug}/?embed=1")
    assert desk.status_code == 200 and code in desk.text and f'action="desk/confirm"' in desk.text and "Ngozi Adeyemi" in desk.text and "Staff access" in desk.text
    # the visitor plays the front-desk assistant and confirms it
    assert web.post(f"/synthetic/{row.slug}/desk/confirm", data={"code": code}, follow_redirects=False).status_code == 303
    after = web.get("/onboard/api/journey").json()
    assert after["confirmed"] and after["appointments"][0]["status"] == "confirmed"
    assert code in after["confirmation"]["text"] and "has confirmed your appointment" in after["confirmation"]["text"]
    assert after["confirmation"]["status"] == "mock_sent" and not after["confirmation"]["real"] and "Simulated" in after["confirmation"]["words"]
    with happ.state.svc.session_factory() as db:
        note = db.scalar(select(Notification).where(Notification.template == "health_confirmed"))
        assert note.to_number.startswith("+2349990") and note.status == "mock_sent"
        assert db.scalar(select(HealthAppointment).where(HealthAppointment.code == code)).status == "confirmed"
    # pressing it again changes nothing, and the patient is not texted twice
    web.post(f"/synthetic/{row.slug}/desk/confirm", data={"code": code})
    web.get("/onboard/api/journey")
    with happ.state.svc.session_factory() as db:
        assert len(list(db.scalars(select(Notification).where(Notification.template == "health_confirmed")))) == 1
    summary = web.get("/onboard/step/8")
    assert summary.status_code == 200 and code in summary.text and 'id="replay-title"' in summary.text
    assert "Olive Branch Community General Hospital" in summary.text and 'action="/onboard/restart"' in summary.text


def test_a_confirmed_visit_still_holds_its_slot_and_can_be_cancelled(web, happ):
    row = go_live(web, happ)
    chat(web, hospital_profile.suggested_conversation(row.profile))
    store = happ.state.svc.onboarding.apps[row.slug].state.store
    visit = next(r for r in store.db.execute("SELECT * FROM appointments WHERE caller_ref NOT LIKE 'sample-%'"))
    assert store.confirm(visit["code"]) and not store.confirm(visit["code"])
    facility = store.facilities[0]
    free = {s.isoformat() for s in store.free_slots(facility, datetime.fromisoformat(visit["starts"]).date(), FIXED)}
    assert store.db.execute("SELECT COUNT(*) FROM appointments WHERE starts = ? AND status IN ('booked', 'confirmed')", (visit["starts"],)).fetchone()[0] >= 1
    assert visit["caller_ref"] and len(free) > 0
    assert store.cancel(visit["code"], visit["caller_ref"])


def test_the_confirm_operation_exists_on_every_provider(happ, client):
    """Every provider system speaks the new operation, over the same signed contract."""
    from sofa.health.provider import TOOLS, Provider, sign
    import json
    import time

    assert "confirm" in [t["name"] for t in TOOLS]
    for slug, app in happ.state.providers.items():
        provider = app.state.provider
        assert provider.call("confirm", {"code": "APT-NONE"}, {})["status"] == "error"
        facility = next(f for f in provider.store.facilities if f.booking) if any(f.booking for f in provider.store.facilities) else None
        if not facility:
            continue
        start_at = provider.store.next_slots(facility, FIXED, 1)[0]
        booked = provider.call("book", {"facility_id": facility.id, "start": start_at.isoformat()}, {"caller_id": "caller-aaaa"})["data"]["appointment"]
        assert provider.call("visit_status", {"code": booked["code"]}, {"caller_id": "caller-aaaa"})["data"]["status"] == "booked"
        assert provider.call("confirm", {"code": booked["code"]}, {})["data"]["confirmed"] is True
        assert provider.call("visit_status", {"code": booked["code"]}, {"caller_id": "caller-aaaa"})["data"]["status"] == "confirmed"
        assert provider.call("confirm", {"code": booked["code"]}, {})["status"] == "error"          # only a booked visit can be confirmed, and only once
    body = json.dumps({"op": "list_tools"}).encode()
    stamp = str(int(time.time()))
    answer = TestClient(happ.state.providers["state-phc"]).post("/rpc", content=body, headers={"x-sofa-timestamp": stamp, "x-sofa-signature": sign(happ.state.svc.settings.provider_secret("state-phc"), stamp, body)})
    assert "confirm" in [t["name"] for t in answer.json()["tools"]]


def test_every_desk_gets_a_confirm_button_for_staff(happ, client):
    from sofa.health import desk as desk_page

    state = happ.state.providers["state-phc"]
    store = state.state.store
    facility = store.facilities[0]
    booked = state.state.provider.call("book", {"facility_id": facility.id, "start": store.next_slots(facility, FIXED, 1)[0].isoformat()}, {"caller_id": "caller-bbbb"})["data"]["appointment"]
    page = desk_page.render(state.state.provider.network, store, "desk-key", "desk-key")
    assert 'action="desk/confirm"' in page and booked["code"] in page
    assert 'action="desk/confirm"' not in desk_page.render(state.state.provider.network, store, "desk-key", "")       # without the key the desk can only be read
    assert TestClient(state).post("/desk/confirm", data={"code": booked["code"], "key": "wrong"}).status_code == 403
    assert TestClient(state).post("/desk/confirm", data={"code": booked["code"], "key": "desk-key"}, follow_redirects=False).status_code == 403    # this app has no desk key set


# ---- who sees the hospital -----------------------------------------------------------------------------------------


def test_another_visitor_does_not_see_the_hospital_and_cannot_open_its_desk(web, happ):
    row = go_live(web, happ)
    stranger = other_visitor(happ)
    said = chat(stranger, ["Please help me find a clinic near me for antenatal care.", "I am in Surulere."])
    assert "Olive Branch" not in said[1]
    assert stranger.get(f"/synthetic/{row.slug}/").status_code == 404
    assert stranger.post(f"/synthetic/{row.slug}/desk/confirm", data={"code": "APT-AAAA"}).status_code == 403
    assert stranger.get("/onboard/step/6", follow_redirects=False).headers["location"] == "/onboard"
    assert stranger.get("/onboard/api/journey").status_code == 404
    forged = TestClient(happ)
    forged.cookies.set("talk_demo", "someone.0123456789abcdef0123456789abcdef")
    assert forged.get(f"/synthetic/{row.slug}/").status_code == 404 and forged.get("/onboard/step/6", follow_redirects=False).status_code == 303
    mine = chat(web, ["Please help me find a clinic near me for antenatal care.", "I am in Surulere."])
    assert "Olive Branch Community General Hospital" in mine[1]


def test_the_desk_key_opens_the_desk_from_another_browser(web, happ):
    row = go_live(web, happ)
    stranger = other_visitor(happ)
    page = stranger.get(f"/synthetic/{row.slug}/", params={"key": row.desk_key})
    assert page.status_code == 200 and "Staff access" in page.text and 'id="desk-key"' not in page.text      # the right key gives staff access, so the key box is gone
    assert stranger.get(f"/synthetic/{row.slug}/", params={"key": "wrong-key"}).status_code == 404


def test_a_phone_the_visitor_gave_with_consent_also_sees_the_hospital(web, happ):
    row = walk_to_connection(web, happ)
    web.post("/onboard/step/5", data={"action": "continue"})
    no_consent = web.post("/onboard/step/6", data={"phone": "0803 123 4567"})
    assert no_consent.status_code == 400 and "tick the box" in no_consent.text
    assert web.post("/onboard/step/6", data={"consent": "on"}).status_code == 400
    assert web.post("/onboard/step/6", data={"phone": "+2349990000123", "consent": "on"}).status_code == 400          # the numbers kept for typed conversations are refused
    assert web.post("/onboard/step/6", data={"phone": "0803 123 4567", "consent": "on"}, follow_redirects=False).status_code == 303
    from tests.support import call

    friend_calls = call(web, ["Please help me find a clinic near me for antenatal care.", "I am in Surulere."], caller="+2348031234567")
    assert "Olive Branch Community General Hospital" in " ".join(friend_calls)
    stranger_calls = call(web, ["Please help me find a clinic near me for antenatal care.", "I am in Surulere."], caller="+2348031239999")
    assert "Olive Branch Community General Hospital" not in " ".join(stranger_calls)
    assert hospital(happ).owner_phone == "+2348031234567"


def test_with_a_phone_and_consent_the_confirmation_text_really_goes_through_the_text_client(web, happ):
    row = walk_to_connection(web, happ)
    web.post("/onboard/step/5", data={"action": "continue"})
    web.post("/onboard/step/6", data={"phone": "0803 123 4567", "consent": "on"})
    sent = []
    sms = happ.state.svc.sms

    async def deliver(to, message):
        sent.append((to, message))
        return "sent", "id-1"

    sms.send = deliver
    chat(web, hospital_profile.suggested_conversation(hospital(happ).profile))
    code = web.get("/onboard/api/journey").json()["appointments"][0]["code"]
    web.post(f"/synthetic/{row.slug}/desk/confirm", data={"code": code})
    confirmation = web.get("/onboard/api/journey").json()["confirmation"]
    assert confirmation["real"] and confirmation["status"] == "sent" and "ending 4567" in confirmation["words"]
    assert "0803" not in confirmation["words"] and "+234803" not in str(confirmation)
    assert [to for to, text in sent if "has confirmed your appointment" in text] == ["+2348031234567"]


def test_without_a_phone_nothing_is_ever_sent_to_a_real_number(web, happ):
    row = go_live(web, happ)
    sent = []

    async def deliver(to, message):
        sent.append(to)
        return "sent", "id-1"

    happ.state.svc.sms.send = deliver
    chat(web, hospital_profile.suggested_conversation(row.profile))
    code = web.get("/onboard/api/journey").json()["appointments"][0]["code"]
    web.post(f"/synthetic/{row.slug}/desk/confirm", data={"code": code})
    web.get("/onboard/api/journey")
    assert sent == []


# ---- limits, lifetime and the switch ------------------------------------------------------------------------------


def test_one_address_may_only_start_so_many_hospitals_an_hour(happ):
    happ.state.svc.settings.demo_onboarding_per_address_per_hour = 2
    for n in range(2):
        assert start(TestClient(happ)).status_code == 303
    refused = start(TestClient(happ))
    assert refused.status_code == 429 and "the most that one network may start" in refused.text


def test_only_so_many_hospitals_may_exist_at_once(happ):
    happ.state.svc.settings.demo_onboarding_max_active = 2
    happ.state.svc.settings.demo_onboarding_per_address_per_hour = 50
    for n in range(2):
        assert start(TestClient(happ)).status_code == 303
    refused = start(TestClient(happ))
    assert refused.status_code == 503 and "Every demonstration hospital is in use" in refused.text


def test_a_visitor_has_one_hospital_and_starting_another_removes_the_first(web, happ, onb):
    row = go_live(web, happ)
    assert row.slug in onb.apps
    assert web.post("/onboard/restart", follow_redirects=False).headers["location"] == "/onboard"
    assert row.slug not in onb.apps and row.slug not in onb.entries
    assert web.get(f"/synthetic/{row.slug}/").status_code == 404
    with happ.state.svc.session_factory() as db:
        retired = db.scalar(select(DemoHospital).where(DemoHospital.slug == row.slug))
        assert retired.state == "retired" and retired.secret is None and retired.desk_key is None and retired.profile == {"retired": True}
    start(web, "maternity")
    assert hospital(happ).template == "maternity" and hospital(happ).slug != row.slug


def test_a_hospital_expires_and_the_scheduler_job_removes_it_with_its_files(web, happ, onb, tmp_path):
    import asyncio

    from sofa.services import scheduler

    row = go_live(web, happ)
    database = tmp_path / f"provider_{row.slug}.db"
    assert database.exists()
    with happ.state.svc.session_factory() as db:
        held = db.scalar(select(DemoHospital).where(DemoHospital.slug == row.slug))
        held.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    onb.entries[row.slug].expires_at = held.expires_at
    assert "Olive Branch" not in chat(web, ["Please help me find a clinic near me for antenatal care.", "I am in Surulere."])[1]      # not shown once its time is up, even before the sweep
    assert web.get("/onboard/step/6", follow_redirects=False).headers["location"] == "/onboard"
    asyncio.run(scheduler.tick(happ.state.svc))
    assert row.slug not in onb.apps and row.slug not in onb.entries and not database.exists()
    with happ.state.svc.session_factory() as db:
        assert db.scalar(select(DemoHospital).where(DemoHospital.slug == row.slug)) is None
    assert web.get(f"/synthetic/{row.slug}/").status_code == 404


def test_a_hospital_survives_a_restart_with_its_appointment_book(web, happ, onb):
    row = go_live(web, happ)
    chat(web, hospital_profile.suggested_conversation(row.profile))
    code = web.get("/onboard/api/journey").json()["appointments"][0]["code"]
    visitor_cookie = web.cookies.get("talk_demo")
    for slug in list(onb.apps):                      # a restart forgets everything that was in memory
        onb.apps.pop(slug).state.store.db.close()
        onb.mounts.pop(slug)
    onb.entries.clear()
    happ.router.routes = [r for r in happ.router.routes if not getattr(r, "path", "").startswith(f"/synthetic/{row.slug}")]
    happ.state.svc.provider_links.unregister_local("health_" + row.slug.replace("-", "_"))
    assert onb.restore() == 1
    again = TestClient(happ)
    again.cookies.set("talk_demo", visitor_cookie)
    assert again.get("/onboard/api/journey").json()["appointments"][0]["code"] == code
    replies = chat(again, ["Please help me find a clinic near me for antenatal care.", "I am in Surulere."])
    assert "Olive Branch Community General Hospital" in replies[0]     # the same browser: Sofa remembers that this visitor is in Surulere
    assert "Olive Branch Community General Hospital" in replies[1] and "Which day and time" not in replies[1]


def test_the_wizard_answers_404_when_it_is_switched_off(tmp_path):
    app = create_app(Settings(synthetic_hospital=True, services_enabled="health", database_url="sqlite://", storage_dir=str(tmp_path), at_callback_secret=SECRET,
                              public_base_url="http://test", scheduler_enabled=False, talk_number=TALK_NUMBER, demo_onboarding_enabled=False, _env_file=None))
    with TestClient(app) as off:
        for path in ("/onboard", "/onboard/step/2", "/onboard/api/journey"):
            assert off.get(path, follow_redirects=False).status_code == 404
        assert off.post("/onboard/start", data={"template": "general"}).status_code == 404
        assert off.post("/onboard/restart").status_code == 404
        assert "Onboard a hospital" not in off.get("/overview").text
        assert off.get("/try").status_code == 200


def test_the_switch_is_on_by_default_and_listed_in_the_example_settings():
    assert Settings(_env_file=None).demo_onboarding_enabled is True
    text = Path(".env.example").read_text(encoding="utf-8")
    assert "DEMO_ONBOARDING_ENABLED" in text


def test_the_wizard_needs_the_health_service(tmp_path):
    app = create_app(Settings(services_enabled="none", database_url="sqlite://", storage_dir=str(tmp_path), scheduler_enabled=False, _env_file=None))
    with TestClient(app) as off:
        assert off.get("/onboard").status_code == 404


# ---- guards ---------------------------------------------------------------------------------------------------------


def test_the_wizard_cookie_is_signed_and_holds_no_personal_data(web):
    response = start(web)
    cookie = response.headers["set-cookie"]
    assert "talk_demo=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    value = web.cookies.get("talk_demo")
    visitor, _, signature = value.partition(".")
    assert len(signature) == 32 and "+" not in value and "@" not in value


def test_a_starting_choice_that_is_not_a_template_is_refused(web):
    refused = start(web, "casino")
    assert refused.status_code == 400 and "three templates" in refused.text


def test_calls_through_the_wizard_appear_on_the_live_calls_page_like_any_other(web, happ):
    happ.state.svc.settings.demo_page_enabled = True
    row = go_live(web, happ)
    chat(web, ["Please help me find a clinic near me for antenatal care.", "I am in Surulere."])
    page = web.get("/demo").text
    assert "Onboarding demo" in page and "Olive Branch Community General Hospital" in page
    assert "Asked" in page


def test_the_hospital_follows_a_change_made_after_the_connection(web, happ, onb):
    row = go_live(web, happ)
    assert web.post("/onboard/step/2", data={**STEP_FORM, "name": "Kingfisher Family Hospital"}, follow_redirects=False).status_code == 303
    mine = chat(web, ["Please help me find a clinic near me for antenatal care.", "I am in Surulere."])
    assert "Kingfisher Family Hospital" in mine[1] and "Olive Branch" not in mine[1]
    assert onb.entries[row.slug].spec.label == "Kingfisher Family Hospital"


def test_the_guide_of_the_new_hospital_answers_questions_from_its_own_entries(web, happ):
    row = go_live(web, happ)
    reply = chat(web, ["Could you tell me about how appointments work, please?"])[0]
    assert "half-hour slots" in reply


def test_a_question_the_guide_does_not_cover_goes_to_the_new_hospitals_front_desk(web, happ):
    row = go_live(web, happ)
    reply = chat(web, ["Could you ask the centre about parking at night, please?"])[0]
    store = happ.state.svc.onboarding.apps[row.slug].state.store
    assert "passed it to the care team" in reply or "parking" in reply.lower()
    assert len(store.requests()) == 1


def test_a_closed_place_is_described_in_a_natural_sentence():
    from sofa.health import speak

    closed = {"name": "Surulere Care Clinic", "owner": "private", "kind": "clinic", "km": 0.3, "open_now": False, "all_day": False, "fee": 8000,
              "travel": "about 10 minutes away by road with the usual traffic at this hour"}
    assert speak.option_line(closed) == ("Surulere Care Clinic, a private clinic, about 10 minutes away by road with the usual traffic at this hour, which is closed now, "
                                         "and with a consultation fee of 8,000 naira")
    del closed["travel"]    # until the caller has said where they are, no distance is spoken at all
    assert speak.option_line(closed) == "Surulere Care Clinic, a private clinic, which is closed now, and with a consultation fee of 8,000 naira"
