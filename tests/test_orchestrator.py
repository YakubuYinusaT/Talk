"""The front desk: the number Talk answers greets like a friendly assistant, hears what the caller needs, and passes the caller to the right service."""

import asyncio

import pytest
from sqlalchemy import select

from sofa.dialogue import templates
from sofa.orchestrator.manager import CallManager
from sofa.orchestrator.understanding import Understanding
from sofa.models import Call, CallTurn, Caller, Handoff
from sofa.dialogue.outcome import new_state
from tests.support import CALLER, TALK_NUMBER, OTHER, SECRET, call

ANTENATAL = "Please help me find the nearest clinic for antenatal care."
CANCEL = "Please can you cancel my appointment for tomorrow?"
PERSON = "May I speak to a person, please?"
DAYPARTS = ("morning", "afternoon", "evening")


def phrases(key: str) -> list[str]:
    """Every wording of one of Talk's own sentences, so that a test can say which sentence was spoken without depending on how it is worded."""
    return templates.PHRASES[key]


def greeting_wordings(key: str, name: str = "") -> set[str]:
    """Every way the greeting can be said at any time of day, for a caller with the given name (or none)."""
    spoken = set()
    for part in DAYPARTS:
        daypart = templates.render(f"daypart_{part}", {})
        for variant in range(len(phrases(key))):
            spoken.add(templates.render(key, {"name": name, "greeting": daypart}, variant))
    return spoken


def understood(db) -> list[dict]:
    """What the model made of each turn of the one call in the database, taken from the trace each turn keeps."""
    turns = db.scalars(select(CallTurn).order_by(CallTurn.seq)).all()
    return [step for turn in turns for step in (turn.trace or []) if step["step"] == "understood"]


# ---- the greeting -----------------------------------------------------------------------------------------------------


def test_the_greeting_introduces_sofa_at_talk(client):
    greeting = call(client, [])[0]
    assert "Sofa" in greeting and "Talk" in greeting


def test_the_greeting_asks_how_it_can_help_and_is_a_question_the_caller_can_answer(client):
    assert call(client, [])[0].rstrip().endswith("?")


def test_the_greeting_is_one_of_the_registered_wordings_for_a_caller_it_does_not_know(client):
    assert call(client, [])[0] in greeting_wordings("greet_caller")


def test_the_greeting_varies_between_calls(client):
    greetings = {call(client, [], caller=f"+23480555500{i:02d}")[0] for i in range(12)}
    assert len(greetings) > 1


def test_a_returning_caller_is_greeted_by_name(client, hdb):
    hdb.add(Caller(phone=OTHER, name="Amina"))
    hdb.commit()
    greeting = call(client, [], caller=OTHER)[0]
    assert "Amina" in greeting and greeting in greeting_wordings("greet_caller_returning", "Amina")


def test_a_caller_whose_name_is_not_known_is_not_greeted_by_one(client, hdb):
    hdb.add(Caller(phone=OTHER, name="Amina"))
    hdb.commit()
    assert "Amina" not in call(client, [], caller=CALLER)[0]


def test_a_call_to_a_number_that_is_not_this_service_hears_that_it_is_not_in_service(client):
    answer = client.post(f"/voice/inbound/{SECRET}", data={"sessionId": "wrong-number", "callerNumber": CALLER, "destinationNumber": "+2348000000000", "isActive": "1"})
    assert templates.pick("no_service") in answer.text and "<Record" not in answer.text     # it says so and hangs up, with nothing to listen for
    assert "Sofa" not in answer.text


# ---- routing what the caller says -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("line, service", [
    (ANTENATAL, "health"),
    ("Hello, do you have amoxicillin in stock, please?", "health"),
    (CANCEL, "health"),
])
def test_a_request_is_passed_to_the_service_that_can_help(client, hdb, line, service):
    call(client, [line])
    assert hdb.scalar(select(Call)).service_domain == service
    assert [step["domain"] for step in understood(hdb)] == [service]


def test_the_trace_of_a_turn_keeps_what_was_heard_and_understood_but_never_the_phone_number(client, hdb):
    call(client, [ANTENATAL])
    turn = hdb.scalar(select(CallTurn))
    steps = [step["step"] for step in turn.trace]
    assert steps[:2] == ["heard", "understood"] and steps[-1] == "replied"
    assert CALLER not in str(turn.trace) and CALLER not in str(turn.llm_json)


# ---- speech that is not understood ----------------------------------------------------------------------------------------


def test_unclear_speech_is_asked_again_and_the_call_stays_open(client, hdb):
    replies = call(client, ["Mmm.", "Uhh.", "Hmm.", ANTENATAL])
    assert replies[1] in phrases("call_ask_again") and replies[2] in phrases("call_ask_again")
    assert replies[3] in phrases("call_give_up")
    assert replies[4] not in phrases("call_ask_again") + phrases("call_give_up")     # Talk did not hang up: the caller carried on and was helped
    assert hdb.scalar(select(Call)).service_domain == "health"
    assert hdb.scalar(select(Handoff)) is None     # no service was known, so there was nobody to pass the request to


def test_a_model_that_names_an_operation_that_does_not_exist_is_treated_as_not_understood(client, happ, hdb):
    llm = happ.state.svc.llm
    real = llm.extract

    async def inventive(model, system, transcript, alternatives=None, json_schema=None):
        if system.startswith("UNDERSTAND"):
            return Understanding(action="health.send_an_ambulance", answer="none"), {}
        return await real(model, system, transcript, alternatives, json_schema)

    llm.extract = inventive
    replies = call(client, ["Please arrange a helicopter to my house."])
    assert replies[1] in phrases("call_ask_again")
    [step] = understood(hdb)
    assert step["tool"] is None and step["domain"] == "unclear"


def test_words_the_router_cannot_place_inside_a_service_go_to_that_service_not_to_a_second_asking(client, hdb):
    replies = call(client, [CANCEL, "Aguda."])
    assert replies[2] not in phrases("call_ask_again")
    assert hdb.scalar(select(Call)).service_domain == "health"


def test_a_caller_who_is_never_understood_inside_a_service_is_handed_to_the_clinic_after_three_tries(client, hdb):
    replies = call(client, [CANCEL, "Hmm.", "Uhh.", "Mmm.", ANTENATAL])
    assert "What would you like to do?" in replies[2] and "What would you like to do?" in replies[3]       # asked again, politely, twice
    assert "the clinic" in replies[4] and "follow up" in replies[4] and "anything else" in replies[4]       # the third time the caller is passed to the clinic's staff
    handoff = hdb.scalar(select(Handoff))
    assert handoff.reason == "three_unknown_turns" and handoff.service_domain == "health"
    assert "area of Lagos" in replies[5]     # the call stayed open, and the next request was taken afresh


def test_a_service_that_understands_the_caller_again_starts_the_count_afresh(client, hdb):
    replies = call(client, [CANCEL, "Hmm.", "Uhh.", ANTENATAL, "Mmm.", "Uhh."])
    assert "What would you like to do?" in replies[2] and "What would you like to do?" in replies[3]
    assert "What would you like to do?" not in replies[4]       # the request was understood, so the three tries begin again
    assert hdb.scalar(select(Handoff)) is None


def test_a_transcript_that_could_not_be_heard_is_asked_for_again_and_a_second_failure_goes_to_the_clinic(happ, hdb):
    person = Caller(phone="+2348055550777")
    hdb.add(person)
    hdb.flush()
    row = Call(caller_id=person.id, provider_session_id="not-heard", from_number=person.phone, to_number=TALK_NUMBER)
    hdb.add(row)
    hdb.flush()
    state = new_state()
    state.update(call_id=str(row.id), domain="health")
    row.service_domain = "health"
    manager = CallManager(hdb, happ.state.svc, state, row, person)

    first = asyncio.run(manager.not_heard(""))
    assert first.text in phrases("repeat_prompt") and hdb.scalar(select(Handoff)) is None
    second = asyncio.run(manager.not_heard(""))
    assert "the clinic" in second.text and not second.end_call
    assert hdb.scalar(select(Handoff)).reason == "asr_low_confidence" and row.outcome == "handoff"


# ---- asking for a person ---------------------------------------------------------------------------------------------------


def test_asking_for_a_person_in_the_middle_of_a_service_hands_the_request_to_the_clinic(client, hdb):
    replies = call(client, [CANCEL, PERSON, ANTENATAL])
    assert "the clinic" in replies[2] and "follow up" in replies[2] and "anything else" in replies[2]
    assert "promise" not in replies[2] and "call you back" not in replies[2]     # no time is promised and no call back is offered
    assert replies[3] not in phrases("call_ask_again")     # the call stayed open and the next request started fresh
    handoff = hdb.scalar(select(Handoff))
    assert handoff.reason == "asked_for_person" and handoff.service_domain == "health"
    assert "cancel my appointment" in handoff.summary and CALLER in handoff.summary


def test_a_handed_over_request_is_recorded_on_the_call(client, hdb):
    call(client, [CANCEL, PERSON])
    row = hdb.scalar(select(Call))
    assert row.outcome == "handoff" and row.handoff_id == hdb.scalar(select(Handoff)).id


def test_asking_for_a_person_before_a_service_is_known_asks_which_service_is_needed(client, hdb):
    replies = call(client, [PERSON, ANTENATAL])
    assert replies[1] in phrases("call_no_human") and "AI assistant" in replies[1]
    assert replies[2] not in phrases("call_no_human")
    assert hdb.scalar(select(Handoff)) is None


# ---- silence ----------------------------------------------------------------------------------------------------------------


def test_silence_is_met_with_a_gentle_prompt_and_only_a_long_silence_ends_the_call(client, hdb):
    replies = call(client, ["", ""])
    assert len(replies) == 3     # an open line costs money: one "are you still there?", then goodbye
    assert replies[1] in phrases("call_still_there")
    assert replies[2] in phrases("call_goodbye_silence")
    assert hdb.scalar(select(Call)).outcome == "silence"


def test_a_caller_who_speaks_again_resets_the_silence_count(client, hdb):
    replies = call(client, ["", ANTENATAL, "", ""])
    assert len(replies) == 5
    assert replies[1] in phrases("call_still_there") and replies[2] not in phrases("call_still_there")
    assert replies[3] in phrases("call_still_there") and replies[4] in phrases("call_goodbye_silence")


# ---- greetings, thanks and goodbye -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line", ["Hello, Sofa.", "Good afternoon, Sofa.", "Thank you very much.", "Hello, how are you?"])
def test_a_greeting_or_thanks_is_answered_warmly_and_not_treated_as_not_understood(client, line):
    replies = call(client, [line])
    assert replies[1] in phrases("call_chat") and "?" in replies[1]     # it asks what they need


def test_greetings_never_add_up_to_a_failure_to_understand(client, hdb):
    replies = call(client, ["Hello.", "Hello again.", "Hi there.", "Hey, Sofa.", "Good morning.", ANTENATAL])
    assert all(reply in phrases("call_chat") for reply in replies[1:6])
    assert replies[6] not in phrases("call_chat") + phrases("call_ask_again") + phrases("call_give_up")
    assert hdb.scalar(select(Handoff)) is None and hdb.scalar(select(Call)).outcome in (None, "ended")     # never "unresolved"


def test_a_caller_who_has_nothing_more_to_ask_is_told_goodbye_and_the_call_ends(client, hdb):
    replies = call(client, [CANCEL, "No, thank you. That is all."])
    assert "anything else" in replies[1]
    assert replies[2] in phrases("call_goodbye")
    assert hdb.scalar(select(Call)).outcome == "completed"


def test_a_no_that_is_not_an_answer_to_anything_else_does_not_end_the_call(client):
    replies = call(client, ["No.", ANTENATAL])
    assert replies[1] not in phrases("call_goodbye") and replies[2] not in phrases("call_goodbye")
