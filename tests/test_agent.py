"""Sofa led by the model (sofa/orchestrator/adapters/health_agent.py). The model's decisions are scripted here, so these tests check what the code does with a
decision and the guard rails it keeps whatever the model says: facts only from the providers, a booking only after a proposal and a yes, the emergency check
first, areas from the list, days and times from the caller's own words, and the rules answering when the model gives no usable decision."""

import pytest
from sqlalchemy import select

from sofa.models import HealthAppointment
from sofa.orchestrator.adapters.health_agent import Decision, HealthAgent
from tests.support import call


@pytest.fixture
def decides(happ):
    """{caller's sentence: the decision the model gives for it}. A sentence with no decision gets none, as from the stand-in model."""
    script: dict = {}
    llm = happ.state.svc.llm
    real = llm.extract

    async def extract(model, system, transcript, alternatives=None, json_schema=None):
        if system.startswith("AGENT"):
            script.setdefault("_prompts", []).append(system)
            return Decision(**script.get(transcript, {})), {}
        return await real(model, system, transcript, alternatives, json_schema)

    llm.extract = extract
    return script


def booked(happ):
    with happ.state.svc.session_factory() as db:
        return db.scalars(select(HealthAppointment)).all()


def test_a_travel_question_after_a_medicine_answer_gets_the_nearest_pharmacy_and_the_trip(client, decides):
    decides["Where can I get paracetamol?"] = {"action": "reply", "urgency": "none", "reply": "Which area are you in, please?", "medicines": ["Paracetamol 500 milligram tablets"]}
    decides["I am at Palmgrove, how long will it take me to get there?"] = {"action": "medicine", "urgency": "none", "medicines": ["Paracetamol 500 milligram tablets"], "caller_area": "Maryland"}
    replies = call(client, ["Where can I get paracetamol?", "I am at Palmgrove, how long will it take me to get there?"])
    assert replies[1] == "Which area are you in, please?"
    assert "Paracetamol" in replies[2] and "From Maryland," in replies[2] and "away by road" in replies[2]


def test_a_booking_is_made_only_after_a_proposal_and_a_yes(client, happ, decides):
    decides["I am in Surulere, book me the earliest time at Surulere Care Clinic."] = {"action": "confirm_booking", "urgency": "none", "caller_area": "Surulere",
                                                                                      "place": "Surulere Care Clinic", "when": "earliest"}
    decides["Yes, please."] = {"action": "confirm_booking", "urgency": "none"}
    replies = call(client, ["I am in Surulere, book me the earliest time at Surulere Care Clinic.", "Yes, please."])
    assert "Would you like me to book it" in replies[1]       # the model jumped to confirming: Sofa proposes a time first, and nothing is booked yet
    assert "Your appointment is confirmed at Surulere Care Clinic" in replies[2]
    assert len(booked(happ)) == 1


def test_a_reply_that_brings_in_a_fact_not_said_in_the_call_is_not_spoken(client, decides):
    decides["How much does Surulere Care Clinic charge?"] = {"action": "reply", "urgency": "none", "reply": "Surulere Care Clinic charges 2,500 naira."}
    replies = call(client, ["How much does Surulere Care Clinic charge?"])
    assert "2,500" not in replies[1]


def test_the_model_can_raise_the_urgency_to_an_emergency(client, decides):
    decides["My father is on the floor and his lips are blue, we are in Ikeja."] = {"action": "reply", "urgency": "emergency", "reply": "Okay."}
    replies = call(client, ["My father is on the floor and his lips are blue, we are in Ikeja."])
    assert replies[1].startswith("Please call 112")


def test_the_emergency_words_are_answered_before_the_model_is_asked(client, decides):
    decides["Please help, my brother is not breathing, we are in Ikeja."] = {"action": "reply", "urgency": "none", "reply": "Okay, how can I help?"}
    replies = call(client, ["Please help, my brother is not breathing, we are in Ikeja."])
    assert replies[1].startswith("Please call 112")
    assert not decides.get("_prompts")


def test_a_day_the_caller_never_said_is_not_used(client, happ, decides):
    decides["Book me at Surulere Care Clinic, I am in Surulere."] = {"action": "offer_booking", "urgency": "none", "caller_area": "Surulere",
                                                                    "place": "Surulere Care Clinic", "when": "next Friday afternoon"}
    replies = call(client, ["Book me at Surulere Care Clinic, I am in Surulere."])
    assert "Friday" not in replies[1] and "Which day and time" in replies[1]


def test_an_area_outside_the_list_is_not_used(client, decides):
    decides["Which pharmacy has paracetamol? I am at Palmgrove."] = {"action": "medicine", "urgency": "none", "medicines": ["Paracetamol 500 milligram tablets"], "caller_area": "Palmgrove"}
    replies = call(client, ["Which pharmacy has paracetamol? I am at Palmgrove."])
    assert "Palmgrove" not in replies[1] and "Paracetamol" in replies[1]


def test_with_no_usable_decision_the_rules_answer(client, decides):
    replies = call(client, ["Which pharmacy in Surulere has paracetamol?"])
    assert "Everwell Pharmacy Surulere" in replies[1]


def test_the_model_sees_the_whole_call_both_sides(client, decides):
    decides["Where can I get paracetamol?"] = {"action": "reply", "urgency": "none", "reply": "Which area are you in, please?"}
    decides["Surulere."] = {"action": "medicine", "urgency": "none", "medicines": ["Paracetamol 500 milligram tablets"], "caller_area": "Surulere"}
    call(client, ["Where can I get paracetamol?", "Surulere."])
    last = decides["_prompts"][-1]
    assert "CALLER: Where can I get paracetamol?" in last and "SOFA: Which area are you in, please?" in last


def test_a_question_about_a_proposal_leaves_it_open(client, happ, decides):
    lines = ["I am in Surulere and I want to see a doctor.", "The first one, at the earliest time.", "How much is the fee there?", "Okay, book it."]
    decides[lines[0]] = {"action": "find_places", "urgency": "none", "kind": "clinic", "caller_area": "Surulere"}
    decides[lines[1]] = {"action": "offer_booking", "urgency": "none", "caller_area": "Surulere", "place": "1", "when": "earliest"}
    decides[lines[2]] = {"action": "reply", "urgency": "none", "reply": "The consultation fee at Surulere Care Clinic is 8,000 naira. Shall I book it?"}
    decides[lines[3]] = {"action": "confirm_booking", "urgency": "none"}
    replies = call(client, lines)
    assert "consultation fee of 8,000 naira" in replies[1] and "Would you like me to book it" in replies[2]
    assert replies[3] == "The consultation fee at Surulere Care Clinic is 8,000 naira. Shall I book it?"
    assert "Your appointment is confirmed at Surulere Care Clinic" in replies[4] and len(booked(happ)) == 1


def test_a_medicine_is_reserved_only_after_the_caller_agrees_and_an_account_is_given(client, happ, decides):
    lines = ["I need ibuprofen, I am in Yaba.", "Please reserve it for me.", "Yes, please."]
    decides[lines[0]] = {"action": "medicine", "urgency": "none", "medicines": ["Ibuprofen 400 milligram tablets"], "caller_area": "Yaba"}
    decides[lines[1]] = {"action": "reserve_medicine", "urgency": "none", "medicines": ["Ibuprofen 400 milligram tablets"], "caller_area": "Yaba"}
    decides[lines[2]] = {"action": "confirm_booking", "urgency": "none"}
    replies = call(client, lines)
    assert "Shall I reserve it for you?" in replies[2] and "650 naira" in replies[2]
    assert "set aside for you at Everwell Pharmacy Yaba" in replies[3] and "The total is 650 naira" in replies[3] and "account number" in replies[3]
    desk = client.get("/synthetic/everwell/").text
    assert "Ibuprofen 400 milligram tablets" in desk and "Awaiting payment" in desk and 'id="orders"' in desk


def test_a_kind_of_medicine_lists_the_products_that_fit(client, decides):
    line = "I need a pain reliever, I am in Yaba."
    decides[line] = {"action": "medicine", "urgency": "none", "caller_area": "Yaba",
                     "medicines": ["Paracetamol 500 milligram tablets", "Ibuprofen 400 milligram tablets"]}
    reply = call(client, [line])[1]
    assert "Paracetamol 500 milligram tablets at about 400 naira" in reply and "Ibuprofen 400 milligram tablets at about 650 naira" in reply
    assert "A pharmacist there can tell you which one suits you." in reply
