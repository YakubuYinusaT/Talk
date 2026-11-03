"""Sofa led by the model: Muse Spark reads the whole conversation and decides what to do next, and the code does it and keeps the guard rails.

Each turn the model sees everything said in the call by both sides, the places Sofa has offered, any booking it has proposed, and the caller's latest words. It
answers with one decision: a step to take (find places, find a medicine, read free times, propose a booking, confirm it, cancel, ask a care team, and so on) or
a short reply of its own. The code then takes that step with the providers' own systems and speaks their facts in Talk's fixed wording.

The guard rails stay in code, whatever the model decides:
- Every fact comes from a provider: a place, a time, a price, a distance or a stock level the model writes itself is only spoken if it was already said in
  this call, and a reply that brings in a new one is not spoken.
- A visit is booked only after Sofa proposed that exact place and time and the caller agreed to it, and cancelled only after the caller confirmed it.
- The emergency check on the caller's words runs first, every turn, before the model is asked; the model can raise the urgency, never lower it.
- An area is one of the areas Talk knows (the model maps a neighbourhood to the nearest one, and Sofa says which), and a day or a time must be made of the
  caller's own words.
When the model gives no usable decision (no answer, a slow one, or one outside these rules), the rules-based front desk answers the turn as before.
"""

import logging
import re
import time

from pydantic import BaseModel

from ...health import data, gazetteer
from ...health.when import parse_when, said_nothing_about_time

log = logging.getLogger("sofa.agent")

ACTIONS = {
    "find_places": "find clinics or pharmacies near an area, with distance, waiting time and fee (kind, need, caller_area or search_area)",
    "medicine": "which pharmacies have a medicine in stock, its price and how far they are (medicine, caller_area)",
    "free_times": "the next free appointment times at one place (place)",
    "offer_booking": "start or continue booking a visit (place or option number, when or earliest, need). Sofa then proposes one exact time and asks the caller to agree",
    "reserve_medicine": "set a medicine aside at a pharmacy for the caller to collect and pay for (medicines: the one product; place: the pharmacy, if said). Sofa proposes it with the price and asks the caller to agree",
    "confirm_booking": "ONLY when PROPOSED below is a visit or a medicine order Sofa has just offered and the caller clearly agrees to it now",
    "cancel_booking": "the caller wants to cancel their own visit (when, if they said which)",
    "confirm_cancel": "ONLY when Sofa has just asked the caller to confirm a cancellation and the caller clearly agrees",
    "place_status": "whether a place is open now and how long its queue is (place)",
    "ask_care_team": "a question about care at a centre: what to bring, how treatment days work, who to call (question, in the caller's words)",
    "reply": "say something yourself: a greeting, ONE short question for a missing detail, or an answer made only of facts already said in this call",
    "person": "the caller asks to speak to a person",
    "goodbye": "the caller is finished",
    "other": "a request that is not about health care",
}
URGENCY = ["none", "possible", "emergency"]
AREAS = sorted(data.AREAS)
WORDS_FOR_PLACES = r"(?:Clinic|Hospital|Centre|Center|Pharmacy|Health Centre|Medical Centre)"


class Decision(BaseModel):
    urgency: str | None = None
    action: str | None = None
    kind: str | None = None
    need: str | None = None
    caller_area: str | None = None
    search_area: str | None = None
    place: str | None = None
    when: str | None = None
    medicines: list[str] = []
    question: str | None = None
    reply: str | None = None


def _one_of(values: list[str], description: str) -> dict:
    return {"anyOf": [{"type": "string", "enum": values}, {"type": "null"}], "description": description}


def _text(description: str) -> dict:
    return {"anyOf": [{"type": "string"}, {"type": "null"}], "description": description}


SCHEMA = {
    "type": "object", "additionalProperties": False, "required": list(Decision.model_fields),
    "properties": {
        "urgency": {"type": "string", "enum": URGENCY, "description": "whether someone may be in danger now"},
        "action": {"type": "string", "enum": list(ACTIONS), "description": "the one step to take now"},
        "kind": _one_of(["clinic", "pharmacy"], "for find_places: what kind of place"),
        "need": _one_of(gazetteer.NEED_CHOICES, "what the caller needs care for, if they said"),
        "caller_area": _one_of(AREAS, "where the caller is or will travel from, said anywhere in the call; a neighbourhood not in the list is mapped to the nearest area in it"),
        "search_area": _one_of(AREAS, "where to look, when it is not where the caller is"),
        "place": _text("the number of an option on the table such as 1 or 2, a place as Sofa named it, or the caller's own words for a place, such as the general hospital"),
        "when": _text("a day or time in the caller's own words, or the word earliest when they want the first free time"),
        "medicines": {"type": "array", "items": {"type": "string"}, "description": "for medicine: the CATALOGUE products, by their exact names, that fit what the caller asked for; several when they asked for a kind of medicine"},
        "question": _text("for ask_care_team: the caller's question"),
        "reply": _text("for reply: what Sofa says, one or two short spoken sentences"),
    },
}

PROMPT = """AGENT. You are Sofa, the voice assistant of Talk, answering a phone call in Lagos, Nigeria. Callers speak English, Nigerian English or Pidgin. You help them
reach health care: find a clinic or a pharmacy, check a medicine, book or cancel a visit, or ask a care team a question. Read the whole conversation below and
decide the ONE next step. Answer with JSON only, with every field present.

How to decide:
- Understand what the caller means from the whole call, as a person would: "there" or "that one" refer to what was said before, a "no" can come with a new
  request ("No, I just need paracetamol" is a medicine request), and a place or a time can be given at any moment.
- Never ask for something the caller has already said in this call. Carry every detail forward: the area, the need, the medicine, the place, the time.
- Use a step whenever a fact is needed. In a reply, only use facts already said in this call; never make up a place, a price, a time, a distance or a stock level.
- Never give medical advice, a diagnosis or a dose. A question about care at a centre goes to ask_care_team.
- Medicines: the CATALOGUE below is what the pharmacies keep, from their own systems. Work out from what the caller means which products fit, in any
  words they use ("a pain reliever", "antimalaria", "something for catarrh", a brand name), and give their exact CATALOGUE names in medicines: one when
  they named a product, every one that fits when they asked for a kind of medicine. If nothing in the CATALOGUE fits, say so in a reply. You may say what a
  product is for, its price and whether it needs a prescription, from the CATALOGUE. A pharmacist decides which product suits the caller.
- A pharmacy has no consultation fee: never mention one for a pharmacy.
- Keep replies short, polite and spoken: one or two sentences, no lists, no symbols.
- caller_area and search_area must be one of the areas listed. If the caller names a neighbourhood that is not listed, give the nearest listed area.
- A caller who asked for the next available slot, the earliest time, "as soon as possible", or simply when they can come ("When I fit bring am come?"),
  and a caller who says "book it" when no time was ever said, wants the earliest time: once a place is known, use offer_booking
  with when earliest, not free_times. "Book it" after Sofa read out free times, with no time chosen, is also offer_booking with when earliest.
- free_times is only for a caller who asks which times are free and has not asked to book.
- A caller who wants to buy, get, order or reserve a medicine ("reserve it for me", "I will take the ibuprofen") gets reserve_medicine; the price is paid by
  bank transfer to an account Talk sends, and the caller collects it at the pharmacy.
- A caller who names a place that is not on the table ("the general hospital") is asking for it: pass their words as place, with the area, and Talk searches for it.
- After a booking is proposed (PROPOSED), a yes is confirm_booking; a question about it (the fee, the address) is a reply from what was said, and the
  proposal stays open.

urgency: emergency when a person may be in danger of death or serious harm now (not breathing, not waking, collapsed, a fit, heavy bleeding, choking, poisoning,
a bite with fast swelling, chest pain with trouble breathing, a serious accident, a birth happening now, a wish to self-harm). possible when it might be one of
those or the caller is unsure. none for everything else, including a fever with no danger sign, a check-up, a past event, or a figure of speech.

STEPS:
{steps}
CATALOGUE:
{catalogue}
AREAS: {areas}
NEEDS: {needs}

THE CALL SO FAR (oldest first):
{log}
OPTIONS ON THE TABLE: {options}
PROPOSED: {proposed}
OPEN QUESTION: {question}"""


def numbered(options: list[dict]) -> str:
    return "; ".join(f"{i + 1}. {o['n']}" for i, o in enumerate(options)) or "none"


class HealthAgent:
    """Asks the model for the next step and takes it through the health front desk (adapters/health.py), which holds the providers and the wording."""

    def __init__(self, desk):
        self.desk = desk

    # ---- what the model is shown ----------------------------------------------------------------------------

    @staticmethod
    def options_of(st: dict) -> list[dict]:
        pending, mem = st.get("pending") or {}, st.get("health_memory") or {}
        return pending.get("options") or mem.get("options") or ([mem["place"]] if mem.get("place") else [])

    @staticmethod
    def catalogue_text(products: list[dict]) -> str:
        return "\n".join(f"- {p['name']}: {p.get('use') or 'a pharmacy product'}; about {p['price']:,} naira a pack" + ("; needs a prescription" if p.get("prescription") else "")
                         for p in products) or "(no pharmacy catalogue could be read)"

    def prompt(self, st: dict, catalogue: str = "") -> str:
        pending = st.get("pending") or {}
        proposed = "none"
        if pending.get("step") == "confirm" and pending.get("place"):
            proposed = f"a visit at {pending['place']['n']} ({pending.get('question', '')[-200:]})"
        elif pending.get("step") == "order_confirm":
            proposed = f"a medicine order ({pending.get('question', '')[-200:]})"
        elif pending.get("step") == "cancel_confirm":
            proposed = f"cancelling a visit ({pending.get('question', '')[-200:]})"
        log_lines = "\n".join(f"{who.upper()}: {text}" for who, text in (st.get("log") or [])[-16:]) or "(the call has just started)"
        steps = "\n".join(f"- {name}: {what}" for name, what in ACTIONS.items())
        return PROMPT.format(steps=steps, catalogue=catalogue, areas=", ".join(AREAS), needs=", ".join(gazetteer.NEED_CHOICES), log=log_lines, options=numbered(self.options_of(st)),
                             proposed=proposed, question=pending.get("question", "none")[-300:] if pending else "none")

    async def decide(self, gw, transcript: str) -> Decision | None:
        """The model's decision for this turn, or None when it gave no usable one (the rules then answer)."""
        started = time.perf_counter()
        try:
            gw.catalogue_text = self.catalogue_text(await self.desk.catalogue(gw))     # what the pharmacies keep, from their own systems
            got, _raw = await gw.svc.llm.extract(Decision, self.prompt(gw.st, gw.catalogue_text), transcript, json_schema=SCHEMA)
        except Exception as exc:   # the model not answering must never cost the caller a reply
            log.warning("the agent decision failed: %s", exc)
            return None
        if got.action not in ACTIONS:
            return None
        got.caller_area = got.caller_area if got.caller_area in data.AREAS else None
        got.search_area = got.search_area if got.search_area in data.AREAS else None
        got.need = got.need if got.need in gazetteer.NEED_CHOICES else None
        got.when = self.grounded_when(gw.st, transcript, got.when)
        gw.note("decided", action=got.action, urgency=got.urgency or "none", area=got.caller_area or got.search_area, place=got.place, when=got.when,
                medicine=", ".join(got.medicines) or None, model=getattr(gw.svc.llm, "model", ""), ms=int((time.perf_counter() - started) * 1000))
        return got

    # ---- the guard rails --------------------------------------------------------------------------------------

    @staticmethod
    def caller_words(st: dict, transcript: str) -> set[str]:
        said = " ".join([text for who, text in (st.get("log") or []) if who == "caller"] + [transcript])
        return set(re.findall(r"[a-z0-9']+", said.lower()))

    def grounded_when(self, st: dict, transcript: str, when: str | None) -> str | None:
        """A day or a time counts only if it is made of the caller's own words; "earliest" is the caller asking for the first free time."""
        if not when or not when.strip():
            return None
        if when.strip().lower() == "earliest":
            return "earliest"
        words = set(re.findall(r"[a-z0-9']+", when.lower()))
        return when.strip()[:120] if words and words <= self.caller_words(st, transcript) else None

    @staticmethod
    def grounded_reply(st: dict, transcript: str, text: str, catalogue: str = "") -> bool:
        """A reply the model wrote may only carry facts already said in this call or written in the pharmacies' catalogue: every figure and every named
        place must appear in one of them."""
        said = " ".join(t for _, t in (st.get("log") or [])) + " " + transcript + " " + ((st.get("pending") or {}).get("question") or "") + " " + catalogue
        for figure in re.findall(r"\d[\d,.:]*", text):
            if figure.rstrip(".,:") not in said:
                return False
        for place in re.findall(rf"((?:[A-Z][\w']*\s){{1,5}}{WORDS_FOR_PLACES})", text):
            if place.strip() not in said:
                return False
        return True

    # ---- taking the step -----------------------------------------------------------------------------------

    def request_of(self, gw, d: Decision, transcript: str):
        from .health import Request

        place = (d.place or "").strip()
        options = self.options_of(gw.st)
        if place.isdigit() and 1 <= int(place) <= len(options):    # "the second one"
            place = options[int(place) - 1]["n"]
        need = d.need or ("pharmacy" if d.kind == "pharmacy" else None)
        return Request(need=need, area=d.search_area or d.caller_area, origin=d.caller_area, facility=place or None,
                       when=None if d.when == "earliest" else d.when, earliest=d.when == "earliest", drug=d.medicines[0] if d.medicines else None,
                       utterance=transcript[:300])

    async def act(self, gw, d: Decision, transcript: str):
        """Take the step the model chose. None hands the turn to the rules."""
        desk, st = self.desk, gw.st
        pending = st.get("pending") or {}
        req = self.request_of(gw, d, transcript)
        a = d.action
        if a == "other":
            return None
        if a == "goodbye":
            gw.call.outcome = gw.call.outcome or "completed"
            st["pending"] = None
            return gw.reply("call_goodbye", end=True, action="goodbye")
        if a == "person":
            st["pending"] = None
            return await gw.give_up("asked_for_person", transcript) if st.get("domain") else gw.reply("call_no_human", action="asked_for_person")
        if a == "reply":
            text = (d.reply or "").strip()
            if not text or len(text) > 400 or not self.grounded_reply(st, transcript, text, getattr(gw, "catalogue_text", "")):
                gw.note("guard", stopped="a reply with a fact that was not said in this call")
                return None
            return gw.reply("health_say", action="agent_reply", answer=text)     # spoken as written; an open question stays open
        if a == "reserve_medicine":
            st["pending"] = None
            desk.recall(gw, "health.drug_availability", req)
            product = (d.medicines[0] if d.medicines else None) or req.drug or (desk.memory(gw).get("req") or {}).get("drug")
            if not product:
                return None
            place = (d.place or "").strip() or (desk.memory(gw).get("pharmacy") or {}).get("n")
            return await desk.offer_order(gw, req, product, place if place and not place.isdigit() else None)
        if a == "confirm_booking" and pending.get("step") == "order_confirm":
            return await desk.resolve_pending(gw, pending, transcript, agreed=True)
        if a == "confirm_booking":
            if pending.get("step") != "confirm":     # nothing was proposed: start the booking, so that Sofa proposes a time first
                return await desk.start(gw, "health.book_appointment", req)
            return await desk.resolve_pending(gw, pending, transcript, agreed=True)
        if a == "confirm_cancel":
            if pending.get("step") != "cancel_confirm":
                return await desk.start(gw, "health.cancel_appointment", req)
            return await desk.resolve_pending(gw, pending, transcript, agreed=True)
        if a in ("find_places", "free_times") and req.facility and "book" in re.findall(r"[a-z]+", transcript.lower()):
            a = "offer_booking"     # "Book the general hospital for me" asks for a booking at that place, whatever step was picked
        st["pending"] = None     # a new step: the question that was open is answered by it
        tool = {"find_places": "health.find_facility", "medicine": "health.drug_availability", "free_times": "health.available_slots",
                "offer_booking": "health.book_appointment", "cancel_booking": "health.cancel_appointment", "place_status": "health.facility_status",
                "ask_care_team": "health.ask_the_centre"}[a]
        if a == "find_places" and d.kind == "pharmacy":
            req.need = "pharmacy"
        if a == "medicine" and len(d.medicines) > 1:     # a kind of medicine: the products that fit, at the nearest pharmacy that has them
            self.desk.recall(gw, "health.drug_availability", req)
            return await desk.drug_options(gw, req, d.medicines)
        if a == "medicine" and not req.drug:
            req.drug = gazetteer.match_drug(transcript)
        if a == "ask_care_team":
            req.utterance = (d.question or transcript)[:300]
        if tool in ("health.book_appointment", "health.available_slots") and req.facility and not req.area:
            req.area = req.origin
        return await desk.start(gw, tool, req)
