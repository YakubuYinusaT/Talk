"""The health front desk: Talk coordinating several independent provider systems for one caller.

A caller says what they need. Talk works out the need and the place (the model reads the words, and what it is given must be made of them), asks every
provider system that could help, puts the real options in front of the caller with the things that decide between them (distance, waiting time, fee), and
asks which one they mean: an area is not a hospital, so Talk never picks for them. Only then does it ask a provider for slots and book. Every provider stays
the source of truth for its own records; Talk keeps the conversation, and says only what a provider confirmed.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import select

from ...dialogue import templates
from ...dialogue.outcome import Outcome
from ...health import floor, gazetteer, scope, speak, travel
from ...health.data import AREAS
from ...health.when import answer_of, hesitates, join_names, wants_earliest, lagos_now, parse_when, said_nothing_about_time, say_day, say_on_day, say_time, when_in_words
from ...health.links import ProviderError, Unavailable
from ..tools import Tool
from . import ServiceAdapter
from .guide import spoken_answer

log = logging.getLogger("sofa.health")
DOMAIN = "health"
PENDING = "health"                     # the orchestrator routes every pending question of this kind back here
MAX_OPTIONS, MAX_TRIES = 3, 2
ORDINALS = {"first": 0, "1st": 0, "1": 0, "second": 1, "2nd": 1, "2": 1, "third": 2, "3rd": 2, "3": 2}   # not "one": "the private one" is not the first
ORDINAL_WORDS = ("first", "second", "third")
KIND_WORDS = {"private": "private", "state": "state", "government": "state", "public": "state", "pharmacy": "pharmacy"}
PLACE_WORDS = {"clinic", "hospital", "centre", "center", "health", "community", "medical", "general", "pharmacy"}
# words around a place or an area that are only politeness or phrasing, so that "I am in Yaba, please" names an area and nothing else
POLITE_WORDS = {"in", "at", "the", "near", "around", "a", "an", "my", "i", "am", "please", "kindly", "hello", "thanks", "thank", "you", "is", "its", "it", "me", "to", "for"}
YES_OPENERS = ("yes", "yeah", "yep", "yup", "ok", "okay", "sure", "correct")

TOOLS = (
    ("health.find_facility", "Find the nearest clinic, hospital or pharmacy for a need such as antenatal care, with its opening hours, how long the wait is and what it costs"),
    ("health.facility_status", "How busy a named clinic or hospital is right now, and when it is open"),
    ("health.available_slots", "The free appointment times at a named clinic or hospital"),
    ("health.book_appointment", "Book an appointment at a clinic or hospital"),
    ("health.cancel_appointment", "Cancel the caller's own appointment"),
    ("health.drug_availability", "Which pharmacies have a medicine in stock, and what it costs"),
    ("health.ask_the_centre", "Answer a basic question about cancer care or the cancer centre, such as what to bring, how appointments and treatment days work, or who to call, from the centre's own patient guide"),
)
# the phrase (sofa/dialogue/service_phrases.py) that asks for what each request still lacks; a second try uses the phrase with "_again" after its name
QUESTIONS = {
    "health.find_facility": "health_ask_area",
    "health.facility_status": "health_ask_place",
    "health.available_slots": "health_ask_place",
    "health.book_appointment": "health_ask_clinic",
    "health.drug_availability": "health_ask_drug",
}
GIVE_UP = {"health.find_facility": "health_giveup_area", "health.drug_availability": "health_giveup_drug"}
GIVE_UP_PLACE = "health_giveup_place"


@dataclass
class Request:
    """What the caller asked for, in the shape providers need. Every field is optional: whatever was not said stays empty and is asked for."""
    need: str | None = None
    area: str | None = None       # a canonical area name
    facility: str | None = None   # a place's name, as said
    when: str | None = None       # a day and time, as said
    drug: str | None = None
    red_flag: bool = False
    origin: str | None = None  # the area the caller is in or will travel from, only when they said so: every travel time starts here
    from_asked: bool = False   # Talk has asked where the caller will travel from, once
    tries: int = 0                # how many times the same question has been asked
    utterance: str = ""

    def pack(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "", False, 0)}

    @staticmethod
    def unpack(data: dict) -> "Request":
        return Request(**{k: v for k, v in (data or {}).items() if k in Request.__dataclass_fields__})


class Reading(BaseModel):
    need: str | None = None
    area: str | None = None
    facility: str | None = None
    when: str | None = None
    drug: str | None = None


class PickedOption(BaseModel):
    choice: str | None = None


class Meaning(BaseModel):
    """What the caller meant by an answer to the question Talk had just asked."""
    meaning: str = "unclear"
    when: str | None = None
    area: str | None = None


MEANINGS = ["gave_it", "earliest", "yes", "no", "something_else", "unclear"]


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def summarise(op: str, data: dict) -> str:
    """What a provider's answer amounted to, in a few words for the trace (counts and kinds, never a name, a number or a caller id)."""

    def count(items, one: str, many: str) -> str:
        return f"{len(items)} {one if len(items) == 1 else many}"

    if not data.get("ok", True):
        return "refused"
    if op == "search":
        return count(data.get("facilities", []), "place", "places")
    if op == "slots":
        return count(data.get("slots", []), "free time", "free times")
    if op == "stock":
        return count(data.get("pharmacies", []), "pharmacy with it", "pharmacies with it") if data.get("drug") else "medicine not recognised"
    if op == "knowledge":
        return "an answer from the guide" if data.get("entries") else "nothing in the guide"
    if op == "upcoming":
        return count(data.get("appointments", []), "appointment", "appointments")
    if op == "book":
        return "booked"
    if op == "cancel":
        return "cancelled"
    if op == "request":
        return "request filed" if data.get("request") else "request not filed"
    if op == "request_status":
        return (data.get("request") or {}).get("status", "no such request")
    if op == "visit_status":
        return data.get("status", "not marked")
    return "answered"


class HealthAdapter(ServiceAdapter):
    domain = DOMAIN

    def __init__(self):
        self.providers: list = []     # the provider systems behind the front desk, set at start-up
        self.demo = None              # the hospitals visitors made in the onboarding wizard (sofa/onboarding), each shown only to the visitor who made it

    def set_providers(self, specs: list) -> bool:
        changed = list(specs) != self.providers
        self.providers = list(specs)
        return changed

    def now(self) -> datetime:
        return lagos_now()

    def tools(self) -> list[Tool]:
        return [Tool(tool_id, DOMAIN, description, "informational") for tool_id, description in TOOLS]

    def holds_session(self, st: dict) -> bool:
        return st.get("domain") == DOMAIN

    # ---- asking the providers ------------------------------------------------------------------------

    def visible(self) -> list:
        """The providers this caller may be told about: the four simulated systems, and the hospital this caller made in the onboarding wizard, if they made one."""
        if not self.demo:
            return self.providers
        who = scope.current()
        return [*self.providers, *self.demo.specs_for(who.visitor, who.phone)]

    def specs(self, kind: str | None = None) -> list:
        return [s for s in self.visible() if kind is None or s.setting("kind") == kind]

    def spec_of(self, place: dict):
        return next((s for s in self.visible() if s.domain == place["d"]), None)

    def find_spec(self, domain: str):
        """A provider by its service domain, whoever it is shown to. The scheduler uses this to follow up a visit after the call that booked it has ended."""
        return next((s for s in self.providers if s.domain == domain), None) or (self.demo.spec_of(domain) if self.demo else None)

    def has_providers(self) -> bool:
        return bool(self.providers) or bool(self.demo and self.demo.any_live())

    async def provider_call(self, gw, spec, op: str, args: dict) -> dict | None:
        """One provider, one operation. The provider's facts, or None when it could not be reached (the caller never loses the call over it)."""
        tool = spec.tool(f"{spec.domain}.{op}") if spec else None
        if not tool:
            return None
        ctx = {"phone": gw.person.phone, "name": gw.person.name, "call_id": str(gw.call.id) if gw.call and gw.call.id else None}
        started = time.perf_counter()
        try:
            result = await gw.svc.provider_links.call(gw.db, spec, tool, args, ctx)
        except (ProviderError, Unavailable) as exc:
            log.warning("provider %s could not be asked %s: %s", spec.domain, op, exc)
            self.note(gw, "asked", provider=spec.label, op=op, ms=int((time.perf_counter() - started) * 1000), ok=False, summary="could not be reached")
            return None
        finally:
            gw.db.commit()  # the call's record is saved at once: a database lock must not be held while the next slow step runs
        data = {**result.data, "ok": result.ok}
        self.note(gw, "asked", provider=spec.label, op=op, ms=int((time.perf_counter() - started) * 1000), ok=result.ok, summary=summarise(op, data))
        return data

    @staticmethod
    def words(gw, key: str, **facts) -> str:
        """One of the front desk's own sentences, taken from the phrase list (sofa/dialogue/service_phrases.py) so that all of Talk's wording is in one place."""
        return templates.render(key, {"number": gazetteer.EMERGENCY_NUMBER, **facts}, (getattr(gw, "st", None) or {}).get("turn", 0))

    @staticmethod
    def note(gw, step: str, **data) -> None:
        """Add a step to the turn's trace. A follow-up pass has no turn to trace, so it has nothing to add to."""
        note = getattr(gw, "note", None)
        if note:
            note(step, **data)

    async def file_request(self, gw, spec, kind: str, summary: str, *, urgent: bool = False, name: str = "", sms_name: str = "") -> dict | None:
        """Pass something to a provider's staff, so a person sees it on that provider's own front desk and can answer it. The provider gets what the caller said and a
        reference, never the phone number. The call never fails over it: None when it could not be filed."""
        from ...models import HealthRequest

        try:
            answer = await self.provider_call(gw, spec, "request", {"kind": kind, "summary": summary[:300], "urgent": urgent})
            filed = (answer or {}).get("request")
            if not filed:
                return None
            gw.db.add(HealthRequest(caller_id=gw.person.id, provider=spec.domain, code=filed["code"], kind=kind, urgent=urgent,
                                    facility_name=name or spec.label, sms_name=sms_name or name or spec.label))
            gw.db.commit()
            self.note(gw, "request", provider=spec.label, code=filed["code"], kind=kind, urgent=urgent)
            if urgent:
                await self.alert_staff(gw, name or spec.label, filed["code"])
            return filed
        except Exception:
            log.exception("a request for the care team could not be filed")
            return None

    async def alert_staff(self, gw, place: str, code: str) -> None:
        """An urgent request is also texted to the staff number in the settings, if there is one."""
        from ...services.notify import send_sms

        phone = (gw.svc.settings.hospital_staff_phone or "").strip()
        if phone:
            await send_sms(gw.db, gw.svc, to=phone, body=self.words(gw, "health_sms_staff", code=code, place=place), template="health_staff_alert")
            gw.db.commit()

    async def ask_all(self, gw, op: str, args: dict, kind: str | None = None) -> list[tuple[object, dict]]:
        specs = self.specs(kind)
        answers = await asyncio.gather(*(self.provider_call(gw, s, op, args) for s in specs))
        return [(s, a) for s, a in zip(specs, answers) if a is not None]

    async def places(self, gw, req: Request, *, kind: str | None, bookable: bool = False, query: str | None = None, limit: int = 4,
                     origin: str | None = None) -> tuple[list[dict], bool]:
        """Places from every provider that fits, open and nearest first. The flag is False when no provider could be reached at all."""
        args = {"limit": limit, **({"need": req.need} if req.need else {}), **({"query": query} if query else {}), **({"bookable": True} if bookable else {})}
        if req.area:
            args.update(lat=AREAS[req.area].lat, lon=AREAS[req.area].lon)
        answered = await self.ask_all(gw, "search", args, kind)
        found = [{**f, "d": spec.domain} for spec, a in answered for f in a.get("facilities", [])]
        if query and found:     # each provider names its own best match: only the best across all of them is what the caller meant
            best = max(f.get("match", 0) for f in found)
            found = [f for f in found if f.get("match", 0) >= best - 0.01]
        self.with_travel(gw, found, origin or req.origin)
        found.sort(key=lambda f: (not (f["open_now"] or f["all_day"] or (req.need == "emergency care" and f["emergency"])), self.how_far(f), f["wait_minutes"]))
        return found[:limit], bool(answered)    # every provider answers with up to `limit` places, so the best few across all of them are kept

    def with_travel(self, gw, found: list[dict], area: str | None) -> None:
        """Adds the trip from where the caller is to every place, with the usual traffic at this hour. Nothing is added until the caller has said where they are."""
        if not area:
            return
        now, spans = self.now(), []
        for f in found:
            t = travel.trip(area, f.get("lat"), f.get("lon"), f.get("area"), now)
            if t is not None:
                f["eta"], f["travel"] = round(t.middle), travel.away_phrase(t)
                spans.append(f"{f['name']}: {travel.say_span(t)}")
        if spans:
            self.note(gw, "travel", origin=area, hour=now.strftime("%H:%M"), trips="; ".join(spans[:4]))

    @staticmethod
    def how_far(f: dict) -> float:
        """What orders places for a caller: minutes on the road when they are known, otherwise kilometres counted as three minutes each."""
        if f.get("eta") is not None:
            return f["eta"]
        return f["km"] * 3 if f.get("km") is not None else 999

    async def fetch_place(self, gw, req: Request, place: dict) -> dict | None:
        """The full, current facts about one place a caller chose, from the provider that runs it."""
        args = {"ids": [place["id"]], "limit": 1, **({"lat": AREAS[req.area].lat, "lon": AREAS[req.area].lon} if req.area else {})}
        answer = await self.provider_call(gw, self.spec_of(place), "search", args)
        found = (answer or {}).get("facilities", [])
        self.with_travel(gw, found, req.origin)
        return found[0] if found else None

    # ---- reading the caller's words ------------------------------------------------------------------

    async def read(self, gw, text: str) -> Request:
        """What the caller asked for, read from their words (see `reading`). What was understood is noted in the turn's trace, never the sentence itself."""
        req = await self.reading(gw, text)
        now = self.now()
        self.note(gw, "read", need=req.need, area=req.area, when=when_in_words(parse_when(req.when or "", now), now.date()), drug=req.drug, place=req.facility)
        return req

    async def reading(self, gw, text: str) -> Request:
        """Rules first, then the model by meaning ("my baby needs jabs" is child immunisation). A place, a time or a medicine only counts if it is made of the
        caller's own words; the need is one of a fixed list. The model never supplies a fact."""
        found = parse_when(text, self.now())
        area = gazetteer.match_area(text)
        req = Request(need=gazetteer.detect_need(text), area=area.name if area else None, when=text if not said_nothing_about_time(found) else None,
                      drug=gazetteer.match_drug(text), red_flag=floor.read(text).level == floor.EMERGENCY, utterance=text[:300])
        schema = {"type": "object", "additionalProperties": False, "required": list(Reading.model_fields),
                  "properties": {"need": {"anyOf": [{"type": "string", "enum": gazetteer.NEED_CHOICES}, {"type": "null"}], "description": "what the caller needs care for"},
                                 **{n: {"anyOf": [{"type": "string"}, {"type": "null"}], "description": d} for n, d in (
                                     ("area", "the part of Lagos the caller is in or means"), ("facility", "the name of a clinic, hospital or pharmacy the caller named"),
                                     ("when", "the day and time the caller asked for"), ("drug", "the medicine the caller named"))}}}
        system = ("ARGUMENTS\nA caller to a health line in Lagos said the words below. Fill in each field only if the caller actually said it, in the caller's own words; "
                  "null for anything not said. Do not guess, do not work out dates, do not add words. For need, pick the one that fits what they describe, or null.")
        try:
            got, _raw = await gw.svc.llm.extract(Reading, system, text, json_schema=schema)
        except Exception as exc:  # the model not answering costs the caller nothing: the rules above and the questions below carry on
            log.warning("health request not read by the model: %s", exc)
            return req
        said = set(tokens(text))

        def grounded(value) -> str | None:
            return value.strip() if isinstance(value, str) and value.strip() and len(value) <= 120 and set(tokens(value)) <= said else None

        if got.need in gazetteer.NEED_CHOICES:
            req.need = got.need
        named = gazetteer.match_area(grounded(got.area) or "")
        req.area = named.name if named else req.area
        here = gazetteer.caller_location(text)
        req.origin = here.name if here else req.origin
        req.facility = grounded(got.facility) or req.facility
        req.when = grounded(got.when) or req.when
        req.drug = grounded(got.drug) or req.drug
        return req

    # ---- entry ----------------------------------------------------------------------------------------

    async def turn(self, gw, transcript: str, confidence: float) -> Outcome:
        u = await gw.understand(transcript)
        started, gw._health_read = getattr(gw, "_health_read", None), None
        req = await started if started is not None else await self.read(gw, transcript)    # already running since the turn began, when the orchestrator could start it
        if req.need == "emergency care":    # the model read an emergency by meaning
            return await self.emergency(gw, transcript)
        tool_id = self.tool_of(u, req)
        if not tool_id:
            out = gw.ask("health_ask_what", {"kind": PENDING, "step": "what", "req": req.pack()}, action="health_ask_what", service="health services")
            out.extra["not_understood"] = True    # the orchestrator counts these, so that a caller who is never understood is handed to the clinic's staff and not asked again for ever
            return out
        return await self.start(gw, tool_id, req)

    @staticmethod
    def tool_of(u, req: Request) -> str | None:
        """The request the caller made: the tool the model named or, when it named none, the medicine the caller's own words named ("Amoxicillin capsules, please")."""
        if u.tool in dict(TOOLS):
            return u.tool
        return "health.drug_availability" if req.drug else None

    async def start(self, gw, tool_id: str, req: Request) -> Outcome:
        gw.st["domain"] = gw.call.service_domain = DOMAIN
        gw.raw_json = {"health": tool_id, "request": req.pack()}
        if not self.specs():
            if self.emergency_of(req):    # even with nothing to ask, a caller in an emergency is told the emergency number first
                return self.say(gw, self.words(gw, "health_emergency_unreachable"), "health_emergency_unreachable")
            return gw.reply("health_unavailable", action="health_unavailable", service="health services")
        handlers = {"health.find_facility": self.find, "health.facility_status": self.status, "health.available_slots": self.slots, "health.book_appointment": self.book,
                    "health.cancel_appointment": self.cancel, "health.drug_availability": self.drug, "health.ask_the_centre": self.ask_centre}
        return await handlers[tool_id](gw, req)

    def ask(self, gw, step: str, tool_id: str, req: Request, question: str, **state) -> Outcome:
        return gw.ask("health_say", {"kind": PENDING, "step": step, "tool": tool_id, "req": req.pack(), "tries": req.tries, "question": question[-300:], **state},
                      action=f"health_ask_{step}", answer=question)

    @staticmethod
    def emergency_of(req: Request) -> bool:
        return req.need == "emergency care" or req.red_flag

    def ask_where(self, gw, tool_id: str, req: Request) -> Outcome:
        """The place, area or medicine is still missing. Asked once more at most: after that the caller is told how to try again. A caller in an emergency hears the
        emergency number with every one of these sentences, because the next one might be the last thing they hear."""
        emergency = tool_id == "health.find_facility" and self.emergency_of(req)
        if req.tries >= MAX_TRIES:
            return self.say(gw, self.words(gw, "health_giveup_emergency" if emergency else GIVE_UP.get(tool_id, GIVE_UP_PLACE)), "health_where_dropped")
        key = ("health_ask_emergency_area" if emergency else QUESTIONS[tool_id]) + ("_again" if req.tries else "")
        return self.ask(gw, "where", tool_id, req, self.words(gw, key))

    def say(self, gw, text: str, action: str) -> Outcome:
        gw.st["pending"] = None
        return gw.reply("health_answer", action=action, answer=text)

    def nothing_reachable(self, gw, req: Request | None = None) -> Outcome:
        """No provider answered. A caller in an emergency is still told, first, to call the emergency number, and is told plainly that the clinics could not be reached."""
        if req is not None and self.emergency_of(req):
            return self.say(gw, self.words(gw, "health_emergency_unreachable"), "health_emergency_unreachable")
        return gw.reply("health_unavailable", action="health_unreachable", service="the clinics' systems")

    # ---- emergencies ---------------------------------------------------------------------------------------

    def ambulance(self, gw, transcript: str) -> Outcome:
        """Talk cannot send an ambulance. It says so, gives the emergency number, which can, and repeats a place already held for the caller."""
        held = gw.st.get("emergency_hold")
        if held:
            return self.say(gw, self.words(gw, "health_ambulance_held", name=held["n"], address=held["a"]), "health_ambulance")
        return self.ask(gw, "emergency_check", "health.emergency", Request(utterance=transcript[:300]), self.words(gw, "health_ambulance"), said=transcript[:300])

    def danger_check(self, gw, transcript: str) -> Outcome:
        """It might be an emergency. The emergency number comes first, then one question, and nothing is asked of any hospital yet."""
        return self.ask(gw, "emergency_check", "health.emergency", Request(utterance=transcript[:300]), self.words(gw, "health_emergency_possible"), said=transcript[:300])

    async def emergency(self, gw, transcript: str, area: str | None = None) -> Outcome:
        """Someone may be in danger now. The emergency number first, at once and by text as well, then where the caller is, then the nearest hospital that has
        an emergency place free. In an emergency any place the caller names is taken as where they are."""
        gw.st["domain"] = gw.call.service_domain = DOMAIN
        req = Request(need="emergency care", red_flag=True, utterance=transcript[:300])
        if not gw.st.get("emergency_texted"):
            gw.st["emergency_texted"] = await self.text_caller(gw, self.words(gw, "health_sms_emergency_number"))
        if not self.specs("clinics"):
            return self.say(gw, self.words(gw, "health_emergency_unreachable"), "health_emergency_unreachable")
        here = gazetteer.match_area(area or "") or gazetteer.match_area(transcript)
        if not here:
            return self.ask(gw, "emergency_where", "health.emergency", req, self.words(gw, "health_emergency_ask_where"), said=transcript[:300])
        return await self.emergency_route(gw, req, here.name, transcript)

    async def emergency_route(self, gw, req: Request, area: str, said: str) -> Outcome:
        """Asks every hospital how many emergency places are free, orders those that have one by the trip from the caller, tells the nearest one about the
        caller on its front desk, and asks whether the caller reached the emergency number."""
        req.origin = req.area = area
        answered = await self.ask_all(gw, "emergency", {"lat": AREAS[area].lat, "lon": AREAS[area].lon}, "clinics")
        if not answered:
            return self.say(gw, self.words(gw, "health_emergency_unreachable"), "health_emergency_unreachable")
        found = [{**f, "d": spec.domain} for spec, a in answered for f in a.get("facilities", [])]
        self.with_travel(gw, found, area)
        found.sort(key=self.how_far)
        free = [f for f in found if f.get("places_free", 0) > 0]
        if not free:
            if not found:
                return self.say(gw, self.words(gw, "health_emergency_none"), "health_emergency_none")
            near = found[0]
            return self.say(gw, self.words(gw, "health_emergency_all_full", name=near["name"], address=near["address"], travel=near.get("travel") or ""),
                            "health_emergency_all_full")
        best = free[0]
        await self.file_request(gw, self.spec_of(best), "emergency", self.words(gw, "health_staff_emergency", where=f" near {area}", said=said[:300] or "an emergency"),
                                urgent=True, name=best["name"], sms_name=best.get("sms_name") or best["name"])
        keep = [{"d": f["d"], "id": f["id"], "n": f["name"], "a": f["address"], "tv": f.get("travel") or ""} for f in free[:3]]
        full = self.words(gw, "health_emergency_full", full=found[0]["name"]) if found[0] is not best else ""   # a nearer hospital is full: the caller is told why
        text = self.words(gw, "health_emergency_found", name=best["name"], address=best["address"], travel=best.get("travel") or "", full=full)
        return self.ask(gw, "emergency_reached", "health.emergency", req, text, places=keep, said=said[:300])

    async def emergency_hold(self, gw, req: Request, places: list[dict], transcript: str) -> Outcome:
        """The caller could not reach the emergency number, or will not call it: the nearest hospital with a free place is asked to keep one, and the next
        one if it has just filled up. The caller hears and is texted where to go and the reference. Nothing is said about an ambulance being sent."""
        sorry = self.words(gw, "health_emergency_no_ambulance") if "ambulance" in tokens(transcript) else ""
        for place in places:
            spec = self.spec_of(place)
            answer = await self.provider_call(gw, spec, "emergency_hold", {"facility_id": place["id"]})
            held = (answer or {}).get("hold") if (answer or {}).get("ok") else None
            if not held:
                continue
            code = held["code"]
            gw.st["emergency_hold"] = {"n": place["n"], "a": place["a"], "code": code}
            self.note(gw, "held", provider=spec.label if spec else place["d"], place=place["n"], code=code)
            texted = await self.text_caller(gw, self.words(gw, "health_sms_emergency_hold", name=place["n"], address=place["a"], code=code))
            said = sorry + self.words(gw, "health_emergency_held", name=place["n"], address=place["a"], travel=place["tv"], code=" ".join(code.split("-")[1]))
            return self.say(gw, said + (" " + self.words(gw, "health_text_sent_emergency") if texted else ""), "health_emergency_held")
        near = places[0]
        return self.say(gw, sorry + self.words(gw, "health_emergency_all_full", name=near["n"], address=near["a"], travel=near["tv"]), "health_emergency_all_full")

    # ---- find ------------------------------------------------------------------------------------------

    async def find(self, gw, req: Request) -> Outcome:
        if req.need == "emergency care" or req.red_flag:     # someone may be in danger: the emergency help, never a list of clinics
            return await self.emergency(gw, req.utterance or "", area=req.area)
        if not req.area:
            return self.ask_where(gw, "health.find_facility", req)
        found, reachable = await self.places(gw, req, kind="pharmacies" if req.need == "pharmacy" else "clinics", limit=3)
        if not reachable:
            return self.nothing_reachable(gw, req)
        if not found:
            return self.say(gw, self.words(gw, "health_find_none"), "health_find_none")
        now = self.now()
        bookable = [f for f in found if f["bookable"]]
        if bookable and len(bookable) > 1:
            # Several clinics: the caller hears each one with what decides between them (waiting time and fee), then is asked whether to book.
            options = self.compact(bookable)
            text = self.options_text(gw, options, req.area, req.need) + " " + self.words(gw, "health_find_offer_many")
            return self.ask(gw, "offer_book", "health.find_facility", req, text, options=options)
        what = "pharmacy" if req.need == "pharmacy" else f"place for {speak.need_phrase(req.need)}" if req.need else "place"
        text = self.words(gw, "health_find_nearest", what=what, place=speak.place_line(found[0], now))
        if found[1:]:
            text += " " + self.words(gw, "health_find_others", others="; ".join(speak.option_line(f) for f in found[1:3]))
        if not bookable:
            return self.say(gw, text, "health_find")
        return self.ask(gw, "offer_book", "health.find_facility", req, f"{text} {self.words(gw, 'health_find_offer_one')}", options=self.compact(bookable))

    def add_trips(self, gw, options: list[dict], origin: str) -> None:
        """Puts the trip from where the caller is into options that were listed before Talk knew it, just after each place's name and kind."""
        places = [{"name": o["n"], "lat": o.get("la"), "lon": o.get("lo"), "area": o.get("pa")} for o in options]
        self.with_travel(gw, places, origin)
        for o, p in zip(options, places):
            if p.get("travel"):
                head = f"{o['n']}, {speak.article(o['k'])}"
                o["tv"], o["eta"] = p["travel"], p["eta"]
                o["line"] = f"{head}, {p['travel']}{o['line'][len(head):]}" if o["line"].startswith(head) else o["line"]

    @staticmethod
    def compact(found: list[dict]) -> list[dict]:
        """What is kept between turns about each option: enough to name it, say it again and ask its provider about it."""
        return [{"d": f["d"], "id": f["id"], "n": f["name"], "sn": f.get("sms_name") or f["name"], "line": speak.option_line(f), "fee": f.get("fee", 0), "w": f.get("wait_minutes", 0),
                 "km": f.get("km"), "k": speak.kind_phrase(f), "services": f.get("services", []), "eta": f.get("eta"), "tv": f.get("travel"),
                 "la": f.get("lat"), "lo": f.get("lon"), "pa": f.get("area")} for f in found]

    def options_text(self, gw, options: list[dict], area: str | None, need: str | None = None, lead: str = "") -> str:
        """The places the caller can choose from, each with what decides between them: "I found three places near Surulere for antenatal care. The first is ..."."""
        need = None if need in ("pharmacy", "emergency care") else need
        where = (f" near {area}" if area else "") + (f" for {speak.need_phrase(need)}" if need else "")
        intro = self.words(gw, "health_options_intro", lead=lead, count=speak.count_word(len(options)), where=where)
        spoken = " ".join(self.words(gw, "health_options_item", ordinal=ORDINAL_WORDS[i], line=o["line"]) for i, o in enumerate(options[:len(ORDINAL_WORDS)]))
        return f"{intro} {spoken}"

    def options_short(self, gw, options: list[dict]) -> str:
        """The places read out again by name only, for a caller who was just told all about them and has not yet said which one."""
        names = [self.words(gw, "health_options_short_item", ordinal=ORDINAL_WORDS[i], name=o["n"]) for i, o in enumerate(options[:len(ORDINAL_WORDS)])]
        spoken = "; ".join(names[:-1]) + "; or " + names[-1] if len(names) > 1 else "".join(names)
        return self.words(gw, "health_options_short", names=spoken)

    def options_question(self, gw, options: list[dict], area: str | None, need: str | None = None, lead: str = "") -> str:
        """The same list followed by the question that asks which one the caller means."""
        return f"{self.options_text(gw, options, area, need, lead)} {self.words(gw, 'health_options_ask')}"

    # ---- which place ---------------------------------------------------------------------------------

    @staticmethod
    def names_a_place(text: str | None, area: str) -> bool:
        """'Surulere' names an area; 'Aguda' or 'Surulere Care' names a place."""
        left = [t for t in tokens(text or "") if t not in tokens(area) and t not in PLACE_WORDS and t not in POLITE_WORDS]
        return bool(left)

    async def resolve_place(self, gw, req: Request, tool_id: str, *, bookable: bool = False) -> tuple[dict | None, Outcome | None]:
        """The one place the caller means, or the question that settles it. Returns (place, None) or (None, the outcome to give)."""
        text = req.facility or ""
        area = gazetteer.match_area(text) if text else None
        if area and not req.area:
            req.area = area.name
        query = text if text and not (area and not self.names_a_place(text, area.name)) else None
        found, reachable = await self.places(gw, Request(area=req.area, origin=req.origin), kind=None if tool_id != "health.book_appointment" else "clinics", bookable=bookable, query=query, limit=MAX_OPTIONS)
        if not reachable:
            return None, self.nothing_reachable(gw)
        if not found:
            req.tries += 1
            return None, self.ask_where(gw, tool_id, req)
        req.tries = 0    # the question about the place is settled: the tries that were used up asking for it must not count against the next question
        options = self.compact(found[:MAX_OPTIONS])
        if len(options) == 1:
            return options[0], None
        return None, self.ask(gw, "choose", tool_id, req, self.options_question(gw, options, req.area if not query else None), options=options)

    async def status(self, gw, req: Request) -> Outcome:
        if not (req.facility or req.area):
            return self.ask_where(gw, "health.facility_status", req)
        req.facility = req.facility or req.area
        place, outcome = await self.resolve_place(gw, req, "health.facility_status")
        return outcome or await self.status_of(gw, req, place)

    async def status_of(self, gw, req: Request, place: dict) -> Outcome:
        full = await self.fetch_place(gw, req, place)
        if not full:
            return self.nothing_reachable(gw)
        offers = join_names(full.get("services", [])[:4], "and")
        return self.say(gw, speak.place_line(full, self.now()) + (" " + self.words(gw, "health_status_offers", offers=offers) if offers else ""), "health_status")

    async def slots(self, gw, req: Request) -> Outcome:
        if not (req.facility or req.area):
            return self.ask_where(gw, "health.available_slots", req)
        req.facility = req.facility or req.area
        place, outcome = await self.resolve_place(gw, req, "health.available_slots", bookable=True)
        return outcome or await self.slots_of(gw, place)

    async def slots_of(self, gw, place: dict) -> Outcome:
        answer = await self.provider_call(gw, self.spec_of(place), "slots", {"facility_id": place["id"], "count": 3})
        if answer is None:
            return self.nothing_reachable(gw)
        now = self.now()
        found = [datetime.fromisoformat(s) for s in answer.get("slots", [])]
        if not found:
            return self.say(gw, self.words(gw, "health_slots_none", place=place["n"]), "health_slots_none")
        times = join_names([f"{say_day(s.date(), now.date())} at {say_time(s)}" for s in found], "and")
        return self.say(gw, self.words(gw, "health_slots", place=place["n"], times=times), "health_slots")

    # ---- booking -------------------------------------------------------------------------------------------------

    async def book(self, gw, req: Request) -> Outcome:
        if not (req.facility or req.area):
            return self.ask_where(gw, "health.book_appointment", req)
        need = req.need if req.need not in (None, "pharmacy", "emergency care") else None
        text = req.facility or ""
        area = gazetteer.match_area(text) if text else None
        if area and not req.area:
            req.area = area.name
        query = text if text and not (area and not self.names_a_place(text, area.name)) else None
        found, reachable = await self.places(gw, Request(need=need, area=req.area, origin=req.origin), kind="clinics", bookable=True, query=query, limit=MAX_OPTIONS)
        if not reachable:
            return self.nothing_reachable(gw)
        if not found:
            req.tries += 1
            return self.ask_where(gw, "health.book_appointment", req)
        req.tries = 0    # asking for the area is over: its tries must not count against the question that asks which clinic, or the one that asks when
        options = self.compact(found[:MAX_OPTIONS])
        if len(options) == 1:
            return await self.book_at(gw, req, options[0])
        return self.ask(gw, "choose", "health.book_appointment", req, self.options_question(gw, options, req.area if not query else None, need), options=options)

    async def book_at(self, gw, req: Request, place: dict) -> Outcome:
        """The place is settled. Ask for the day and time if they were not said, then offer the first real slot that fits."""
        if not req.origin and not req.from_asked and place.get("la") is not None:
            req.from_asked = True
            key = "health_ask_from_area" if req.area else "health_ask_from"
            return self.ask(gw, "from", "health.book_appointment", req, self.words(gw, key, place=place["n"], area=req.area), place=place)
        found = parse_when(req.when or "", self.now())
        if said_nothing_about_time(found) and wants_earliest(req.utterance):     # "Please book me the earliest time at Aguda."
            return await self.offer_slot(gw, req, place, found, note=self.words(gw, "health_note_earliest"))
        if said_nothing_about_time(found):
            return self.ask(gw, "when", "health.book_appointment", req, self.words(gw, "health_ask_when", place=place["n"]), place=place)
        return await self.offer_slot(gw, req, place, found)

    async def offer_slot(self, gw, req: Request, place: dict, found: dict, note: str = "") -> Outcome:
        spec, now = self.spec_of(place), self.now()
        args = {"facility_id": place["id"], "count": 6, **({"day": found["day"].isoformat()} if found["day"] else {}),
                **({"window": list(found["window"])} if found["window"] else {}), **({"at": found["at"]} if found["at"] is not None else {})}
        answer = await self.provider_call(gw, spec, "slots", args)
        if answer is None:
            return self.nothing_reachable(gw)
        slots, unreachable = self.reachable(req, place, answer.get("slots", []), now)
        if not slots and (found["day"] or unreachable):   # nothing that day, or nothing the caller can reach in time: the next free time after it
            after = (found["day"] or now.date()) + timedelta(days=1)
            more = {"facility_id": place["id"], "count": 6, **({"day": after.isoformat()} if unreachable else {})}
            answer = await self.provider_call(gw, spec, "slots", more)
            slots, _ = self.reachable(req, place, (answer or {}).get("slots", []), now)
            note = note or self.words(gw, "health_note_nothing_free", day=say_on_day(found["day"], now.date()), place=place["n"])
        if not slots:
            return self.say(gw, self.words(gw, "health_slots_none", place=place["n"]), "health_book_none")
        start, leave = datetime.fromisoformat(slots[0][0]), slots[0][1]
        day, time_ = say_on_day(start.date(), now.date()), say_time(start)
        if leave:
            depart, trip = leave
            question = self.words(gw, "health_offer_slot_leave", note=note, place=place["n"], day=day, time=time_, area=req.origin, span=travel.say_span(trip),
                                  leave=say_time(depart) if depart.date() == start.date() else f"{say_time(depart)} {say_on_day(depart.date(), now.date())}")
            self.note(gw, "travel", origin=req.origin, slot=f"{day} at {time_}", leave_by=say_time(depart), trip=travel.say_span(trip))
        else:
            question = self.words(gw, "health_offer_slot", note=note, place=place["n"], day=day, time=time_)
        return self.ask(gw, "confirm", "health.book_appointment", req, question, place=place, slot=slots[0][0])

    def reachable(self, req: Request, place: dict, slots: list[str], now: datetime) -> tuple[list[tuple[str, tuple | None]], bool]:
        """The offered times the caller can still reach, each with when to leave, and whether any time was left out because it could not be reached.
        Without the caller's area every time is kept, with no leaving time."""
        if not req.origin or place.get("la") is None:
            return [(s, None) for s in slots], False
        kept, dropped = [], False
        for s in slots:
            plan = travel.leave_by(req.origin, place["la"], place["lo"], place.get("pa"), datetime.fromisoformat(s), now)
            if plan is None:
                kept.append((s, None))
            elif plan[2]:
                kept.append((s, plan[:2]))
            else:
                dropped = True
        return kept, dropped

    async def make_booking(self, gw, req: Request, place: dict, slot: str) -> Outcome:
        visit = req.need if req.need in place.get("services", []) else "general consultation"
        answer = await self.provider_call(gw, self.spec_of(place), "book", {"facility_id": place["id"], "start": slot, "visit": visit})
        if answer is None:
            return self.nothing_reachable(gw)
        now = self.now()
        if not answer.get("ok"):   # taken a moment ago, or no longer offered: offer the next one that fits what was asked
            return await self.offer_slot(gw, req, place, parse_when(req.when or "", now), note=self.words(gw, "health_note_taken"))
        appt = answer["appointment"]
        start, code = datetime.fromisoformat(appt["starts"]), appt["code"]
        said = self.words(gw, "health_booked", place=place["n"], day=say_on_day(start.date(), now.date()), time=say_time(start), code=" ".join(code.split("-")[1]))
        sms_name = place.get("sn") or place["n"]
        text = self.words(gw, "health_sms_booked", place=sms_name, day=f"{start.strftime('%A')} {start.day} {start.strftime('%B')}", time=say_time(start), code=code)
        self.remember_visit(gw, place, appt)
        spec = self.spec_of(place)
        self.note(gw, "booked", provider=spec.label if spec else place["d"], place=place["n"], code=code, when=f"{say_day(start.date(), now.date())} at {say_time(start)}")
        if await self.text_caller(gw, text):
            said += " " + self.words(gw, "health_text_sent")
        return self.say(gw, said, "health_booked")

    def remember_visit(self, gw, place: dict, appt: dict) -> None:
        """Talk keeps the code, the place and the time of a visit it booked, so it can remind the patient and follow up. Nothing about why they are going."""
        from ...models import HealthAppointment

        gw.db.add(HealthAppointment(caller_id=gw.person.id, provider=place["d"], code=appt["code"], facility_name=place["n"], sms_name=place.get("sn") or place["n"],
                                    starts_local=appt["starts"]))

    async def text_caller(self, gw, body: str) -> bool:
        """Only ever to the caller's own number. True when the text was accepted, so the call says it was sent only when it was."""
        from ...services.notify import send_sms

        note = await send_sms(gw.db, gw.svc, to=gw.person.phone, body=body[:300], template="health_notice", caller_id=gw.person.id)
        return note.status in ("sent", "mock_sent")

    # ---- cancelling --------------------------------------------------------------------------------------------------

    async def cancel(self, gw, req: Request) -> Outcome:
        answered = await self.ask_all(gw, "upcoming", {}, "clinics")
        if not answered and self.specs("clinics"):
            return self.nothing_reachable(gw)
        mine = sorted(({**a, "d": spec.domain} for spec, answer in answered for a in answer.get("appointments", [])), key=lambda a: a["starts"])
        if not mine:
            return self.say(gw, self.words(gw, "health_cancel_none"), "health_cancel_none")
        now = self.now()
        wanted = parse_when(req.utterance, now)["day"]    # "my appointment for tomorrow": only the appointments of that day are meant
        if wanted:
            that_day = [a for a in mine if datetime.fromisoformat(a["starts"]).date() == wanted]
            if not that_day:
                return self.say(gw, self.words(gw, "health_cancel_none_day", day=say_on_day(wanted, now.date())), "health_cancel_none")
            mine = that_day
        first = mine[0]
        start = datetime.fromisoformat(first["starts"])
        return self.ask(gw, "cancel_confirm", "health.cancel_appointment", req,
                        self.words(gw, "health_cancel_ask", place=first["facility_name"], day=say_on_day(start.date(), now.date()), time=say_time(start)),
                        appointment={"d": first["d"], "code": first["code"]})

    # ---- the centre's patient guide ----------------------------------------------------------------------------------------

    async def ask_centre(self, gw, req: Request) -> Outcome:
        """A basic question, answered only from the centre's own patient guide. What the guide does not cover is not guessed at: it goes to the care team."""
        question = (req.utterance or "").strip()
        answered = await self.ask_all(gw, "knowledge", {"query": question, "limit": 3}, "clinics")
        if not answered:
            return self.nothing_reachable(gw)
        # a hospital the visitor made in the wizard is preferred over the others when its guide answers the question as well as another does
        entries = [e for _, e in sorted(((s.setting("scope") != "visitor", e) for s, a in answered for e in a.get("entries", [])), key=lambda pair: (-pair[1]["score"], pair[0]))][:3]
        gw.raw_json = {"health": "ask_the_centre", "entries": [e["id"] for e in entries]}
        if not entries:     # the guide does not cover it: the centre's staff see the question on their front desk, and the answer is texted back
            target = next(((s, a) for s, a in sorted(answered, key=lambda pair: pair[0].setting("scope") != "visitor") if a.get("provider")), None)
            filed = None
            if target:
                filed = await self.file_request(gw, target[0], "question", question, name=target[1]["provider"], sms_name=target[1].get("sms_name", ""))
            if filed:   # the request on the staff's front desk is the follow-up, so the caller is told who has the question and that the reply comes by text message
                return self.say(gw, self.words(gw, "health_question_passed", name=target[1].get("sms_name") or target[1]["provider"]), "health_question_filed")
            return await gw.give_up("health_not_in_the_guide", question)
        if entries[0]["id"] == "urgent-signs":   # a warning sign is spoken exactly as the centre wrote it, never reworded
            return self.say(gw, entries[0]["answer"], "health_urgent_signs")
        return await spoken_answer(gw, question, [e["answer"] for e in entries])

    # ---- medicines --------------------------------------------------------------------------------------------------------

    async def drug(self, gw, req: Request) -> Outcome:
        if not req.drug:
            return self.ask_where(gw, "health.drug_availability", req)
        args = {"drug": req.drug, **({"lat": AREAS[req.area].lat, "lon": AREAS[req.area].lon} if req.area else {})}
        answered = await self.ask_all(gw, "stock", args, "pharmacies")
        if not answered:
            return self.nothing_reachable(gw)
        drug = next((a["drug"] for _, a in answered if a.get("drug")), None)
        if not drug:
            req.tries += 1
            req.drug = None
            return self.ask_where(gw, "health.drug_availability", req)
        pharmacies = sorted((p for _, a in answered for p in a.get("pharmacies", [])), key=lambda p: (p["km"] is None, p["km"] if p["km"] is not None else 0, not p["open_now"], p["name"]))
        if not pharmacies:
            return self.say(gw, self.words(gw, "health_drug_none", drug=drug["name"]), "health_drug_none")
        text = self.words(gw, "health_drug_found", drug=drug["name"], where=join_names([p["name"] for p in pharmacies[:2]], "and"), price=f"{drug['price']:,}")
        if drug["prescription"]:
            text += " " + self.words(gw, "health_drug_prescription")
        night = next((p for p in pharmacies if p.get("all_day")), None)
        if night and night not in pharmacies[:2]:
            text += " " + self.words(gw, "health_drug_night", pharmacy=night["name"])
        return self.say(gw, text, "health_drug")

    # ---- the caller's answers ------------------------------------------------------------------------------------------

    def take_time(self, req: Request, transcript: str) -> None:
        """A caller who names a day or a time while answering something else ("Yes, book the private clinic for tomorrow morning") is not asked for it again."""
        if not said_nothing_about_time(parse_when(transcript, self.now())):
            req.when = transcript.strip()[:120]

    async def resolve_pending(self, gw, pending: dict, transcript: str) -> Outcome | None:
        st, step, tool_id = gw.st, pending["step"], pending.get("tool")
        req = Request.unpack(pending.get("req"))
        tries = pending.get("tries", 0)

        if step == "what":
            u = await gw.understand(transcript)
            st["pending"] = None
            fresh = await self.read(gw, transcript)
            req = Request.unpack({**req.__dict__, **{k: v for k, v in fresh.__dict__.items() if v not in (None, "", False, 0)}})
            tool = self.tool_of(u, req)
            return await self.start(gw, tool, req) if tool else None

        answer = answer_of(transcript, cancelling=step == "cancel_confirm")
        if step in ("offer_book", "confirm", "cancel_confirm"):
            plain = await gw.answer_to(transcript)  # the model's reading of a yes or a no, said in any way
            answer = {"yes": "yes", "no": "no"}.get(plain, answer)
            if answer == "yes" and hesitates(transcript):    # a caller who is thinking, waiting or asking for more has agreed to nothing, whatever the model made of it
                answer = None
        gw.raw_json = {"health_step": step, "answer": answer}

        if step == "offer_book":
            st["pending"] = None
            if answer == "no":
                return gw.reply("declined", action="health_offer_declined")
            options = pending["options"]
            req.tries = 0    # the tries used up asking for the area do not count against the questions that follow
            chosen = self.pick_by_words(transcript, options)    # "Yes, please book the private clinic" answers the offer and the choice together
            if answer != "yes" and chosen is None:
                return None
            if chosen is None and len(options) == 1:
                chosen = 0
            if chosen is not None:
                self.take_time(req, transcript)
                return await self.book_at(gw, req, options[chosen])
            return self.ask(gw, "choose", "health.book_appointment", req, self.options_short(gw, options), options=options)

        if step == "choose":
            options = pending["options"]
            index = await self.pick_option(gw, transcript, options)
            here = gazetteer.caller_location(transcript)
            if index is None and here and here.name != req.origin:   # the caller said where they are: the same places again, now with the trip from there
                req.origin = here.name
                self.add_trips(gw, options, req.origin)
                return self.ask(gw, "choose", tool_id, req, self.options_question(gw, options, None, lead=self.words(gw, "health_options_from", area=here.name)), options=options)
            if index is None:
                if tries + 1 >= MAX_TRIES:
                    st["pending"] = None
                    return gw.reply("declined", action="health_choose_dropped")
                req.tries = tries + 1
                return self.ask(gw, "choose", tool_id, req, self.options_question(gw, options, None, lead=self.words(gw, "health_options_again")), options=options)
            st["pending"] = None
            req.tries = 0    # the place is chosen: the tries spent on choosing it must not count against the question that asks when
            place = options[index]
            if tool_id == "health.facility_status":
                return await self.status_of(gw, req, place)
            if tool_id == "health.available_slots":
                return await self.slots_of(gw, place)
            self.take_time(req, transcript)
            return await self.book_at(gw, req, place)

        if step == "where":
            u = await gw.understand(transcript)
            fresh = await self.read(gw, transcript)
            area = gazetteer.match_area(transcript)
            answered_it = bool(area or fresh.area or fresh.facility or (tool_id == "health.drug_availability" and fresh.drug))
            if u.tool in dict(TOOLS) and u.tool != tool_id and not answered_it:   # not an answer at all: the caller has asked for something else
                st["pending"] = None
                return None
            st["pending"] = None
            req.tries = tries + 1
            req.need = req.need or fresh.need
            if tool_id == "health.drug_availability":
                req.drug = fresh.drug or transcript.strip()[:80]
            elif tool_id == "health.find_facility":
                req.area = (area.name if area else None) or fresh.area
                req.origin = req.area or req.origin     # Talk asked which area the caller is in, so the answer is where they are
            else:
                req.area = (area.name if area else None) or fresh.area or req.area
                req.facility = fresh.facility or transcript.strip()[:80]
                here = gazetteer.caller_location(transcript) or (area if area and not self.names_a_place(transcript, area.name) else None)
                req.origin = here.name if here else req.origin     # "which area of Lagos are you in?" was answered with an area, so that is where the caller is
            return await self.start(gw, tool_id, req)

        if step == "emergency_check":     # "Is someone in danger right now?"
            st["pending"] = None
            said = pending.get("said") or transcript
            yes = answer_of(transcript) == "yes" or floor.read(transcript).level == floor.EMERGENCY
            if not yes and answer_of(transcript) != "no":
                yes = (await self.meaning(gw, pending, transcript)).meaning == "yes"
            if yes:
                self.note(gw, "urgency", level=floor.EMERGENCY, source="caller", hits=[])
                return await self.emergency(gw, f"{said} {transcript}")
            return await self.turn(gw, said, 1.0)      # nobody is in danger: the first request is answered as it was meant

        if step == "emergency_where":
            here = gazetteer.match_area(transcript) or gazetteer.match_area((await self.meaning(gw, pending, transcript)).area or "")
            st["pending"] = None
            if here:
                return await self.emergency_route(gw, req, here.name, f"{pending.get('said', '')} {transcript}".strip())
            if tries + 1 >= MAX_TRIES:
                return self.say(gw, self.words(gw, "health_giveup_emergency"), "health_where_dropped")
            req.tries = tries + 1
            return self.ask(gw, "emergency_where", "health.emergency", req, self.words(gw, "health_emergency_ask_where_again"), said=pending.get("said", ""))

        if step == "emergency_reached":   # "Were you able to reach 112?" Anything other than a clear yes is taken as no: the caller is helped either way
            st["pending"] = None
            reached = answer_of(transcript) == "yes" and "ambulance" not in tokens(transcript)
            if answer_of(transcript) is None and "ambulance" not in tokens(transcript):
                reached = (await self.meaning(gw, pending, transcript)).meaning == "yes"
            places = pending.get("places") or []
            if reached and places:
                return self.say(gw, self.words(gw, "health_emergency_reached", name=places[0]["n"]), "health_emergency_reached")
            return await self.emergency_hold(gw, req, places, transcript)

        if step == "from":
            place = pending["place"]
            area = gazetteer.match_area(transcript) or gazetteer.match_area((await self.read(gw, transcript)).area or "")
            st["pending"] = None
            if area:
                req.origin = area.name
            elif req.area and answer_of(transcript) == "yes":     # "Will you be travelling from Surulere?" "Yes, please."
                req.origin = req.area
            else:
                meant = await self.meaning(gw, pending, transcript)
                named = gazetteer.match_area(meant.area or "") if meant.meaning == "gave_it" else None
                if named:
                    req.origin = named.name
                elif meant.meaning == "yes" and req.area:
                    req.origin = req.area
                elif meant.meaning == "something_else":
                    return None
            self.take_time(req, transcript)
            return await self.book_at(gw, req, place)

        if step == "when":
            place, now = pending["place"], self.now()
            found = parse_when(transcript, now)
            if said_nothing_about_time(found):
                found = parse_when((await self.read(gw, transcript)).when or "", now)
            if said_nothing_about_time(found):
                meant = await self.meaning(gw, pending, transcript) if not wants_earliest(transcript) else Meaning(meaning="earliest")
                if meant.meaning == "earliest":     # "When is the next available slot?": the first time the caller can reach
                    st["pending"] = None
                    req.when = None
                    return await self.offer_slot(gw, req, place, parse_when("", now), note=self.words(gw, "health_note_earliest"))
                if meant.meaning == "gave_it" and meant.when:
                    found = parse_when(meant.when, now)
                if meant.meaning == "something_else":   # a different request: it is handled as one
                    st["pending"] = None
                    return None
            if said_nothing_about_time(found):
                if tries + 1 >= MAX_TRIES:
                    st["pending"] = None
                    return gw.reply("declined", action="health_when_dropped")
                req.tries = tries + 1
                return self.ask(gw, "when", tool_id, req, self.words(gw, "health_ask_when_again"), place=place)
            st["pending"] = None
            req.when = transcript.strip()[:120]
            return await self.offer_slot(gw, req, place, found)

        if step == "confirm":
            place, now = pending["place"], self.now()
            fresh = parse_when(transcript, now)
            if not said_nothing_about_time(fresh) and (tokens(transcript) or [""])[0] not in YES_OPENERS:   # a different day or time, not a yes to the one offered
                st["pending"] = None
                req.when = transcript.strip()[:120]
                return await self.offer_slot(gw, req, place, fresh)
            if answer == "yes":
                st["pending"] = None
                return await self.make_booking(gw, req, place, pending["slot"])
            if answer == "no":
                if tries + 1 >= 3:
                    st["pending"] = None
                    return gw.reply("declined", action="health_confirm_dropped")
                req.tries = tries + 1
                return self.ask(gw, "when", tool_id, req, self.words(gw, "health_ask_when_other"), place=place)
            st["pending"] = None
            return None

        if step == "cancel_confirm":
            st["pending"] = None
            if answer == "yes":
                appt = pending["appointment"]
                done = await self.provider_call(gw, self.spec_of(appt), "cancel", {"code": appt["code"]})
                if done is None:
                    return self.nothing_reachable(gw)
                if not done.get("ok"):
                    return self.say(gw, self.words(gw, "health_cancel_failed"), "health_cancel_failed")
                from ...models import HealthAppointment

                row = gw.db.scalar(select(HealthAppointment).where(HealthAppointment.code == appt["code"], HealthAppointment.caller_id == gw.person.id))
                if row:
                    row.status = "cancelled"
                sent = await self.text_caller(gw, self.words(gw, "health_sms_cancelled", code=appt["code"]))
                return self.say(gw, self.words(gw, "health_cancelled") + (" " + self.words(gw, "health_text_sent_cancel") if sent else ""), "health_cancelled")
            if answer == "no":
                return self.say(gw, self.words(gw, "health_cancel_kept"), "health_cancel_kept")
            return None

        st["pending"] = None
        return None

    def pick_by_words(self, text: str, options: list[dict]) -> int | None:
        """Which of the offered places the caller means, from what they said: 'the first', a name, 'the private one', 'the cheaper one'. None when their words do not settle it."""
        said = tokens(text)
        for w in said:
            if w in ORDINALS and ORDINALS[w] < len(options):
                return ORDINALS[w]
        named = [i for i, o in enumerate(options) if {t for t in tokens(o["n"]) if t not in PLACE_WORDS} & set(said)]
        if len(named) == 1:
            return named[0]
        kinds = {KIND_WORDS[w] for w in said if w in KIND_WORDS}
        if kinds:
            matching = [i for i, o in enumerate(options) if all(k in o["k"] for k in kinds)]
            if matching:
                return matching[0]     # the list is nearest first; the offer that follows names the place, so a wrong guess is heard and corrected
        if any(w in said for w in ("cheaper", "cheapest", "cheap", "lowest")):
            return min(range(len(options)), key=lambda i: options[i]["fee"])
        if any(w in said for w in ("nearest", "closest", "closer")):
            return min(range(len(options)), key=lambda i: self.how_far(options[i]))
        if any(w in said for w in ("quicker", "quickest", "faster", "fastest", "shorter", "shortest")):
            return min(range(len(options)), key=lambda i: options[i]["w"])
        return None

    async def meaning(self, gw, pending: dict, text: str) -> Meaning:
        """What the caller meant by their answer to the question Talk had just asked, read by the model with the question in view. Only words the caller
        said count as a day, a time or an area. When the model cannot answer, the meaning is unclear and Talk asks again, as it did before."""
        question = (pending.get("question") or "")[-300:]
        schema = {"type": "object", "additionalProperties": False, "required": ["meaning", "when", "area"],
                  "properties": {"meaning": {"type": "string", "enum": MEANINGS},
                                 "when": {"anyOf": [{"type": "string"}, {"type": "null"}]}, "area": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}
        system = ("REPLY\nTalk, a health line in Lagos, asked a caller the QUESTION below, and the caller answered. Say what the caller meant.\n"
                  "meaning: gave_it (they answered what was asked), earliest (they want the first free time, for example the next available slot or as soon as "
                  "possible), yes, no, something_else (they asked for something different), or unclear.\n"
                  "when: the day and time they asked for, in their own words, or null. area: the part of Lagos they named, in their own words, or null.\n"
                  f"QUESTION: {question or 'not known'}")
        started = time.perf_counter()
        try:
            got, _raw = await gw.svc.llm.extract(Meaning, system, text, json_schema=schema)
        except Exception as exc:
            log.warning("the model did not read the answer: %s", exc)
            return Meaning()
        said = set(tokens(text))
        keep = lambda v: v.strip() if isinstance(v, str) and v.strip() and set(tokens(v)) <= said else None   # noqa: E731  only the caller's own words
        meant = Meaning(meaning=got.meaning if got.meaning in MEANINGS else "unclear", when=keep(got.when), area=keep(got.area))
        self.note(gw, "meant", meaning=meant.meaning, ms=int((time.perf_counter() - started) * 1000))
        return meant

    async def pick_option(self, gw, text: str, options: list[dict]) -> int | None:
        """Which of the offered places the caller means. The caller's words settle it when they can (see pick_by_words); the model reads it only when they do not."""
        chosen = self.pick_by_words(text, options)
        if chosen is not None:
            return chosen
        try:
            schema = {"type": "object", "additionalProperties": False, "required": ["choice"],
                      "properties": {"choice": {"type": "string", "enum": [str(i + 1) for i in range(len(options))] + ["none"]}}}
            listing = "\n".join(f"{i + 1}. {o['line']}" for i, o in enumerate(options))
            pick, _raw = await gw.svc.llm.extract(PickedOption, f"CHOICE\nA caller was offered these places and answered. Say the number of the one they mean, or none.\n{listing}", text,
                                                  json_schema=schema)
            if pick.choice and pick.choice.isdigit() and 1 <= int(pick.choice) <= len(options):
                return int(pick.choice) - 1
        except Exception as exc:
            log.warning("could not read the choice: %s", exc)
        return None
