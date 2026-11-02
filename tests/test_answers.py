"""The strict yes and no safety net, the words that close a call, and the rule that only what the caller actually said can fill in a detail of the request."""

import asyncio
from types import SimpleNamespace

import pytest

from sofa.orchestrator.answers import closing, quick_answer

# ---- a plain yes or a plain no ------------------------------------------------------------------------------------


@pytest.mark.parametrize("said, answer", [
    ("Yes", "yes"), ("Yes, please.", "yes"), ("Yes, please go ahead.", "yes"), ("Okay, go ahead, please.", "yes"), ("That is right, thank you.", "yes"),
    ("Yeah, that is correct.", "yes"), ("Sure, please do it.", "yes"),
    ("No", "no"), ("No, that is wrong.", "no"), ("Nope, not that one, please.", "no"), ("No, thank you.", "no"), ("No, no, thank you.", "no"),
])
def test_a_plain_yes_or_no_is_recognised_however_politely_it_is_said(said, answer):
    assert quick_answer(said) == answer


@pytest.mark.parametrize("said", [
    "Okay, tomorrow morning, please.",                              # a yes word, but the caller is also giving the time
    "No, I would like to book in Yaba instead, please.",            # a no, but also a new request
    "Yes, and please could you also cancel my other appointment.",
    "Please book the private clinic for me.",
    "Yes, no.",                                                      # both at once, which is left to the model
    "Hello.",
    "",
])
def test_anything_more_than_a_yes_or_a_no_is_left_to_the_model(said):
    assert quick_answer(said) is None


# ---- closing the call after "is there anything else?" ------------------------------------------------------------------


@pytest.mark.parametrize("said", ["No.", "No, thank you.", "No, that is all.", "That is all, thank you.", "Nothing else, thank you.", "No, thank you, goodbye.", "Goodbye.", "Bye bye."])
def test_the_caller_closing_the_call_after_being_asked_whether_there_is_anything_else(said):
    assert closing(said, asked_more=True)


@pytest.mark.parametrize("said", ["No, please find a pharmacy in Ikeja.", "No, I would like to cancel my appointment, please.", "Yes, please book the private clinic.",
                                  "Please find me a clinic in Yaba.", ""])
def test_a_request_is_never_mistaken_for_the_caller_closing_the_call(said):
    assert not closing(said, asked_more=True)


def test_a_plain_no_closes_the_call_only_after_anything_else_was_asked_but_goodbye_always_does():
    assert not closing("No.", asked_more=False)        # A no to some other question is an answer to that question, and not a goodbye.
    assert closing("Goodbye.", asked_more=False)


# ---- only the caller's own words can fill in a detail ---------------------------------------------------------------------------


def read(happ, said, sentence, **fields):
    """What Talk takes from one sentence when the model claims to have found `fields` in it: the model is told what to return, and the health desk decides what stays."""
    said[sentence] = fields
    adapter = happ.state.svc.orchestrator.adapter("health")
    return asyncio.run(adapter.reading(SimpleNamespace(svc=happ.state.svc), sentence))


def test_a_clinic_a_time_and_a_medicine_the_caller_never_said_are_dropped(happ, said):
    got = read(happ, said, "Yes, please go ahead.", facility="Surulere Care Clinic", when="tomorrow at eight", drug="paracetamol", area="Surulere")
    assert got.facility is None and got.drug is None and got.area is None and got.when is None      # A time is only ever taken from the caller's own sentence.


def test_a_clinic_the_caller_did_say_is_kept_whatever_the_capital_letters(happ, said):
    got = read(happ, said, "Please book me at surulere care clinic.", facility="Surulere Care Clinic")
    assert got.facility == "Surulere Care Clinic"


def test_a_clinic_that_is_only_partly_made_of_the_callers_words_is_dropped(happ, said):
    got = read(happ, said, "Please book me at the care clinic in Surulere.", facility="Surulere Care Clinic and Maternity Home")
    assert got.facility is None


def test_a_need_must_be_one_of_the_fixed_choices_so_an_invented_need_is_ignored(happ, said):
    got = read(happ, said, "My baby needs her jabs, please.", need="a surgical operation")
    assert got.need != "a surgical operation"
