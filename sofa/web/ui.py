"""Shared rendering helpers for every page of the site and for the front desks: the template engine, the menu, the providers and the plain-language steps of the trace.

The steps are what the language model's orchestration looks like to a reader. The orchestrator records a trace for every turn (heard, understood, read,
asked, booked, request, replied); `describe_trace` turns that list into short lines, and the same lines are shown on the Try it page, on the Live calls
page and in the onboarding wizard, so a visitor sees one picture of what Talk did.

The templates in sofa/web/templates are written against a small set of globals (the menu, the home address, the asset version). `install` puts them into a template
environment, and it is used for the site and also for the front desks, which have an environment of their own, so that both are built in the same shell.
"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.templating import Jinja2Templates
from starlette.requests import Request

WEB = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB / "templates"))

LONG_DIGITS = re.compile(r"\d{6,}")


def scrub(text: str | None) -> str:
    """Hide any run of six or more digits: a phone number or an identifier must never reach a public page."""
    return LONG_DIGITS.sub("[hidden]", text or "")


def mask_phone(number: str) -> str:
    return ("*" * max(0, len(number) - 4)) + number[-4:] if number else ""


def lagos_now() -> str:
    """The as-of time that every figure on a page carries (Africa/Lagos, UTC+1, no daylight saving)."""
    return (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%H:%M")


def as_of() -> str:
    return f"as of {lagos_now()} Lagos"


def _lagos(value) -> str:
    if not value:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (value + timedelta(hours=1)).strftime("%d %b %Y, %H:%M")


# ---- the site: five pages, in this order, on every page ------------------------------------------------------------

HOME = "/overview"

# Each page of the menu: its label, its address, and the addresses that belong to it (an address that ends the match exactly, or one that is the start of a longer address).
# A front desk lives under /synthetic, so it belongs to Providers unless the desk says otherwise.
PAGES = [("Home", HOME, [("/", True), (HOME, True)]),
         ("Try it", "/try", [("/try", False)]),
         ("Live calls", "/demo", [("/demo", False)]),
         ("Providers", "/overview/providers", [("/overview/providers", False), ("/synthetic", False)]),
         ("Onboard a hospital", "/onboard", [("/onboard", False)])]


def _owns(path: str, owned: list[tuple[str, bool]]) -> bool:
    return any(path == base or (not exact and path.startswith(base + "/")) for base, exact in owned)


def site_nav(request=None, current: str = "") -> list[tuple[str, str, bool]]:
    """The links across the top of every page: (label, address, whether it is this page).

    A page that is switched off in the settings is left out. When there is no request to read (a front desk is rendered without one) every page is listed, and `current` names
    the label that is shown as the page the visitor is on."""
    off: set[str] = set()
    path = ""
    if isinstance(request, Request):
        path = request.url.path.rstrip("/") or "/"
        svc = getattr(request.app.state, "svc", None)
        if svc is not None:
            if not getattr(svc.settings, "try_page_enabled", True):
                off.add("/try")
            if not getattr(svc.settings, "demo_page_enabled", False):
                off.add("/demo")
            if not getattr(svc, "onboarding", None):
                off.add("/onboard")
    current = current if isinstance(current, str) else ""
    return [(label, href, (label == current) if current else _owns(path, owned)) for label, href, owned in PAGES if href not in off]


# ---- the four simulated providers ------------------------------------------------------------------------------------

OFFERS = {"state-phc": "Health centres and general hospitals. Low fees, longer queues, and emergency departments.",
          "eko-care": "A private clinic group. Higher fees and much shorter queues.",
          "everwell": "A pharmacy chain. Medicines, prices and what is in stock.",
          "onc-centre": "A cancer centre that gives every patient a fixed time, answers questions from its own patient guide, and follows up after each visit."}
KINDS = {"state-phc": "State", "eko-care": "Private", "everwell": "Pharmacy", "onc-centre": "Specialist centre"}


def providers() -> list[dict]:
    """The simulated provider systems: who runs each, what it offers and where its front desk is."""
    from ..health import data

    return [{"slug": slug, "name": n.name, "kind": KINDS.get(slug, "Provider"), "offers": OFFERS.get(slug, ""), "places": len(n.facilities), "desk": f"/synthetic/{slug}/"}
            for slug, n in data.NETWORKS.items()]


def desk_of(provider_name: str) -> str:
    """The front-desk address of a provider named the way the trace names it (its display name); empty if there is no such provider."""
    wanted = (provider_name or "").strip().lower()
    for p in providers():
        if wanted in (p["name"].lower(), p["slug"]):
            return p["desk"]
    return ""


# ---- the steps: what Talk did for one turn, in plain words ------------------------------------------------------------

OPERATIONS = {"search": "find places", "slots": "list free times", "book": "book a time", "cancel": "cancel a visit", "upcoming": "list coming visits",
              "stock": "check stock", "knowledge": "search the patient guide", "visit_status": "check a visit", "request": "pass on to staff",
              "request_status": "check a request"}
# what the model's choice of action means, in the words of a caller's need
WANTS = {"health.find_facility": "to find a clinic, a hospital or a pharmacy", "health.facility_status": "to know how busy a clinic or hospital is",
         "health.available_slots": "to hear the free appointment times", "health.book_appointment": "to book an appointment",
         "health.cancel_appointment": "to cancel an appointment", "health.drug_availability": "to know whether a medicine is in stock",
         "health.ask_the_centre": "an answer from a facility's patient guide", "chat": "only to say hello or thank you",
         "human": "to speak to a person", "health": "help with health services"}
URGENCY_SOURCES = {"floor": "Keyword floor", "model": "Language model", "both": "Keyword floor and language model", "caller": "The caller said so"}
MEANT = {"gave_it": "The caller answered the question.", "earliest": "The caller wants the earliest free time.", "yes": "The caller said yes.",
         "no": "The caller said no.", "something_else": "The caller asked for something different."}
STEPS = {"find_places": "find places near the caller", "medicine": "find the medicine in stock", "free_times": "read the free times at a place",
         "offer_booking": "propose a booking", "confirm_booking": "book the visit the caller agreed to", "cancel_booking": "find the visit to cancel",
         "confirm_cancel": "cancel the visit the caller confirmed", "place_status": "check a place's hours and queue", "ask_care_team": "ask the care team's guide",
         "reply": "answer from what was already said", "person": "pass the caller to a person", "goodbye": "say goodbye", "other": "leave it to the general service"}
REQUEST_KINDS = {"question": "A question for the staff", "person": "A wish to speak to a person", "emergency": "An emergency"}


def pretty_model(name: str | None) -> str:
    """'muse-spark-1.3' becomes 'Muse Spark 1.3'; a name this does not know is shown as it is."""
    name = (name or "").strip()
    m = re.fullmatch(r"(muse(?:-[a-z]+)+)-(\d[\w.]*)", name, re.I)
    return (" ".join(w.capitalize() for w in m.group(1).split("-")) + " " + m.group(2)) if m else name


def _ms(value) -> str:
    return f"{int(value)} ms" if isinstance(value, (int, float)) else ""


def describe_trace(trace: list[dict] | None, show_words: bool = True) -> list[dict]:
    """The trace of one turn as a list of steps, each {kind, title, text, meta, rows, link, at}.

    A step is a name (`title`), one short sentence (`text`) and a small line of facts (`meta`: the model, the time it took, a booking code). The facts are kept apart from
    the sentence so that the trace stays compact, one line for each step, and so that a reader can scan the models and the times down one edge.

    show_words=False leaves out everything that comes from what the caller said or what Talk answered (the words, what was read from them, the place and time
    of a booking); the steps, the models, the numbers and the providers still show. Any run of six or more digits is hidden either way."""
    steps: list[dict] = []
    table = None
    for e in trace or []:
        kind = e.get("step")
        at = e.get("at_ms")
        if kind == "asked":
            if table is None:
                table = {"kind": "asked", "title": "Asked", "text": "", "meta": "", "rows": [], "link": None, "at": at}
                steps.append(table)
            op = str(e.get("op") or "")
            result = scrub(str(e.get("summary") or ""))
            table["rows"].append({"provider": scrub(str(e.get("provider") or "")), "desk": desk_of(e.get("provider") or ""), "op": OPERATIONS.get(op, op.replace("_", " ")), "code": op,
                                  "ms": _ms(e.get("ms")), "ok": bool(e.get("ok", True)), "result": result if e.get("ok", True) else (result or "no answer")})
            continue
        table = None
        step = {"kind": kind, "title": "", "text": "", "meta": "", "rows": None, "link": None, "at": at if isinstance(at, (int, float)) else None}
        if kind == "heard":
            typed = e.get("model") == "typed"
            said = scrub(str(e.get("text") or ""))
            conf = e.get("confidence")
            facts = ["Typed in the box"] if typed else [pretty_model(e.get("model")) or "Speech model", _ms(e.get("ms")), f"confidence {conf:.2f}" if isinstance(conf, (int, float)) else ""]
            step["title"] = "Heard"
            step["text"] = f"“{said}”" if show_words else "The caller's words are not shown here."
            step["meta"] = " · ".join(f for f in facts if f)
        elif kind == "understood":
            step["title"] = "Understood"
            what = WANTS.get(str(e.get("tool") or e.get("action") or ""), "")
            if not what and e.get("answer") in ("yes", "no"):
                what = f"a {e['answer']} to the question Talk had just asked"
            step["text"] = f"The caller wants {what}." if what else "It was not clear what the caller wants."
            step["meta"] = " · ".join(f for f in (pretty_model(e.get("model")) or "Language model", _ms(e.get("ms"))) if f)
        elif kind == "read":
            step["title"] = "Read"
            found = [(label, e.get(key)) for label, key in (("Need", "need"), ("Area", "area"), ("Time", "when"), ("Medicine", "drug"), ("Place", "place")) if e.get(key)]
            if not found:
                step["text"] = "Nothing to look up yet."
            elif show_words:
                step["text"] = " ".join(f"{label}: {scrub(str(v))}." for label, v in found)
            else:
                step["text"] = "The details are not shown here."
        elif kind == "urgency":
            step["title"] = "Urgency"
            level = str(e.get("level") or "")
            step["text"] = ("Someone may be in danger. 112 first, then the nearest hospital with a free emergency place." if level == "emergency"
                            else "It might be an emergency. 112 first, then one question." if level == "possible" else "No sign of danger.")
            step["meta"] = URGENCY_SOURCES.get(str(e.get("source") or ""), "")
        elif kind == "held":
            step["title"] = "Emergency place held"
            where = f" at {scrub(str(e.get('place')))}" if show_words and e.get("place") else ""
            step["text"] = f"{scrub(str(e.get('provider') or 'The provider'))} is keeping an emergency place{where}."
            step["meta"] = f"Hold {scrub(str(e.get('code') or ''))}"
            desk = desk_of(e.get("provider") or "")
            step["link"] = {"label": "Front desk", "href": desk} if desk else None
        elif kind == "decided":
            step["title"] = "Decided"
            step["text"] = f"With the whole call in view, the next step is to {STEPS.get(str(e.get('action')), str(e.get('action') or 'answer'))}."
            found = [(label, e.get(key)) for label, key in (("Area", "area"), ("Place", "place"), ("Time", "when"), ("Medicine", "medicine")) if e.get(key)]
            if found and show_words:
                step["text"] += " " + " ".join(f"{label}: {scrub(str(v))}." for label, v in found)
            step["meta"] = " · ".join(f for f in (pretty_model(e.get("model")) or "Language model", _ms(e.get("ms"))) if f)
        elif kind == "guard":
            step["title"] = "Guard rail"
            step["text"] = "The model's own reply named a fact that was not said in this call, so it was not spoken and the rules answered instead."
            step["meta"] = "Code check · no model"
        elif kind == "meant":
            step["title"] = "Understood"
            step["text"] = MEANT.get(str(e.get("meaning")), "It was not clear what the caller meant by the answer.")
            step["meta"] = " · ".join(f for f in ("Language model", _ms(e.get("ms"))) if f)
        elif kind == "travel":
            step["title"] = "Travel"
            if not show_words:
                step["text"] = "The trip was worked out from the caller's area. The details are not shown here."
            elif e.get("leave_by"):
                step["text"] = f"From {scrub(str(e.get('origin')))}, the trip takes {scrub(str(e.get('trip')))}. Leave by {scrub(str(e.get('leave_by')))} for {scrub(str(e.get('slot')))}."
            else:
                step["text"] = f"From {scrub(str(e.get('origin')))} at {scrub(str(e.get('hour')))}: {scrub(str(e.get('trips')))}."
            step["meta"] = "Lagos traffic by hour · no network call"
        elif kind == "booked":
            step["title"] = "Booked"
            where = f" at {scrub(str(e.get('place')))}, {scrub(str(e.get('when')))}" if show_words and e.get("place") else ""
            step["text"] = f"{scrub(str(e.get('provider') or 'The provider'))} confirmed the visit{where}."
            step["meta"] = f"Booking {scrub(str(e.get('code') or ''))}"
            desk = desk_of(e.get("provider") or "")
            step["link"] = {"label": "Appointment book", "href": desk} if desk else None
        elif kind == "request":
            step["title"] = "Request filed"
            what = REQUEST_KINDS.get(str(e.get("kind")), "A request")
            step["text"] = f"{what}, filed with {scrub(str(e.get('provider') or 'the provider'))}" + (" and marked urgent" if e.get("urgent") else "") + "."
            step["meta"] = f"Request {scrub(str(e.get('code') or ''))}"
            desk = desk_of(e.get("provider") or "")
            step["link"] = {"label": "Staff requests", "href": desk} if desk else None
        elif kind == "replied":
            step["title"] = "Replied"
            action = e.get("action")
            said = scrub(str(e.get("text") or ""))
            step["text"] = f"“{said}”" if show_words else "Talk's reply is not shown here."
            step["meta"] = f"Action: {action}" if action else ""
        else:
            continue
        steps.append(step)
    return steps


def render_steps(steps: list[dict]) -> str:
    """The steps as an HTML list, escaped by the template engine. The Try it page puts this straight into the page."""
    return str(templates.env.get_template("_trace.html").module.render_steps(steps))


def scrub_data(value):
    """A trace (or any data about to leave the server in a response) with every long run of digits hidden, however deep it sits."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {k: scrub_data(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub_data(v) for v in value]
    return value


def install(env) -> None:
    """Give a template environment the filters and globals that the shared templates use, so that the site and the front desks are built in the same shell."""
    env.filters["lagos"] = _lagos
    env.globals["as_of"] = as_of
    env.globals["site_nav"] = site_nav
    env.globals["home_url"] = HOME
    env.globals["asset_v"] = asset_version


def asset_version() -> str:
    """The stylesheets and scripts carry their last-changed time in their address, so a visitor's browser fetches a new file after an update instead of keeping the old one."""
    static = WEB / "static"
    names = ("ci.css", "ci.js", "try.js", "live.js", "desk.css", "desk.js", "onboard.css", "onboard.js")
    return str(int(max((static / n).stat().st_mtime for n in names if (static / n).exists())))


install(templates.env)
