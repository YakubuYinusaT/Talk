"""A caller reaches the health network through Talk, over several turns, the way people really speak on the phone. Talk asks three independent provider systems (a state
health network, a private clinic group, a pharmacy chain) and a simulated cancer centre, puts the real options in front of the caller, and asks which one they mean: an
area is not a hospital. Only then does it ask a provider for slots and book. Nothing in Talk is written for any one provider: they sit behind the health front desk.

Every conversation below is written as a caller would say it: a polite opening, an answer to each question Talk asks, and a polite closing. The first line of each list
is what the caller says after the greeting, so the reply with the same number as a line is Talk's answer to it, and replies[0] is the greeting."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from sofa.config import Settings
from sofa.orchestrator.adapters.health import HealthAdapter
from sofa.main import create_app
from sofa.models import Handoff, HealthAppointment, HealthRequest, Notification
from tests.support import CALLER, TALK_NUMBER, OTHER, SECRET, appointments, call

WANT_TO_BOOK = "Hello, I would like to book an appointment, please."
IN_SURULERE = "I am in Surulere."
TOMORROW_MORNING = "Tomorrow morning, please."
YES_PLEASE = "Yes, please go ahead."

# the conversation that books Aguda Community Health Centre (the cheaper clinic in Surulere) for tomorrow at 8 in the morning
BOOK_AT_AGUDA = [WANT_TO_BOOK, IN_SURULERE, "The second one, please.", TOMORROW_MORNING, YES_PLEASE]


def another_caller(n: int) -> str:
    """A different phone number for each caller in a test that places several calls, so that none of them is mistaken for the same person."""
    return f"+23480555500{n:02d}"


# ---- how it is set up ---------------------------------------------------------------------------------------------------------------


def test_the_provider_systems_are_not_there_unless_they_are_switched_on(tmp_path):
    app = create_app(Settings(database_url="sqlite://", storage_dir=str(tmp_path), at_callback_secret=SECRET, public_base_url="http://test", scheduler_enabled=False,
                              services_enabled="none", talk_number=TALK_NUMBER, _env_file=None))
    with TestClient(app) as c:
        assert c.get("/synthetic/state-phc/").status_code == 404
    assert "health" not in app.state.svc.orchestrator.domains()


def test_the_provider_systems_run_beside_talk_when_they_are_switched_on(client, happ):
    assert client.get("/synthetic/state-phc/").status_code == 200
    assert "health" in happ.state.svc.orchestrator.domains()


# ---- the whole conversation, from the first request to a cancellation --------------------------------------------------------------------


def test_the_conversation_from_finding_a_clinic_to_booking_and_cancelling_it_is_held_over_several_turns(client, happ, hdb):
    replies = call(client, ["Please help me find the nearest clinic for antenatal care.", IN_SURULERE, "Yes, please book the private clinic.", TOMORROW_MORNING, YES_PLEASE,
                            "Please can you cancel my appointment for tomorrow?", "Yes, please."])
    assert "which area of Lagos you are in" in replies[1] and "Surulere" not in replies[1]                       # an area is asked for politely, not guessed
    assert "I found three places near Surulere for antenatal care." in replies[2] and "Would you like me to book an appointment at one of them for you?" in replies[2]
    assert "Which day and time would you like at Surulere Care Clinic" in replies[3]                              # one sentence answered the offer and chose the clinic
    assert "I can book you at Surulere Care Clinic tomorrow at 8 in the morning." in replies[4] and "Would you like me to book it for you?" in replies[4]
    assert "Your appointment is confirmed at Surulere Care Clinic tomorrow at 8 in the morning." in replies[5] and "booking code is" in replies[5]
    assert "A text message with these details is on its way to you." in replies[5]
    assert "Your appointment is at Surulere Care Clinic tomorrow at 8 in the morning. Would you like me to cancel it?" in replies[6]
    assert "Your appointment has been cancelled." in replies[7] and "A text message to confirm this is on its way to you." in replies[7]
    assert appointments(happ, "eko-care") == []                                                                   # the private clinic's own book no longer holds it
    assert hdb.scalar(select(HealthAppointment)).status == "cancelled"


# ---- finding a place -----------------------------------------------------------------------------------------------------------------------


def test_a_caller_who_gives_no_area_is_asked_for_it_and_the_answer_is_understood(client, happ):
    asked = call(client, ["Please help me find the nearest clinic for antenatal care."])
    assert "Could you please tell me which area of Lagos you are in?" in asked[1]
    assert not [slug for slug, body in happ.state.net.seen if '"search"' in body]                                 # no provider is asked before there is an area to ask about
    replies = call(client, ["Please help me find the nearest clinic for antenatal care.", IN_SURULERE, "No, thank you."], OTHER)
    options = replies[2]
    assert "I found three places near Surulere for antenatal care." in options
    assert "Aguda Community Health Centre" in options and "Surulere Care Clinic" in options        # a state centre and a private clinic, from two different systems
    assert "state primary health centre" in options and "private clinic" in options and "naira" in options and "minutes" in options
    assert "Would you like me to book an appointment at one of them for you?" in options
    assert {slug for slug, body in happ.state.net.seen if '"search"' in body} >= {"state-phc", "eko-care"}
    assert "That is no problem at all." in replies[3]


def test_a_caller_who_gives_the_area_up_front_is_not_asked_for_it_again(client):
    replies = call(client, ["Please help me find a clinic for antenatal care in Surulere.", "No, thank you."])
    assert "which area of Lagos" not in replies[1] and "I found three places near Surulere for antenatal care." in replies[1]
    assert "Surulere Care Clinic" in replies[1] and "Aguda Community Health Centre" in replies[1]


def test_the_options_are_read_out_nearest_first_with_the_waiting_time_and_the_fee_of_each(client):
    replies = call(client, ["Please help me find a clinic in Ikeja.", "No, thank you."])
    options = replies[1]
    assert "The first is Ikeja Allen Medical Centre, a private clinic" in options and "The second is Ikeja Heights General Hospital, a state general hospital" in options
    assert "The third is Agege Pen Cinema Health Centre" in options
    assert options.count("a consultation fee of") == 3 and options.count("of waiting") == 3


def test_a_cancer_centre_is_found_only_when_the_caller_needs_cancer_care(client):
    replies = call(client, ["Please help me find a clinic for cancer care.", "I am in Ikeja.", "No, thank you."])
    assert "The nearest place for cancer care is Oncology Care Centre Ikeja, a state cancer centre on Oba Akran Avenue" in replies[2]
    ordinary = call(client, ["Please help me find a clinic.", "I am in Ikeja.", "No, thank you."], OTHER)
    assert "Oncology Care Centre" not in ordinary[2]       # a specialist centre is not a general clinic


def test_what_the_model_understands_by_meaning_picks_the_service(client, said):
    said["Please help me find a clinic for my baby's jabs."] = {"need": "child immunisation"}
    said["We live in Mushin."] = {"area": "Mushin"}
    replies = call(client, ["Please help me find a clinic for my baby's jabs.", "We live in Mushin."])
    assert "which area of Lagos you are in" in replies[1]
    assert "I found three places near Mushin for child immunisation." in replies[2] and "Mushin Grace Clinic" in replies[2]


def test_a_caller_who_names_the_area_and_the_need_in_one_sentence_is_not_asked_again(client, said):
    said["Please help me find the nearest clinic in Yaba."] = {"area": "Yaba"}
    assert "Yaba Mainland Health Centre" in call(client, ["Please help me find the nearest clinic in Yaba."])[1]


def test_one_provider_down_does_not_stop_the_others(client, happ):
    happ.state.net.down.add("state-phc")
    replies = call(client, ["Please help me find the nearest clinic for antenatal care.", IN_SURULERE])
    assert "Surulere Care Clinic" in replies[2] and "Aguda" not in replies[2]


# ---- medicines -----------------------------------------------------------------------------------------------------------------------------


def test_a_medicine_named_in_the_first_sentence_is_looked_up_at_the_pharmacy_chain_at_once(client):
    replies = call(client, ["Hello, do you have amoxicillin in stock, please?"])
    assert "Amoxicillin 500 milligram capsules" in replies[1] and "Everwell Pharmacy" in replies[1] and "naira" in replies[1]
    assert "needs a prescription from a doctor" in replies[1]
    assert "Which medicine" not in replies[1]       # the caller already said it


def test_a_caller_who_does_not_name_the_medicine_is_asked_for_it_and_the_answer_is_understood(client):
    replies = call(client, ["Hello, do you have medicine in stock, please?", "Amoxicillin five hundred milligram capsules."])
    assert "Which medicine are you looking for, please?" in replies[1]
    assert "Amoxicillin 500 milligram capsules" in replies[2] and "Everwell Pharmacy" in replies[2] and "needs a prescription from a doctor" in replies[2]


def test_a_medicine_said_loosely_is_still_found(client, said):
    said["Hello, do you have coartem in stock, please?"] = {"drug": "coartem"}
    replies = call(client, ["Hello, do you have coartem in stock, please?"])
    assert "Artemether and lumefantrine tablets for malaria" in replies[1] and "needs a prescription from a doctor" in replies[1]


# ---- booking: the caller chooses the place --------------------------------------------------------------------------------------------------


def test_an_area_is_not_a_hospital_so_the_caller_is_asked_which_one(client, happ):
    replies = call(client, [WANT_TO_BOOK, IN_SURULERE, "The private clinic, please.", TOMORROW_MORNING, YES_PLEASE])
    assert "Which clinic would you like, or which area of Lagos are you in?" in replies[1]
    options = replies[2]
    assert "I found three places near Surulere." in options and "Aguda Community Health Centre" in options and "Surulere Care Clinic" in options
    assert "Which one would you like, please?" in options
    assert "Which day and time would you like at Surulere Care Clinic" in replies[3]
    assert "I can book you at Surulere Care Clinic tomorrow at 8 in the morning" in replies[4] and "Would you like me to book it for you?" in replies[4]
    assert "Your appointment is confirmed at Surulere Care Clinic tomorrow at 8 in the morning" in replies[5] and "booking code is" in replies[5]
    assert "text message" in replies[5]
    assert len(appointments(happ, "eko-care")) == 1 and appointments(happ, "state-phc") == []     # booked with the private clinic's own system, and only there


def test_the_caller_can_choose_by_position_by_price_by_name_or_by_how_busy(client, happ):
    def asked_for(choice: str, who: str) -> str:
        return call(client, [WANT_TO_BOOK, IN_SURULERE, choice], who)[3]

    assert "Which day and time would you like at Aguda Community Health Centre" in asked_for("The cheaper one, please.", another_caller(1))
    assert "Which day and time would you like at Surulere Care Clinic" in asked_for("The first one, please.", another_caller(2))
    assert "Which day and time would you like at Aguda Community Health Centre" in asked_for("Aguda, please.", another_caller(3))
    assert "Which day and time would you like at Surulere Care Clinic" in asked_for("The quicker one, please.", another_caller(4))


def test_a_caller_who_names_a_clinic_and_a_time_in_one_sentence_is_only_asked_where_they_will_travel_from(client, happ, said):
    said["Please book me an appointment at Aguda tomorrow morning."] = {"facility": "Aguda", "when": "tomorrow morning"}
    replies = call(client, ["Please book me an appointment at Aguda tomorrow morning.", "Yes, I will come from Surulere.", "Yes, please."])
    assert "Will you be travelling to Aguda Community Health Centre from Surulere" in replies[1]       # no which-one and no what-time: only where from
    assert "I can book you at Aguda Community Health Centre tomorrow at 8 in the morning" in replies[2] and "please plan to leave by" in replies[2]
    assert "Your appointment is confirmed at Aguda Community Health Centre" in replies[3] and len(appointments(happ, "state-phc")) == 1


def test_a_vague_request_is_asked_about_one_thing_at_a_time(client):
    replies = call(client, [WANT_TO_BOOK, IN_SURULERE, "The first one, please.", "Friday afternoon, please.", YES_PLEASE])
    assert "Which clinic would you like, or which area of Lagos are you in?" in replies[1] and "I found three places near Surulere." in replies[2]
    assert "Which day and time would you like" in replies[3] and "Friday 30 October at 12 noon" in replies[4]
    assert "Your appointment is confirmed" in replies[5] and "Friday 30 October" in replies[5]


def test_a_value_that_is_not_in_the_callers_words_is_dropped_and_asked_for(client, said):
    said["Please book me an appointment."] = {"facility": "Aguda Community Health Centre", "when": "Friday 30 October"}       # the model made these up
    replies = call(client, ["Please book me an appointment."])
    assert "Which clinic would you like, or which area of Lagos are you in?" in replies[1]


def test_a_no_asks_for_another_time_and_a_new_time_replaces_the_old_one(client):
    replies = call(client, [WANT_TO_BOOK, IN_SURULERE, "The second one, please.", TOMORROW_MORNING, "No, thank you.", "Thursday at two in the afternoon, please.", YES_PLEASE])
    assert "That is no problem. Which day and time would suit you better?" in replies[5]
    assert "Thursday 29 October at 2 in the afternoon" in replies[6] and "Your appointment is confirmed" in replies[7]


def test_a_slot_taken_while_the_caller_was_deciding_is_not_booked_and_the_next_is_offered(client, happ):
    store = happ.state.providers["state-phc"].state.store

    def fill_the_slot():                      # two other patients take the offered slot while the caller thinks
        for who in ("x", "y"):
            store.book(store.by_id["hc-aguda"], datetime(2026, 10, 28, 8, 0), "general consultation", who)

    happ.state.net.before_book = fill_the_slot
    replies = call(client, BOOK_AT_AGUDA)
    assert "I can book you at Aguda Community Health Centre tomorrow at 8 in the morning" in replies[4]
    assert "I am sorry, that time has just been taken." in replies[5] and "8:30" in replies[5] and "Would you like me to book it for you?" in replies[5]
    assert len([a for a in appointments(happ, "state-phc") if a["caller_ref"] not in ("x", "y")]) == 0     # nothing was booked for the caller


def test_a_caller_who_cannot_choose_is_not_pushed(client, happ):
    replies = call(client, ["Hello, I would like to book an appointment in Surulere, please.", "I am not sure, I do not know.", "I am sorry, I really cannot decide."])
    assert "I am sorry, I did not catch which one you mean." in replies[2] and "Aguda Community Health Centre" in replies[2]
    assert "confirmed" not in replies[3] and "That is no problem at all." in replies[3]
    assert appointments(happ, "state-phc") == [] and appointments(happ, "eko-care") == []


def test_asking_for_the_area_does_not_use_up_a_try_of_the_question_that_asks_which_clinic(client, happ):
    replies = call(client, [WANT_TO_BOOK, IN_SURULERE, "I am not sure, I do not know.", "The second one, please.", TOMORROW_MORNING, YES_PLEASE])
    assert "I am sorry, I did not catch which one you mean." in replies[3] and "Aguda Community Health Centre" in replies[3]      # asked once more, not dropped at once
    assert "Which day and time would you like at Aguda Community Health Centre" in replies[4] and "Your appointment is confirmed" in replies[6]
    assert len(appointments(happ, "state-phc")) == 1


def test_asking_for_the_area_does_not_use_up_a_try_of_the_question_that_asks_when(client, happ):
    replies = call(client, [WANT_TO_BOOK, IN_SURULERE, "The second one, please.", "Hmm.", TOMORROW_MORNING, YES_PLEASE])
    assert "I did not catch the day and time" in replies[4]      # asked once more, not dropped at once
    assert "Your appointment is confirmed" in replies[6] and len(appointments(happ, "state-phc")) == 1


def test_a_caller_who_still_cannot_choose_after_being_asked_twice_is_let_go_politely(client, happ):
    replies = call(client, [WANT_TO_BOOK, IN_SURULERE, "I am not sure, I do not know.", "I am sorry, I really cannot decide."])
    assert "I did not catch which one you mean" in replies[3] and "confirmed" not in replies[4] and "That is no problem at all." in replies[4]
    assert appointments(happ, "state-phc") == [] and appointments(happ, "eko-care") == []


def test_the_model_chooses_when_the_rules_cannot(client, said):
    said["choice:The one near the market, please."] = "2"
    replies = call(client, [WANT_TO_BOOK, IN_SURULERE, "The one near the market, please.", TOMORROW_MORNING, YES_PLEASE])
    assert "Which day and time would you like at Aguda Community Health Centre" in replies[3] and "Your appointment is confirmed at Aguda" in replies[5]


@pytest.mark.parametrize("polite", ["Hmm, let me think about it, please.", "Please tell me more.", "Please.", "Thank you.", "Okay, please wait a moment.", "Please, I am not sure."])
def test_a_polite_sentence_that_is_not_a_yes_does_not_book_the_appointment(client, happ, polite):
    replies = call(client, BOOK_AT_AGUDA[:4] + [polite])
    assert "Your appointment is confirmed" not in replies[5]
    assert appointments(happ, "state-phc") == [] and appointments(happ, "eko-care") == []


@pytest.mark.parametrize("agreement", ["Yes, please go ahead.", "Yes, please.", "Yeah.", "Okay, that is fine.", "Sure.", "Please book it.", "Please do."])
def test_a_clear_agreement_books_the_appointment_however_politely_it_is_said(client, happ, agreement):
    replies = call(client, BOOK_AT_AGUDA[:4] + [agreement])
    assert "Your appointment is confirmed at Aguda Community Health Centre" in replies[5]
    assert len(appointments(happ, "state-phc")) == 1


def test_a_polite_sentence_that_is_not_a_yes_does_not_accept_the_offer_to_book(client, happ):
    replies = call(client, ["Please help me find the nearest clinic for antenatal care.", IN_SURULERE, "Please tell me more."])
    assert "Which day and time" not in replies[3] and "Your appointment is confirmed" not in replies[3]
    assert appointments(happ, "state-phc") == [] and appointments(happ, "eko-care") == []


def test_a_polite_sentence_that_is_not_a_yes_does_not_cancel_the_appointment(client, happ):
    call(client, BOOK_AT_AGUDA)
    replies = call(client, ["Please can you cancel my appointment?", "Please tell me more."])
    assert "Would you like me to cancel it?" in replies[1] and "has been cancelled" not in replies[2]
    assert len(appointments(happ, "state-phc")) == 1


@pytest.mark.parametrize("agreement", ["Yes, please cancel it.", "Please cancel it.", "Yes, please.", "Okay, no problem, go ahead."])
def test_a_clear_agreement_cancels_the_appointment_and_the_word_cancel_is_not_taken_for_a_no(client, happ, agreement):
    call(client, BOOK_AT_AGUDA)
    replies = call(client, ["Please can you cancel my appointment?", agreement])
    assert "Your appointment has been cancelled." in replies[2]
    assert appointments(happ, "state-phc") == []


@pytest.mark.parametrize("refusal", ["No, please do not cancel it.", "Please keep it.", "No, thank you.", "Please do not cancel it."])
def test_a_clear_refusal_keeps_the_appointment(client, happ, refusal):
    call(client, BOOK_AT_AGUDA)
    replies = call(client, ["Please can you cancel my appointment?", refusal])
    assert "I have kept your appointment as it is." in replies[2]
    assert len(appointments(happ, "state-phc")) == 1


@pytest.mark.parametrize("text, answer", [
    ("Yes, please go ahead.", "yes"), ("Yes please", "yes"), ("Yeah, that is fine.", "yes"), ("Okay, no problem, go ahead.", "yes"), ("Please book it.", "yes"), ("Please do.", "yes"),
    ("No, thank you.", "no"), ("No, please change it.", "no"), ("Please do not.", "no"), ("I do not want it.", "no"), ("Never mind.", "no"),
    ("Please.", None), ("Thank you.", None), ("Please tell me more.", None), ("Please, I am not sure.", None), ("Okay, let me think about it.", None), ("Blue.", None),
])
def test_consent_needs_an_affirmative_word_and_politeness_alone_is_never_one(text, answer):
    from sofa.health.when import answer_of

    assert answer_of(text) == answer


def test_when_the_question_was_whether_to_cancel_the_word_cancel_means_yes_and_keep_means_no():
    from sofa.health.when import answer_of

    assert answer_of("Please cancel it.", cancelling=True) == "yes" and answer_of("Cancel it, please.") == "no"
    assert answer_of("Please keep it.", cancelling=True) == "no" and answer_of("Do not cancel it.", cancelling=True) == "no"
    assert answer_of("Please tell me more.", cancelling=True) is None


def test_a_text_confirmation_goes_only_to_the_caller_and_only_when_accepted(client, hdb):
    call(client, BOOK_AT_AGUDA)
    texts = hdb.scalars(select(Notification).where(Notification.template == "health_notice")).all()
    assert len(texts) == 1 and texts[0].to_number == CALLER
    assert texts[0].body.startswith("Your appointment at Aguda Community Health Centre is confirmed for Wednesday 28 October at 8 in the morning.")


def test_a_booking_that_is_declined_at_the_last_step_sends_no_text(client, hdb, happ):
    call(client, [WANT_TO_BOOK, IN_SURULERE, "The second one, please.", TOMORROW_MORNING, "No, thank you.", "No, thank you."])
    assert not hdb.scalars(select(Notification).where(Notification.template == "health_notice")).all()
    assert appointments(happ, "state-phc") == []


# ---- status and slots -----------------------------------------------------------------------------------------------------------------------


def test_the_queue_and_hours_of_a_named_place(client, said):
    said["How busy is Aguda right now, please?"] = {"facility": "Aguda"}
    replies = call(client, ["How busy is Aguda right now, please?"])
    assert "Aguda Community Health Centre, a state primary health centre on Bode Thomas Street" in replies[1] and "open until 4 in the evening" in replies[1]
    assert "waiting" in replies[1] and "500 naira" in replies[1] and "It also offers" in replies[1]


def test_the_free_times_at_a_named_place(client, said):
    said["What times are free at Surulere Care, please?"] = {"facility": "Surulere Care"}
    replies = call(client, ["What times are free at Surulere Care, please?"])
    assert "The next free appointment times at Surulere Care Clinic are" in replies[1] and "today at" in replies[1]


# ---- cancelling ----------------------------------------------------------------------------------------------------------------------------------


def test_a_caller_cancels_their_appointment_with_whichever_provider_holds_it(client, hdb, happ):
    call(client, BOOK_AT_AGUDA)
    replies = call(client, ["Please can you cancel my appointment?", "Yes, please."])
    assert "Your appointment is at Aguda Community Health Centre tomorrow at 8 in the morning." in replies[1] and "Would you like me to cancel it?" in replies[1]
    assert "Your appointment has been cancelled." in replies[2] and "text message" in replies[2]
    assert appointments(happ, "state-phc") == []
    assert hdb.scalar(select(Notification).where(Notification.body.like("Your appointment APT-% has been cancelled.%")))
    assert "I could not find an appointment booked for you" in call(client, ["Please can you cancel my appointment?"], OTHER)[1]


def test_the_day_with_no_appointment_is_said_in_a_complete_sentence_with_on_before_a_date(client):
    call(client, BOOK_AT_AGUDA)
    on_friday = call(client, ["Please can you cancel my appointment for Friday?"])[1]
    assert "I am sorry, I could not find an appointment booked for you on Friday 30 October." in on_friday
    assert "I am sorry, I could not find an appointment booked for you tomorrow." not in on_friday


def test_a_day_that_is_a_date_is_offered_and_confirmed_with_on_before_it(client):
    replies = call(client, [WANT_TO_BOOK, IN_SURULERE, "The first one, please.", "Friday afternoon, please.", YES_PLEASE])
    assert "I can book you at Surulere Care Clinic on Friday 30 October at 12 noon." in replies[4]
    assert "Your appointment is confirmed at Surulere Care Clinic on Friday 30 October at 12 noon." in replies[5]


def test_a_caller_who_names_the_day_cancels_the_appointment_of_that_day(client, happ):
    call(client, BOOK_AT_AGUDA)
    assert "tomorrow at 8 in the morning" in call(client, ["Please can you cancel my appointment for tomorrow?"])[1]
    none_on_friday = call(client, ["Please can you cancel my appointment for Friday?"])[1]
    assert "I could not find an appointment booked for you" in none_on_friday and "Friday 30 October" in none_on_friday     # and the one for tomorrow is left alone
    assert len(appointments(happ, "state-phc")) == 1


def test_a_no_keeps_the_appointment(client, happ):
    call(client, BOOK_AT_AGUDA)
    replies = call(client, ["Please can you cancel my appointment?", "No, thank you."])
    assert "I have kept your appointment as it is." in replies[2] and len(appointments(happ, "state-phc")) == 1


# ---- what the providers see ---------------------------------------------------------------------------------------------------------------------------


def test_each_provider_sees_a_different_reference_and_never_the_phone_number(client, happ):
    import json

    call(client, ["Please help me find the nearest clinic for antenatal care.", IN_SURULERE, "No, thank you."])
    seen = happ.state.net.seen
    assert seen and all(CALLER not in body and CALLER.replace("+234", "0") not in body for _, body in seen)
    ids = {slug: json.loads(body)["context"]["caller_id"] for slug, body in seen if '"op":"call"' in body}
    assert len(set(ids.values())) == len(ids) >= 2


# ---- an emergency is never answered with a menu ----------------------------------------------------------------------------------------------------


def gives_112_first(reply: str) -> bool:
    """The first sentence the caller hears asks them to call 112."""
    return "call 112 now" in reply.split(". ")[0]


def test_an_emergency_gets_the_emergency_number_first_and_no_queue(client):
    replies = call(client, ["Please, my brother is not breathing, we are in Ikeja."])
    assert gives_112_first(replies[1]) and "Ikeja Heights General Hospital" in replies[1]
    assert "people are waiting" not in replies[1] and "book an appointment" not in replies[1]
    assert "I have told their team about you" in replies[1] and "Were you able to reach 112?" in replies[1]


def test_an_emergency_with_no_area_gets_the_emergency_number_at_once_and_then_the_nearest_care(client):
    replies = call(client, ["Please, my brother is not breathing.", "We are in Ikeja."])
    assert gives_112_first(replies[1]) and "Where are you, please" in replies[1]
    assert gives_112_first(replies[2]) and "Ikeja Heights General Hospital" in replies[2]
    assert "book an appointment" not in replies[2] and "people are waiting" not in replies[2]


def test_an_emergency_in_the_middle_of_something_else_takes_over(client):
    replies = call(client, [WANT_TO_BOOK, IN_SURULERE, "Please, my father has collapsed and he is unconscious, we are in Ikeja."])
    assert gives_112_first(replies[3]) and "Ikeja Heights General Hospital" in replies[3]


ALL_PROVIDERS = {"state-phc", "eko-care", "everwell", "onc-centre"}
EMERGENCY_FIRST = "If this is an emergency, please call 112 now."


def test_an_emergency_gets_the_emergency_number_first_even_when_every_clinic_system_is_down(client, happ):
    happ.state.net.down = set(ALL_PROVIDERS)
    replies = call(client, ["Please, my brother is not breathing, we are in Ikeja."])
    assert gives_112_first(replies[1])
    assert "could not reach the clinics" in replies[1] and "Is there anything else I can help with?" in replies[1]
    assert "not available right now" not in replies[1]      # the ordinary apology for a service that is down says nothing about the emergency number


def test_an_emergency_with_no_area_still_hears_the_emergency_number_when_every_clinic_system_is_down(client, happ):
    happ.state.net.down = set(ALL_PROVIDERS)
    replies = call(client, ["Please, my brother is not breathing.", "We are in Ikeja."])
    assert gives_112_first(replies[1]) and "Where are you, please" in replies[1]
    assert gives_112_first(replies[2]) and "could not reach the clinics" in replies[2]


def test_an_emergency_when_no_provider_is_set_up_at_all_still_hears_the_emergency_number(client, happ):
    happ.state.svc.orchestrator.adapter("health").providers = []
    replies = call(client, ["Please, my brother is not breathing, we are in Ikeja."])
    assert gives_112_first(replies[1]) and "could not reach the clinics" in replies[1]


def test_an_emergency_caller_whose_area_is_not_understood_hears_the_emergency_number_every_time(client):
    replies = call(client, ["Please, my brother is not breathing.", "Somewhere near the big tree.", "It is beside the old well."])
    assert all(gives_112_first(reply) for reply in replies[1:4])
    assert "I did not recognise that place" in replies[2] and "I could not find the nearest emergency care" in replies[3]


def test_an_emergency_that_finds_no_emergency_care_near_the_caller_still_hears_the_emergency_number(client, monkeypatch):
    async def none_found(self, gw, op, args, kind=None):
        return [(spec, {"facilities": []}) for spec in self.specs(kind)]      # the providers answered, and none of them takes emergencies

    monkeypatch.setattr(HealthAdapter, "ask_all", none_found)
    replies = call(client, ["Please, my brother is not breathing, we are in Ikeja."])
    assert gives_112_first(replies[1]) and "could not find emergency care near you" in replies[1]


# ---- the simulated cancer centre ------------------------------------------------------------------------------------------------------------------------


def test_a_basic_question_is_answered_from_the_centres_own_guide(client):
    replies = call(client, ["What should I bring to my first visit at the cancer centre, please?"])
    assert "referral letter" in replies[1] and "photo ID" in replies[1]


def test_a_warning_sign_is_answered_exactly_as_the_centre_wrote_it(client):
    replies = call(client, ["Please ask the cancer centre what to do about a fever during chemotherapy."])
    assert "Contact the centre straight away" in replies[1] and "call 112" in replies[1]


def test_a_question_the_guide_does_not_cover_goes_to_the_care_team_and_not_to_a_guess(client, hdb):
    replies = call(client, ["Please ask the cancer centre about parking.", "Thank you."])
    assert "referral letter" not in replies[1]
    assert "I am sorry, the patient guide does not cover that question." in replies[1]
    assert "I have passed it to the care team at the Ikeja care centre, and when they reply you will receive a text message." in replies[1]
    assert hdb.scalar(select(HealthRequest)).status == "open" and hdb.scalar(select(Handoff)) is None


def test_a_question_that_cannot_be_passed_on_is_handed_to_the_clinic_the_usual_way(client, happ, hdb):
    happ.state.net.down.add("onc-centre")
    replies = call(client, ["Please ask the cancer centre about parking."])
    assert "I will pass the details to the clinic" in replies[1]
    assert hdb.scalar(select(Handoff)) is not None and hdb.scalar(select(HealthRequest)) is None


def test_a_booking_at_the_cancer_centre_is_remembered_and_its_text_never_names_what_is_treated(client, hdb, happ):
    replies = call(client, ["Please book an appointment at the cancer centre.", "I am in Ikeja.", TOMORROW_MORNING, YES_PLEASE])
    assert "Which day and time would you like at Oncology Care Centre Ikeja" in replies[2]
    assert "Your appointment is confirmed at Oncology Care Centre Ikeja tomorrow at 8 in the morning" in replies[4]
    text = hdb.scalar(select(Notification).where(Notification.template == "health_notice"))
    assert text.body.startswith("Your appointment at the Ikeja care centre is confirmed") and "Oncology" not in text.body and "cancer" not in text.body.lower()
    row = hdb.scalar(select(HealthAppointment))
    assert row.provider == "health_onc_centre" and row.sms_name == "the Ikeja care centre" and row.status == "booked" and row.starts_local == "2026-10-28T08:00:00"
    assert appointments(happ, "onc-centre")[0]["visit"] == "cancer care"
