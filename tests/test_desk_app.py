"""The front desk as the hospital's own app: an overview of what needs attention, the next visits and a log of what Talk did there, with a menu of sections."""

import re

from tests.support import call

BOOK = ["Please help me find the nearest clinic for antenatal care.", "I am in Surulere.", "Yes, please book the second one.", "Tomorrow morning, please.",
        "Yes, please go ahead."]
EMERGENCY = ["Please, my brother is not breathing, we are in Ikeja.", "No, I could not get through to them."]


def desk(client, slug="state-phc"):
    return client.get(f"/synthetic/{slug}/").text


def section(page, name):
    """One section of the desk, from its start to the start of the next one (a section holds smaller sections of its own)."""
    start = page.index(f'id="{name}" data-panel')
    following = page.find(" data-panel aria-labelledby", start + len(name) + 20)
    return page[start:following if following != -1 else len(page)]


def test_a_visit_talk_booked_appears_in_the_activity_and_in_the_next_visits(client):
    call(client, BOOK)
    page = desk(client)
    activity = section(page, "activity")
    assert "Visit booked" in activity and "Aguda Community Health Centre" in activity and re.search(r"APT-[A-Z0-9]{4}", activity)
    assert "Next visits" in page and "08:00" in section(page, "overview")


def test_an_emergency_place_held_needs_attention_first_and_is_counted_in_the_menu(client):
    call(client, EMERGENCY)
    page = desk(client)
    overview = section(page, "overview")
    assert overview.index("Needs attention") < overview.index("Emergency place held")
    assert re.search(r'href="#emergency" data-panel="emergency">.*?<span class="count alert">1</span>', page, re.S)
    assert "Emergency place held" in section(page, "activity") and "Emergency reported" in section(page, "activity")


def test_a_quiet_desk_says_so_in_a_few_words(client):
    page = desk(client, "everwell")
    assert "Nothing needs attention" in page and "Nothing yet" in page


def test_the_activity_never_shows_a_phone_number(client):
    call(client, BOOK)
    assert not re.search(r"\+?234\d{6,}", section(desk(client), "activity"))
