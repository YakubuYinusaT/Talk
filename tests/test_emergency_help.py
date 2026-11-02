"""The emergency help: the emergency number first, where the caller is, the nearest hospital with a free emergency place by travel time, whether the caller
reached 112, and a place held when they did not. Talk never says that an ambulance was sent and never gives first aid."""

from sqlalchemy import select

from sofa.dialogue.service_phrases import PHRASES as SERVICE_PHRASES
from sofa.models import Notification
from tests.support import call

NOT_BREATHING_IN_IKEJA = "Please, my brother is not breathing, we are in Ikeja."
COLLAPSED_IN_YABA = "Please help, my father has collapsed and we are in Yaba."


def holds(happ, slug="state-phc"):
    return [dict(h) for h in happ.state.providers[slug].state.store.holds()]


def first_sentence_gives_112(reply: str) -> bool:
    return "call 112 now" in reply.split(". ")[0]


def test_a_caller_who_could_not_reach_112_has_a_place_held_at_the_nearest_hospital_with_one_free(client, happ, hdb):
    replies = call(client, [NOT_BREATHING_IN_IKEJA, "No, I could not get through to them."])
    assert first_sentence_gives_112(replies[1]) and "Were you able to reach 112?" in replies[1]
    assert "I have asked Ikeja Heights General Hospital to keep an emergency place for you" in replies[2] and "Your reference is" in replies[2]
    [held] = holds(happ)
    assert held["facility_id"] == "gh-ikeja-heights" and held["code"].startswith("EMG-")
    texts = hdb.scalars(select(Notification).where(Notification.template == "health_notice")).all()
    assert any("call 112" in t.body for t in texts) and any(held["code"] in t.body and "Obafemi Awolowo Way" in t.body for t in texts)


def test_a_caller_who_reached_112_has_no_place_held(client, happ):
    replies = call(client, [NOT_BREATHING_IN_IKEJA, "Yes, I called them and they are coming."])
    assert "I am glad you reached 112" in replies[2] and holds(happ) == []


def test_an_unclear_answer_is_taken_as_not_reached_so_the_caller_is_helped_either_way(client, happ):
    replies = call(client, [NOT_BREATHING_IN_IKEJA, "I do not know, the line keeps ringing."])
    assert "keep an emergency place" in replies[2] and len(holds(happ)) == 1


def test_a_full_hospital_is_passed_over_and_the_caller_is_told_why(client, happ):
    replies = call(client, [COLLAPSED_IN_YABA, "No, nobody is answering."])
    assert "Lagos Island Central Hospital has no free emergency place just now" in replies[1]
    assert replies[1].index("call 112 now") < replies[1].index("Lagos Island Central Hospital")      # the emergency number still comes first
    assert "Ikeja Heights General Hospital" in replies[2] and [h["facility_id"] for h in holds(happ)] == ["gh-ikeja-heights"]


def test_asking_twice_for_the_same_caller_never_takes_two_places(client, happ):
    call(client, [NOT_BREATHING_IN_IKEJA, "No, I could not get through."])
    call(client, [NOT_BREATHING_IN_IKEJA, "No, still nothing."])
    store = happ.state.providers["state-phc"].state.store
    assert len(holds(happ)) == 1 and store.places_free(store.by_id["gh-ikeja-heights"]) == 2


def test_the_hold_and_the_free_places_show_first_on_the_front_desk(client, happ):
    call(client, [NOT_BREATHING_IN_IKEJA, "No, I could not get through."])
    [held] = holds(happ)
    desk = client.get("/synthetic/state-phc/").text
    assert desk.index('id="emergency"') < desk.index('id="requests"') and f'id="hold-{held["code"]}"' in desk
    assert "Ikeja Heights General Hospital: 2 of 3 free" in desk and "Lagos Island Central Hospital: 0 of 0 free" in desk


def test_a_worry_that_might_be_an_emergency_gets_112_and_one_question(client):
    replies = call(client, ["I think my sister fainted, she is lying on the ground.", "Yes, please, she is not waking up."])
    assert replies[1] == "If this is an emergency, please call 112 now. Is someone in danger right now?"
    assert first_sentence_gives_112(replies[2]) and "Where are you, please" in replies[2]


def test_a_caller_who_says_nobody_is_in_danger_goes_on_with_what_they_asked(client):
    replies = call(client, ["My mother fell down the stairs, can you find her a clinic in Surulere?", "No, she is fine, she only hurt her ankle."])
    assert "Is someone in danger right now?" in replies[1]
    assert "Surulere" in replies[2] and "call 112" not in replies[2]


def test_the_model_recognises_an_emergency_the_keywords_do_not_know(client, said):
    words = "Something bit my leg in the bush and it is swelling up very fast, we are in Ikeja."
    said["urgency:" + words] = "emergency"
    replies = call(client, [words])
    assert first_sentence_gives_112(replies[1]) and "Ikeja Heights General Hospital" in replies[1]


def test_the_model_can_never_lower_what_the_keywords_heard(client, said):
    said["urgency:" + NOT_BREATHING_IN_IKEJA] = "none"
    replies = call(client, [NOT_BREATHING_IN_IKEJA])
    assert first_sentence_gives_112(replies[1])


def test_a_request_for_an_ambulance_is_answered_honestly(client):
    replies = call(client, ["Please send an ambulance to Surulere."])
    assert replies[1].startswith("I am sorry, I cannot send an ambulance myself. Please call 112, which can send one.")
    later = call(client, [NOT_BREATHING_IN_IKEJA, "No, I could not get through.", "Can you send an ambulance?"], "+2348055550009")
    assert "cannot send an ambulance" in later[3] and "Ikeja Heights General Hospital is keeping an emergency place for you" in later[3]


def test_no_emergency_sentence_promises_what_talk_cannot_do():
    emergency = [s for key, ss in SERVICE_PHRASES.items() if "emergency" in key or "ambulance" in key for s in ss]
    assert emergency
    for sentence in emergency:
        lowered = sentence.lower()
        assert not any(p in lowered for p in ("ambulance is on", "ambulance has been", "sent an ambulance", "dispatched", "guarantee", "will be treated", "will be seen"))


def test_a_hospital_made_in_the_wizard_keeps_the_emergency_places_it_was_given():
    from sofa.onboarding import hospital_profile

    profile = hospital_profile.new_profile(next(iter(hospital_profile.TEMPLATES)))
    profile["services"] = list({*profile["services"], hospital_profile.data.EMERGENCY})
    profile["emergency_places"] = 4
    assert hospital_profile.facility_of(profile, "demo-test").emergency_places == 4
    profile["services"] = [s for s in profile["services"] if s != hospital_profile.data.EMERGENCY]
    assert hospital_profile.facility_of(profile, "demo-test").emergency_places == 0     # no emergency department, no emergency places
