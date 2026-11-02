"""Follow-up: Talk reminds a patient before a visit it booked, checks with the clinic's own book afterwards, thanks the patient who came and reaches out to the one who
did not. The clinic stays the source of truth; texts go out only in daytime, once each, and never name what is treated."""

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select

from sofa.health import followups
from sofa.models import HealthAppointment, Notification
from tests.support import CALLER, FIXED, OTHER, call

TUESDAY_MORNING = datetime(2026, 10, 27, 10, 20)         # the day before the booked visit
VISIT_DAY_NOON = datetime(2026, 10, 28, 12, 0)           # the booked visit (8 in the morning) is over
# Aguda Community Health Centre, tomorrow at 8 in the morning, booked the way a caller would: a request, an area, a choice, a time and a confirmation
BOOK_ANY_CLINIC = ["Hello, I would like to book an appointment, please.", "I am in Surulere.", "The second one, please.", "Tomorrow morning, please.", "Yes, please go ahead."]
BOOK_CANCER_CENTRE = ["Please book an appointment at the cancer centre.", "I am in Ikeja.", "Tomorrow morning, please.", "Yes, please go ahead."]


def run(happ, now):
    return asyncio.run(followups.run(happ.state.svc, now))


def nothing_was_done(done: dict) -> bool:
    """True when a pass sent and recorded nothing at all, whatever kinds of follow-up it counts."""
    return not any(done.values())


def texts(hdb, template):
    return [n for n in hdb.scalars(select(Notification).where(Notification.template == template)) if n.to_number == CALLER]


def mark(happ, slug, hdb, outcome):
    row = hdb.scalar(select(HealthAppointment))
    assert happ.state.providers[slug].state.store.mark(row.code, outcome)
    return row


def test_a_visit_the_hospital_has_confirmed_is_confirmed_to_the_patient_by_text_once(client, happ, hdb):
    call(client, BOOK_ANY_CLINIC)
    assert run(happ, TUESDAY_MORNING)["confirmed"] == 0 and texts(hdb, "health_confirmed") == []        # the hospital has not confirmed it yet, so nothing is said
    code = hdb.scalar(select(HealthAppointment)).code
    assert happ.state.providers["state-phc"].state.store.confirm(code)       # the hospital's staff confirm the visit on their own front desk
    done = run(happ, TUESDAY_MORNING + timedelta(minutes=5))
    assert done["confirmed"] == 1 and done["reminders"] == 0       # the reminder had already gone out in the first pass, and it is not repeated for a confirmed visit
    sent = texts(hdb, "health_confirmed")
    assert len(sent) == 1 and "Good news from Aguda Community Health Centre: the hospital has confirmed your appointment for tomorrow at 8 in the morning." in sent[0].body
    assert f"Your booking code is {code}." in sent[0].body and "Please arrive 15 minutes early." in sent[0].body
    hdb.expire_all()
    assert hdb.scalar(select(HealthAppointment)).status == "confirmed"       # Talk's own record now matches the hospital's
    assert run(happ, TUESDAY_MORNING + timedelta(minutes=10))["confirmed"] == 0 and len(texts(hdb, "health_confirmed")) == 1      # the patient is told only once


def test_a_visit_that_is_already_over_is_never_announced_as_confirmed(client, happ, hdb):
    call(client, BOOK_ANY_CLINIC)
    row = mark(happ, "state-phc", hdb, "attended")
    assert happ.state.providers["state-phc"].state.store.confirm(row.code) is False        # a visit already marked as attended cannot be confirmed afterwards
    assert run(happ, VISIT_DAY_NOON)["confirmed"] == 0 and texts(hdb, "health_confirmed") == []      # and a visit whose time has passed is never announced as confirmed


def test_the_text_that_confirms_a_visit_names_the_place_by_its_discreet_name_and_says_when():
    row = HealthAppointment(caller_id=1, provider="health_onc_centre", code="APT-ABCD", facility_name="Oncology Care Centre Ikeja", sms_name="the Ikeja care centre",
                            starts_local="2026-10-30T14:30:00")
    body = followups.confirmed_text(row, TUESDAY_MORNING)
    assert body.startswith("Good news from the Ikeja care centre: the hospital has confirmed your appointment for Friday 30 October at 2:30 in the afternoon.")
    assert "Your booking code is APT-ABCD." in body and "Oncology" not in body and "cancer" not in body.lower()


def test_a_visit_coming_up_gets_one_reminder(client, happ, hdb):
    call(client, BOOK_ANY_CLINIC)
    assert run(happ, TUESDAY_MORNING)["reminders"] == 1
    sent = texts(hdb, "health_reminder")
    assert len(sent) == 1 and "tomorrow at 8 in the morning" in sent[0].body and "Aguda Community Health Centre" in sent[0].body
    assert "friendly reminder" in sent[0].body and "Your booking code is APT-" in sent[0].body
    assert run(happ, TUESDAY_MORNING)["reminders"] == 0 and len(texts(hdb, "health_reminder")) == 1       # once only


def test_no_reminder_in_the_night_or_more_than_a_day_ahead(client, happ, hdb):
    call(client, BOOK_ANY_CLINIC)
    assert run(happ, datetime(2026, 10, 27, 5, 0))["reminders"] == 0       # before 7 in the morning
    assert run(happ, datetime(2026, 10, 26, 9, 0))["reminders"] == 0       # more than a day before
    assert run(happ, datetime(2026, 10, 27, 21, 0))["reminders"] == 0      # after 8 in the evening
    assert run(happ, datetime(2026, 10, 28, 7, 30))["reminders"] == 1      # the morning of the visit, once it is day again
    assert texts(hdb, "health_reminder")[0].body.count("today at 8") == 1


def test_a_patient_who_came_is_thanked_once(client, happ, hdb):
    call(client, BOOK_ANY_CLINIC)
    mark(happ, "state-phc", hdb, "attended")
    done = run(happ, VISIT_DAY_NOON)
    assert done["attended"] == 1 and done["thanked"] == 1
    thanks = texts(hdb, "health_thanks")
    assert len(thanks) == 1 and "Thank you for coming to Aguda Community Health Centre" in thanks[0].body and "book your next visit" in thanks[0].body
    assert nothing_was_done(run(happ, VISIT_DAY_NOON))
    hdb.expire_all()
    assert hdb.scalar(select(HealthAppointment)).status == "attended"


def test_a_patient_who_did_not_come_hears_from_us_once(client, happ, hdb):
    call(client, BOOK_ANY_CLINIC)
    mark(happ, "state-phc", hdb, "no_show")
    done = run(happ, VISIT_DAY_NOON)
    assert done["missed"] == 1 and done["chased"] == 1
    missed = texts(hdb, "health_missed")
    assert len(missed) == 1 and "We missed you at Aguda Community Health Centre" in missed[0].body and "To book a new time" in missed[0].body
    assert run(happ, VISIT_DAY_NOON)["chased"] == 0


def test_a_visit_the_clinic_has_not_marked_is_left_alone(client, happ, hdb):
    call(client, BOOK_ANY_CLINIC)
    assert nothing_was_done(run(happ, VISIT_DAY_NOON))
    hdb.expire_all()
    assert hdb.scalar(select(HealthAppointment)).status == "booked" and texts(hdb, "health_thanks") == [] and texts(hdb, "health_missed") == []     # nobody is told anything untrue


def test_a_follow_up_waits_for_daytime_and_is_sent_when_it_comes(client, happ, hdb):
    call(client, BOOK_ANY_CLINIC)
    mark(happ, "state-phc", hdb, "attended")
    assert run(happ, datetime(2026, 10, 28, 21, 0))["thanked"] == 0         # recorded as attended, but not texted at 9 in the evening
    assert run(happ, datetime(2026, 10, 29, 8, 0))["thanked"] == 1


def test_a_cancelled_visit_is_not_reminded(client, happ, hdb):
    call(client, BOOK_ANY_CLINIC)
    call(client, ["Please can you cancel my appointment?", "Yes, please."])
    hdb.expire_all()
    assert hdb.scalar(select(HealthAppointment)).status == "cancelled"
    assert run(happ, TUESDAY_MORNING)["reminders"] == 0


def test_each_patient_is_followed_up_only_about_their_own_visit(client, happ, hdb):
    call(client, BOOK_ANY_CLINIC)
    call(client, BOOK_ANY_CLINIC, OTHER)
    assert run(happ, TUESDAY_MORNING)["reminders"] == 2
    assert len(texts(hdb, "health_reminder")) == 1 and len([n for n in hdb.scalars(select(Notification).where(Notification.template == "health_reminder"))]) == 2


def test_the_texts_never_name_what_is_treated(client, happ, hdb):
    call(client, BOOK_CANCER_CENTRE)
    run(happ, TUESDAY_MORNING)
    mark(happ, "onc-centre", hdb, "attended")
    run(happ, VISIT_DAY_NOON)
    bodies = [n.body for n in hdb.scalars(select(Notification).where(Notification.template.in_(("health_notice", "health_reminder", "health_thanks"))))]
    assert len(bodies) == 3 and all("the Ikeja care centre" in b for b in bodies)
    assert not any("oncology" in b.lower() or "cancer" in b.lower() for b in bodies)


def test_a_clinic_that_cannot_be_reached_does_not_stop_the_pass(client, happ, hdb):
    call(client, BOOK_ANY_CLINIC)
    happ.state.net.down.update({"state-phc", "eko-care", "everwell", "onc-centre"})
    assert run(happ, VISIT_DAY_NOON)["attended"] == 0
    hdb.expire_all()
    assert hdb.scalar(select(HealthAppointment)).status == "booked"


def test_without_the_health_front_desk_there_is_nothing_to_do(tmp_path):
    from sofa.config import Settings
    from sofa.main import create_app

    app = create_app(Settings(database_url="sqlite://", storage_dir=str(tmp_path), at_callback_secret="x", public_base_url="http://test", scheduler_enabled=False, _env_file=None))
    assert nothing_was_done(asyncio.run(followups.run(app.state.svc, FIXED)))
