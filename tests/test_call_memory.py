"""Sofa remembers the whole call: what the caller said and what Sofa offered are kept when a question closes, so a detail given late, a "book it" after the
question has closed, or a new request later in the call starts from what is already known. A caller who answers with something else gets a second chance."""

from tests.support import call


def test_one_answer_that_is_not_a_place_does_not_end_the_request(client):
    replies = call(client, ["When is the next available slot at a clinic, please?", "I just want my daughter to see a doctor.", "I am in Surulere."])
    assert "When you call again" not in replies[2]
    assert "When you call again" not in replies[3] and "Aguda Community Health Centre" in replies[3]


def test_answers_that_are_never_a_place_end_the_request_politely(client):
    replies = call(client, ["When is the next available slot at a clinic, please?", "I just want my daughter to see a doctor.", "I am not sure.", "I do not know."])
    assert "When you call again" in replies[-1]


def test_a_place_given_in_answer_to_the_danger_question_is_kept(client):
    replies = call(client, ["My mother fell down the stairs, can you find her a clinic?", "I dey Ikorodu."])
    assert "Is someone in danger" in replies[1]
    assert "Ikorodu" in replies[2] and "which area of Lagos" not in replies[2]


def test_asking_for_the_next_available_slot_leads_to_a_booking(client):
    replies = call(client, ["My daughter has a fever. I am in Surulere. When is the next available slot?", "The first one, please.", "Yes, please book it."])
    assert "Would you like me to book it" in replies[2]
    assert "Your appointment is confirmed at Surulere Care Clinic" in replies[3]


def test_a_place_given_after_sofa_gave_up_goes_on_with_the_request(client):
    replies = call(client, ["When is the next available slot at a clinic, please?", "I just want my daughter to see a doctor.", "I am not sure.", "I do not know.",
                            "I am in Surulere."])
    assert "When you call again" in replies[4]
    assert "near Surulere" in replies[5] and "What would you like" not in replies[5]


def test_book_the_first_one_books_it_and_does_not_read_out_times(client):
    replies = call(client, ["What times are free at a clinic in Surulere?", "Okay, please book the first one."])
    assert "next free appointment times" not in replies[2] and "Surulere Care Clinic" in replies[2]


def test_a_later_request_starts_from_where_the_caller_said_they_are(client):
    replies = call(client, ["I am in Surulere. When is the next available slot at a clinic?", "The first one, please.", "Yes, please.", "Which pharmacy has paracetamol?"])
    assert "Your appointment is confirmed" in replies[3]
    assert "Everwell Pharmacy Surulere" in replies[4] and "which area" not in replies[4].lower()


def test_a_time_given_when_the_place_was_asked_is_kept(client):
    replies = call(client, ["I would like to book an appointment for antenatal care.", "Tomorrow morning.", "I am in Yaba.", "The first one, please."])
    assert "could not find" not in replies[2]
    assert "tomorrow" in replies[4].lower() and "What day and time" not in replies[4]


def test_the_model_reads_the_caller_against_what_sofa_said_and_what_the_call_is_about():
    from sofa.orchestrator import understanding

    prompt = understanding.build({"talk_said": "I can book you at Surulere Care Clinic today at 5 in the evening. Would you like me to book it for you?",
                                  "call_so_far": "request health.book_appointment; area Surulere; place offered Surulere Care Clinic"})
    assert "TALK SAID: I can book you at Surulere Care Clinic" in prompt and "CALL SO FAR: request health.book_appointment" in prompt
