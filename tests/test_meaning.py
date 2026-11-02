"""Answers that no rule expects: the model reads what the caller meant, with the question Talk asked in view, so a simple answer is understood and not asked
again. Only the caller's own words count as a day, a time or an area."""

from tests.support import call

TO_THE_TIME_QUESTION = ["I would like to book an appointment at a clinic in Yaba, please.", "I am coming from Ikorodu, actually.", "The first one, please."]


def test_asking_for_the_next_available_slot_is_an_answer_to_when(client):
    replies = call(client, [*TO_THE_TIME_QUESTION, "When is the next available slot?"])
    assert "earliest time I can find that you can reach" in replies[4] and "I can book you at Yaba Mainland Health Centre" in replies[4]
    assert "did not catch" not in replies[4]


def test_the_model_understands_an_unusual_way_of_asking_for_the_first_free_time(client, said):
    said["meaning:Honestly, I am free all week, so put me in wherever there is room."] = {"meaning": "earliest"}
    replies = call(client, [*TO_THE_TIME_QUESTION, "Honestly, I am free all week, so put me in wherever there is room."])
    assert "earliest time I can find" in replies[4] and "please plan to leave by" in replies[4]


def test_the_model_reads_a_day_from_a_roundabout_answer(client, said):
    said["meaning:My sister can bring me on Thursday, so that is best."] = {"meaning": "gave_it", "when": "on Thursday"}
    replies = call(client, [*TO_THE_TIME_QUESTION, "My sister can bring me on Thursday, so that is best."])
    assert "Thursday 29 October" in replies[4]


def test_a_day_the_caller_never_said_is_not_used(client, said):
    said["meaning:Well, I need to think about my week first."] = {"meaning": "gave_it", "when": "Friday morning"}     # the model made it up
    replies = call(client, [*TO_THE_TIME_QUESTION, "Well, I need to think about my week first."])
    assert "I can book you" not in replies[4] and "did not catch the day and time" in replies[4]


def test_a_different_request_in_place_of_a_time_is_handled_as_that_request(client, said):
    said["meaning:Actually, do you have paracetamol in stock?"] = {"meaning": "something_else"}
    replies = call(client, [*TO_THE_TIME_QUESTION, "Actually, do you have paracetamol in stock?"])
    assert "did not catch the day and time" not in replies[4] and "aracetamol" in replies[4]


def test_the_model_reads_where_the_caller_will_travel_from(client, said):
    said["meaning:My house is close to the big market in Ikorodu."] = {"meaning": "gave_it", "area": "Ikorodu"}
    replies = call(client, ["I would like to book an appointment at a clinic in Yaba, please.", "The first one, please.",
                            "My house is close to the big market in Ikorodu.", "Tomorrow at 2 in the afternoon, please."])
    assert "The trip from Ikorodu takes" in replies[4]
