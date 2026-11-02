"""Location first, then travel time: Talk finds out where the caller is before it says how long the trip takes, allows for Lagos traffic at that hour, and never
offers a visit the caller cannot reach in time."""

from datetime import datetime, timedelta

from sofa.health import data, gazetteer, travel
from tests.support import call

FACILITIES = {f.id: f for f in data.FACILITIES}
TUESDAY_MORNING = datetime(2026, 10, 27, 10, 15)


def trip(origin: str, facility_id: str, when: datetime) -> travel.Trip:
    f = FACILITIES[facility_id]
    return travel.trip(origin, f.lat, f.lon, f.area, when)


# ---- the estimate --------------------------------------------------------------------------------------------------


def test_the_same_trip_takes_longer_in_the_morning_rush_than_in_the_night():
    rush = trip("Surulere", "gh-ikeja-heights", datetime(2026, 10, 27, 8, 0))
    night = trip("Surulere", "gh-ikeja-heights", datetime(2026, 10, 27, 3, 0))
    assert rush.middle > night.middle * 1.8


def test_friday_evening_is_slower_than_sunday_morning():
    friday = trip("Yaba", "gh-island-central", datetime(2026, 10, 30, 17, 0))
    sunday = trip("Yaba", "gh-island-central", datetime(2026, 11, 1, 9, 0))
    assert friday.middle > sunday.middle


def test_a_long_trip_across_the_lagoon_is_spoken_as_a_range_and_a_short_one_as_one_figure():
    assert travel.say_span(trip("Surulere", "hc-aguda", TUESDAY_MORNING)) == "about 10 minutes"
    assert travel.say_span(trip("Ajah", "gh-island-central", TUESDAY_MORNING)) == "an hour and a quarter to an hour and 45 minutes"


def test_an_area_talk_does_not_know_gives_no_trip():
    f = FACILITIES["hc-aguda"]
    assert travel.trip("Atlantis", f.lat, f.lon, f.area, TUESDAY_MORNING) is None


def test_the_leaving_time_allows_for_the_slow_end_of_the_trip_and_arriving_early():
    f = FACILITIES["cl-ikeja-allen"]
    slot = datetime(2026, 10, 28, 8, 0)
    depart, found, reachable = travel.leave_by("Ikorodu", f.lat, f.lon, f.area, slot, TUESDAY_MORNING)
    assert reachable and depart <= slot - timedelta(minutes=travel.EARLY + round(found.high))


def test_a_visit_too_soon_to_reach_is_marked_as_unreachable():
    f = next(x for x in data.FACILITIES if x.area == "Yaba")
    _, _, reachable = travel.leave_by("Ikorodu", f.lat, f.lon, f.area, datetime(2026, 10, 27, 11, 0), TUESDAY_MORNING)
    assert not reachable


# ---- where the caller is -------------------------------------------------------------------------------------------


def test_the_caller_saying_where_they_are_is_their_location():
    assert gazetteer.caller_location("I am in Surulere.").name == "Surulere"
    assert gazetteer.caller_location("I will be coming from Ikorodu, please.").name == "Ikorodu"
    assert gazetteer.caller_location("We live near Yaba.").name == "Yaba"


def test_an_area_inside_a_request_or_a_place_name_is_not_where_the_caller_is():
    assert gazetteer.caller_location("Please find me a clinic in Yaba.") is None
    assert gazetteer.caller_location("I would like to book at Ikeja Allen Medical Centre.") is None
    assert gazetteer.caller_location("I am not bleeding, I just want a check-up in Surulere, please.") is None     # "I am" is not about the place


# ---- in a conversation ---------------------------------------------------------------------------------------------


def test_no_distance_is_spoken_until_the_caller_has_said_where_they_are(client):
    replies = call(client, ["I would like to book an appointment at a clinic in Yaba, please."])
    assert "kilometre" not in replies[1] and "away by road" not in replies[1]


def test_talk_asks_where_the_caller_will_travel_from_before_it_offers_a_time(client):
    replies = call(client, ["I would like to book an appointment at a clinic in Yaba, please.", "The first one, please."])
    assert "Will you be travelling to Yaba Mainland Health Centre from Yaba, or from another area" in replies[2] and "when to leave" in replies[2]


def test_the_offer_says_how_long_the_trip_takes_and_when_to_leave(client):
    replies = call(client, ["Please help me find the nearest clinic for antenatal care.", "I am in Surulere.", "Yes, please book the private clinic.",
                            "Tomorrow morning, please."])
    assert "away by road with the usual traffic" in replies[2]
    assert "The trip from Surulere takes" in replies[4] and "please plan to leave by" in replies[4]


def test_a_caller_who_says_where_they_are_while_choosing_hears_the_same_places_with_the_trip(client):
    replies = call(client, ["I would like to book an appointment at a clinic in Yaba, please.", "I am coming from Ikorodu, actually."])
    assert replies[2].startswith("Thank you. Here are the same places with the trip from Ikorodu.") and "away by road" in replies[2]


def test_a_time_the_caller_cannot_reach_is_never_offered(client):
    replies = call(client, ["I would like to book an appointment at a clinic in Yaba, please.", "I am coming from Ikorodu, actually.", "The first one, please.",
                            "Today at 11 in the morning, please."])
    assert "today at 11 in the morning" not in replies[4]
    assert "please plan to leave by" in replies[4]
