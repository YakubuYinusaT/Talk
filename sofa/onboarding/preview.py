"""What Talk will be allowed to say from a hospital's information, shown before the hospital is connected.

The preview is not a mock-up. It builds the hospital in memory from the visitor's current choices, asks it with the very same operations Talk uses (search, slots, knowledge),
and puts the facts into the same sentences Talk speaks (sofa/health/speak.py and sofa/dialogue/service_phrases.py). Whatever the hospital would not be able to answer, Talk
would not say either.
"""

from datetime import datetime

from ..dialogue import templates
from ..health import knowledge, speak
from ..health.provider import Provider
from ..health.store import HospitalStore
from ..health.when import join_names, say_day, say_time
from . import hospital_profile

OUTSIDE_QUESTION = "Could you tell me whether you accept insurance, please?"    # a question that no guide is likely to cover, to show what Talk does with one


def build(profile: dict, template: str, now: datetime) -> list[dict]:
    """The sentences, each with what the caller asks and what Talk says, in the order a visitor would want to read them."""
    network = hospital_profile.network_of(profile, "preview", template)
    store = HospitalStore(":memory:", clock=lambda: now, facilities=network.facilities)
    try:
        return sentences(profile, template, now, network, Provider(network, store))
    finally:
        store.close()      # the appointment book exists only for this preview, so it is closed as soon as the sentences are written


def sentences(profile: dict, template: str, now: datetime, network, provider: Provider) -> list[dict]:
    """The same sentences, written from a provider system that the caller of this function has made and will close."""
    place = network.facilities[0]
    items: list[dict] = []

    about = provider.describe(place, now, 0.3)
    items.append({"kind": "place", "title": "When a caller asks about the hospital", "caller": "Please tell me about " + profile["name"] + ".",
                  "talk": speak.place_line(about, now), "note": "Talk reads these facts from the hospital each time. It adds nothing of its own."})

    slots = provider.slots({"facility_id": place.id, "count": 3}, {})["data"]["slots"]
    if slots:
        found = [datetime.fromisoformat(s) for s in slots]
        times = join_names([f"{say_day(s.date(), now.date())} at {say_time(s)}" for s in found], "and")
        items.append({"kind": "slots", "title": "When a caller asks for an appointment time", "caller": "What times do you have free, please?",
                      "talk": templates.render("health_slots", {"place": profile["name"], "times": times}, 0), "note": "Only times that are free in the appointment book are offered."})
    else:
        items.append({"kind": "slots", "title": "When a caller asks for an appointment time", "caller": "What times do you have free, please?",
                      "talk": templates.render("health_slots_none", {"place": profile["name"]}, 0), "note": "No day of the week is open, so no time can be offered."})

    for entry in [e for e in network.guide if e.id != knowledge.URGENT_ENTRY][:3]:
        question = hospital_profile.question_from(entry.title)
        top = provider.knowledge({"query": question, "limit": 1}, {})["data"]["entries"]
        if top and top[0]["id"] == entry.id:
            items.append({"kind": "guide", "title": f"Patient guide: {entry.title}", "caller": question, "talk": entry.answer, "note": "Talk answers from this text and from nothing else."})
        else:
            items.append({"kind": "guide", "title": f"Patient guide: {entry.title}", "caller": question, "talk": entry.answer,
                          "note": "Another entry in the guide matches this question better, so a caller who asks it this way hears that one. Words that the title and the answer share help."})

    urgent = next(e for e in network.guide if e.id == knowledge.URGENT_ENTRY)
    items.append({"kind": "warning", "title": "When a caller describes a warning sign", "caller": "Please, my sister has a very high fever and is shaking badly.",
                  "talk": urgent.answer, "note": "Warning signs are always spoken exactly as you wrote them, and never put in other words. Talk never gives any other advice about an illness."})
    items.append({"kind": "unknown", "title": "When the guide does not cover a question", "caller": OUTSIDE_QUESTION,
                  "talk": templates.render("health_question_passed", {"name": profile["name"]}, 0),
                  "note": "Talk does not guess. It files the question as a request on the hospital's front desk, and texts the caller the staff's reply."})
    return items
