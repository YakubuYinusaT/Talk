"""The front desk of one provider system: the page its staff keep open all day.

The page is built only from the provider's own records (store.py) and its fixed lists (data.py and knowledge.py), so it shows exactly what Talk reads when it
speaks to a caller on that provider's behalf. This module gathers those records into plain values and hands them to a template; all the markup lives in
sofa/web/templates/desk, and all the styling and behaviour in sofa/web/static/desk.css and desk.js.
"""

import hmac
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..web import ui
from . import data, knowledge
from .store import HospitalStore

WEB = Path(__file__).resolve().parent.parent / "web"
# The loader looks in the desk's own folder first and then in the shared templates, so that a desk page extends the same base.html and uses the same components (_ui.html)
# as every page of the site. ui.install gives this environment the menu and the asset version that those templates expect.
TEMPLATES = Environment(loader=FileSystemLoader([str(WEB / "templates" / "desk"), str(WEB / "templates")]), autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
ui.install(TEMPLATES)

# Each provider has its own identity inside one shared design: a name for its kind of place, an accent colour (defined in ci.css) and a mark. A provider this table does not know
# falls back to a neutral identity, so that a new provider never breaks the page.
IDENTITY = {
    "state-phc": {"type": "State primary health centre", "accent": "green", "mark": "centre"},
    "eko-care": {"type": "Private clinic", "accent": "blue", "mark": "clinic"},
    "everwell": {"type": "Pharmacy", "accent": "teal", "mark": "pharmacy"},
    "onc-centre": {"type": "Cancer centre", "accent": "purple", "mark": "ribbon"},
}
NEUTRAL = {"type": "Health provider", "accent": "green", "mark": "plain"}

STATUS = {"booked": "Booked", "confirmed": "Confirmed", "attended": "Attended", "no_show": "Did not come"}
KINDS = {"question": ("Question", "question"), "person": ("Speak to a person", "person"), "emergency": ("Emergency", "siren")}
URGENT_ENTRY = "urgent-signs"          # the patient guide entry that lists the warning signs


def key_matches(given: str, secret: str) -> bool:
    """Whether the desk key is the right one. Both sides are compared as bytes, so that a key with an unusual character is refused rather than causing an error."""
    return bool(secret) and hmac.compare_digest(given.encode(), secret.encode())


def age_words(then: datetime, now: datetime) -> str:
    """How long ago something happened, the way a person would say it."""
    seconds = max(0, int((now - then).total_seconds()))
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            n = seconds // size
            return f"{n} {unit}{'' if n == 1 else 's'} ago"
    return "just now"


def day_label(day, today) -> str:
    """The heading of one day in the appointment book."""
    if day == today:
        return f"Today, {day:%A} {day.day} {day:%B}"
    if (day - today).days == 1:
        return f"Tomorrow, {day:%A} {day.day} {day:%B}"
    return f"{day:%A} {day.day} {day:%B}"


def hours_words(store: HospitalStore, f: data.Facility, now: datetime) -> str:
    span = store.hours_today(f, now)
    if not span:
        return "Closed today"
    if span == (0, 24):
        return "All day and night"
    return f"{span[0]:02d}:00 to {span[1]:02d}:00"


def places_of(store: HospitalStore, now: datetime) -> list[dict]:
    rows = []
    for f in store.facilities:
        people, wait = store.queue(f, now)
        rows.append({"id": f.id, "name": f.name, "kind": f.kind, "area": f.area, "open": store.is_open(f, now), "hours": hours_words(store, f, now), "emergency": f.emergency,
                     "people": people, "wait": wait, "fee": f.fee, "bookable": f.booking})
    return rows


def visits_of(store: HospitalStore, now: datetime) -> tuple[list[dict], int, int]:
    """The appointment book from today on, grouped by day, each visit with the words and flags the page needs, then how many visits today and how many of those are still to be marked."""
    days: dict = {}
    today_total = today_unmarked = 0
    for r in store.booked_on(now):
        when = datetime.fromisoformat(r["starts"])
        passed = r["status"] in ("booked", "confirmed") and when < now
        if when.date() == now.date():
            today_total += 1
            today_unmarked += 1 if passed else 0
        days.setdefault(when.date(), []).append({"code": r["code"], "place": store.by_id[r["facility_id"]].name, "place_id": r["facility_id"], "time": f"{when:%H:%M}", "visit": r["visit"],
                                                 "ref": r["caller_ref"][:8], "status": r["status"], "label": STATUS.get(r["status"], r["status"]), "passed": passed})
    groups = [{"label": day_label(day, now.date()), "iso": day.isoformat(), "visits": visits} for day, visits in sorted(days.items())]
    return groups, today_total, today_unmarked


def requests_of(store: HospitalStore, now: datetime) -> tuple[list[dict], list[dict]]:
    """The requests for the care team: those still waiting (urgent first, then the oldest) and those answered recently."""
    waiting, answered = [], []
    for r in store.requests(60):
        label, icon = KINDS.get(r["kind"], (r["kind"].capitalize(), "question"))
        row = {"code": r["code"], "kind": label, "icon": icon, "urgent": bool(r["urgent"]) and r["status"] == "open", "summary": r["summary"], "ref": r["caller_ref"][:8],
               "age": age_words(datetime.fromisoformat(r["created"]), now), "reply": r["reply"],
               "replied": age_words(datetime.fromisoformat(r["replied"]), now) if r["replied"] else ""}
        (waiting if r["status"] == "open" else answered).append(row)
    return waiting, answered


def stock_of(store: HospitalStore) -> dict | None:
    """What each pharmacy holds of each medicine, for a provider that has pharmacies. The numbers are made up but steady (data.stock_level)."""
    pharmacies = [f for f in store.facilities if f.kind == "pharmacy"]
    if not pharmacies:
        return None
    rows = []
    for drug in data.DRUGS:
        held = [{"area": f.area, "qty": data.stock_level(f.id, drug.id)} for f in pharmacies]
        rows.append({"name": drug.name, "price": drug.price, "prescription": drug.prescription, "held": held, "places_with": sum(1 for h in held if h["qty"] > 0)})
    # The areas become the column headings of the stock table, in the same order as the figures in every row.
    return {"rows": rows, "areas": [f.area for f in pharmacies], "places": len(pharmacies), "lines_in_stock": sum(1 for r in rows if r["places_with"] > 0)}


def build(network: data.Network, store: HospitalStore, desk_key: str, key: str, staff: bool = False, extras: dict | None = None) -> dict:
    """Everything the template needs for one view of the desk. `key` is what the visitor put in the address; only a right key gives the staff buttons, and so does
    `staff`, which says that the request comes from the visitor a hospital made in the onboarding wizard belongs to. `extras` is what is particular to such a hospital."""
    now = store.clock()
    identity = IDENTITY.get(network.slug) or IDENTITY.get(network.profile, NEUTRAL)
    marking = staff or key_matches(key, desk_key)
    access = "staff" if marking else "off" if not desk_key else "wrong" if key else "read"
    places = places_of(store, now)
    groups, today_total, today_unmarked = visits_of(store, now)
    waiting, answered = requests_of(store, now)
    stock = stock_of(store)
    urgent = sum(1 for r in waiting if r["urgent"])
    people = sum(p["people"] for p in places if p["open"])
    if stock:
        second = {"id": "stock", "label": "Medicines in stock", "figure": f"{stock['lines_in_stock']} of {len(stock['rows'])}"}
    else:
        second = {"id": "visits", "label": "Visits today", "figure": today_total, "note": f"{today_unmarked} to mark" if today_unmarked else ""}
    tiles = [
        {"id": "waiting", "label": "People waiting", "figure": people},
        second,
        {"id": "open", "label": "Open requests", "figure": len(waiting)},
        {"id": "urgent", "label": "Urgent requests", "figure": urgent, "alert": bool(urgent)},
    ]
    guide = None
    entries, source = (network.guide, network.guide_source or knowledge.SOURCE) if network.guide else (knowledge.ENTRIES, knowledge.SOURCE) if network.slug == "onc-centre" else ((), "")
    if entries:
        warning = next((e for e in entries if e.id == URGENT_ENTRY), None)
        guide = {"entries": [e for e in entries if e.id != URGENT_ENTRY], "warning": warning, "source": source, "sample": not network.demo}
    return {"name": network.name.replace(" (simulated)", ""), "slug": network.slug, "identity": identity, "now": now, "clock": f"{now:%A} {now.day} {now:%B}, {now:%H:%M}",
            "access": access, "marking": marking, "key": key if marking else "", "tiles": tiles, "places": places,
            "groups": groups, "bookable": any(p["bookable"] for p in places), "waiting": waiting, "answered": answered, "urgent": urgent, "stock": stock, "guide": guide,
            "book_places": sorted({(v["place_id"], v["place"]) for g in groups for v in g["visits"]}, key=lambda pair: pair[1]),
            "demo": network.demo, "assistant": None, "embedded": False, **(extras or {})}


def render(network: data.Network, store: HospitalStore, desk_key: str, key: str, staff: bool = False, extras: dict | None = None) -> str:
    return TEMPLATES.get_template("desk.html").render(**build(network, store, desk_key, key, staff, extras))
