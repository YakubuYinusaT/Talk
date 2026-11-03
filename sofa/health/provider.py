"""One provider system, the other side of Talk's signed HTTP link: a state health network, a private clinic group or a pharmacy chain.

Talk sends a signed JSON message, `list_tools` or `call`, and gets facts back as data: which of this provider's places fit, who is open, how long the queue is,
which slots are free, whether a booking really went through. The provider keeps its own records (store.py) and decides only what is true in its own system.
What to say to the caller, and which provider to ask, is Talk's job. A provider sees a pseudonymous caller reference and never a phone number.
"""

import hashlib
import hmac
import json
import time
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import data, knowledge
from . import desk as desk_page
from .store import HospitalStore
from .when import words

GENERIC = {"clinic", "hospital", "health", "centre", "center", "general", "pharmacy", "medical", "community", "the", "at", "in", "a", "to", "of", "and", "my", "i", "want", "book",
           "an", "appointment", "for", "near", "around", "please", "go", "see", "doctor", "visit", "everwell", "private", "state"}

TOOLS = [
    {"name": "search", "description": "Find this provider's places near a point, by need or by name, with hours, queue and fee",
     "params": [{"name": "lat", "prompt": "Latitude", "required": False}, {"name": "lon", "prompt": "Longitude", "required": False},
                {"name": "need", "prompt": "The service needed", "required": False}, {"name": "query", "prompt": "A place's name", "required": False}]},
    {"name": "slots", "description": "Free appointment times at one of this provider's places",
     "params": [{"name": "facility_id", "prompt": "Which place?", "required": True}]},
    {"name": "book", "description": "Book an appointment at one of this provider's places", "risk": "service",
     "params": [{"name": "facility_id", "prompt": "Which place?", "required": True}, {"name": "start", "prompt": "When?", "required": True}]},
    {"name": "cancel", "description": "Cancel the caller's own appointment", "risk": "service", "params": [{"name": "code", "prompt": "The booking code", "required": True}]},
    {"name": "upcoming", "description": "The caller's own coming appointments with this provider", "params": []},
    {"name": "catalogue", "description": "The products this provider's pharmacies keep: what each is for, the price of a pack, and whether it needs a prescription",
     "params": []},
    {"name": "reserve", "description": "Set packs of a medicine aside at one of this provider's pharmacies for the caller to collect", "risk": "service",
     "params": [{"name": "facility_id", "prompt": "Which pharmacy?", "required": True}, {"name": "drug", "prompt": "Which medicine?", "required": True},
                {"name": "qty", "prompt": "How many packs?", "required": False}]},
    {"name": "stock", "description": "Which of this provider's pharmacies have a medicine in stock",
     "params": [{"name": "drug", "prompt": "Which medicine?", "required": True}]},
    {"name": "knowledge", "description": "Entries from this provider's own patient guide that answer a question",
     "params": [{"name": "query", "prompt": "The question", "required": True}]},
    {"name": "confirm", "description": "Record that the hospital's staff have confirmed a booked visit, so that Talk can tell the patient", "risk": "service",
     "params": [{"name": "code", "prompt": "The booking code", "required": True}]},
    {"name": "visit_status", "description": "What became of one of the caller's own visits: still booked, confirmed by the staff, attended, missed or cancelled",
     "params": [{"name": "code", "prompt": "The booking code", "required": True}]},
    {"name": "request", "description": "Pass something to this provider's staff: a question its guide does not cover, a wish to speak to a person, or an emergency", "risk": "service",
     "params": [{"name": "kind", "prompt": "question, person or emergency", "required": True}, {"name": "summary", "prompt": "What the caller said", "required": True},
                {"name": "urgent", "prompt": "Is it urgent?", "required": False}]},
    {"name": "emergency", "description": "This provider's hospitals that take emergencies, with how many emergency places are free now", "params": []},
    {"name": "emergency_hold", "description": "Keep one emergency place for a caller who could not reach the emergency number", "risk": "service",
     "params": [{"name": "facility_id", "prompt": "Which hospital?", "required": True}]},
    {"name": "request_status", "description": "Whether the staff have answered one of the caller's own requests, and what they said",
     "params": [{"name": "code", "prompt": "The request code", "required": True}]},
]


def sign(secret: str, stamp: str, body: bytes) -> str:
    return hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def ok(**payload) -> dict:
    return {"status": "ok", "say": "", "data": payload}


def refuse(reason: str) -> dict:
    """The provider understood and said no. The reason doubles as `say` so Talk treats it as an answer, not as a broken connection."""
    return {"status": "error", "say": reason, "data": {"reason": reason}}


def name_scores(text: str, pool: list[data.Facility]) -> list[tuple[float, data.Facility]]:
    """The places a caller named, best match first, with how well each matched. Words like clinic or hospital say nothing about which one, so they are ignored, and a word from a place's own
    name counts for more than the area it is in ("Aguda" is an area nickname, but it is also the name of one health centre)."""
    whole = [f for f in pool if " ".join(words(f.name)) == " ".join(words(text))]
    if whole:     # the place's full name, as Talk said it: that place and no other ("Ikorodu Greenfield General Hospital", not the Greenfield clinic too)
        return [(2.0, f) for f in whole]
    tokens = [t for t in words(text) if t not in GENERIC]
    if not tokens:     # only the kind of place ("the general hospital", "a private clinic"): the places of that kind
        said = set(words(text)) | ({"clinic"} if "private" in words(text) else set())
        return [(0.8, f) for f in pool if set(words(f.kind)) and set(words(f.kind)) <= said]
    scored: list[tuple[float, data.Facility]] = []
    for f in pool:
        names = {w for w in words(f.name) if w not in GENERIC}
        places = set(words(f.area)) | {w for a in data.AREAS[f.area].aliases for w in words(a)}
        score = 0.0
        for token in tokens:
            if token in names:
                score += 1.0
            elif token in places:
                score += 0.4
            elif len(token) > 4 and any(SequenceMatcher(None, token, k).ratio() >= 0.85 for k in names if len(k) > 4):
                score += 0.8
        if score:
            scored.append((score, f))
    scored.sort(key=lambda pair: -pair[0])
    best = scored[0][0] if scored else 0.0
    return [(score, f) for score, f in scored if score >= max(best - 0.01, 0.8)]      # naming a place needs a word of its own name, not only its area


def name_matches(text: str, pool: list[data.Facility]) -> list[data.Facility]:
    return [f for _, f in name_scores(text, pool)]


class Provider:
    def __init__(self, network: data.Network, store: HospitalStore):
        self.network, self.store = network, store

    def describe(self, f: data.Facility, now: datetime, km: float | None) -> dict:
        span = self.store.hours_today(f, now)
        opens_next = None
        if not self.store.is_open(f, now) and not f.hours.get(0) == (0, 24):
            for n in range(0, 8):
                day = now.date() + timedelta(days=n)
                hours = f.hours.get(day.weekday())
                if hours and not (n == 0 and now.hour >= hours[1]):
                    opens_next = {"day": day.isoformat(), "hour": hours[0]}
                    break
        people, wait = self.store.queue(f, now)
        return {"id": f.id, "name": f.name, "kind": f.kind, "area": f.area, "address": f.address, "km": None if km is None else round(km, 1), "services": list(f.services),
                "open_now": self.store.is_open(f, now), "all_day": f.hours.get(0) == (0, 24), "closes": span[1] if span and span[0] <= now.hour < span[1] else None,
                "opens_next": opens_next, "emergency": f.emergency, "bookable": f.booking, "fee": f.fee, "waiting": people, "wait_minutes": wait,
                "owner": self.network.owner, "provider": self.network.name, "sms_name": f.sms_name or f.name, "lat": f.lat, "lon": f.lon}

    # ---- the operations ----------------------------------------------------------------------------

    def call(self, tool: str, args: dict, ctx: dict) -> dict:
        handler = {"search": self.search, "slots": self.slots, "book": self.book, "cancel": self.cancel, "upcoming": self.upcoming, "stock": self.stock,
                   "catalogue": self.catalogue, "reserve": self.reserve,
                   "knowledge": self.knowledge, "visit_status": self.visit_status, "request": self.request, "request_status": self.request_status,
                   "confirm": self.confirm, "emergency": self.emergency, "emergency_hold": self.emergency_hold}.get(tool)
        if not handler:
            return refuse("unknown_tool")
        try:
            return handler(args, ctx)
        except (KeyError, ValueError, TypeError):
            return refuse("bad_request")

    def search(self, args: dict, ctx: dict) -> dict:
        now = self.store.clock()
        pool = list(self.store.facilities)
        need, query = str(args.get("need") or ""), str(args.get("query") or "")
        if need == "pharmacy":
            pool = [f for f in pool if f.kind == "pharmacy"]
        elif need:
            pool = [f for f in pool if need in f.services or (need == "emergency care" and f.emergency)]
        if args.get("bookable"):
            pool = [f for f in pool if f.booking]
        if args.get("ids"):
            pool = [f for f in pool if f.id in set(args["ids"])]
        elif not need:
            pool = [f for f in pool if not f.specialist or (query and name_matches(query, [f]))]   # a specialist centre is not a general clinic
        matches: dict[str, float] = {}
        if query:
            scored = name_scores(query, pool)
            matches = {f.id: score for score, f in scored}
            pool = [f for _, f in scored]
        lat, lon = args.get("lat"), args.get("lon")
        if lat is not None and lon is not None:
            ranked = [(f, km) for f, km in self.store.nearest(float(lat), float(lon), pool)]
        else:
            ranked = [(f, None) for f in sorted(pool, key=lambda f: f.name)]
        limit = max(1, min(int(args.get("limit") or 5), 10))
        return ok(facilities=[{**self.describe(f, now, km), **({"match": matches[f.id]} if f.id in matches else {})} for f, km in ranked[:limit]])

    def slots(self, args: dict, ctx: dict) -> dict:
        f = self.store.by_id.get(str(args.get("facility_id") or ""))
        if not f:
            return refuse("unknown_facility")
        now = self.store.clock()
        window = tuple(args["window"]) if args.get("window") else None
        day = date.fromisoformat(args["day"]) if args.get("day") else None
        at = args.get("at")
        found = self.store.next_slots(f, now, max(1, min(int(args.get("count") or 1), 5)), window=window, at=None if at is None else int(at), day=day)
        return ok(facility_id=f.id, slots=[s.isoformat() for s in found], bookable=f.booking)

    def book(self, args: dict, ctx: dict) -> dict:
        caller = str(ctx.get("caller_id") or "")
        f = self.store.by_id.get(str(args.get("facility_id") or ""))
        if not caller:
            return refuse("unknown_caller")
        if not f or not f.booking:
            return refuse("unknown_facility")
        start = datetime.fromisoformat(str(args.get("start")))
        if start < self.store.clock() or (start - self.store.clock()).days > 14:
            return refuse("slot_not_offered")
        visit = str(args.get("visit") or data.GENERAL)
        made = self.store.book(f, start, visit if visit in f.services else data.GENERAL, caller)
        if not made:
            return refuse("taken")
        return ok(appointment={"code": made["code"], "facility_id": f.id, "facility_name": f.name, "starts": start.isoformat(), "visit": made["visit"]})

    def cancel(self, args: dict, ctx: dict) -> dict:
        caller = str(ctx.get("caller_id") or "")
        return ok(cancelled=True) if caller and self.store.cancel(str(args.get("code") or ""), caller) else refuse("not_found")

    def upcoming(self, args: dict, ctx: dict) -> dict:
        caller = str(ctx.get("caller_id") or "")
        found = self.store.upcoming(caller, self.store.clock()) if caller else []
        return ok(appointments=[{"code": a["code"], "facility_id": a["facility_id"], "facility_name": self.store.by_id[a["facility_id"]].name,
                                 "starts": a["starts"].isoformat(), "visit": a["visit"]} for a in found])

    def confirm(self, args: dict, ctx: dict) -> dict:
        """The hospital's staff accept a booking (the front desk's Confirm button does the same). Talk learns of it by asking about the visit, and then texts the patient."""
        return ok(confirmed=True, code=str(args.get("code") or "")) if self.store.confirm(str(args.get("code") or "")) else refuse("not_found")

    def guide(self) -> tuple[tuple, str] | None:
        """This provider's patient guide and how it is labelled: its own when it has one, the sample guide for the cancer centre, and none for the others."""
        if self.network.guide:
            return self.network.guide, self.network.guide_source or knowledge.SOURCE
        if self.network.slug == "onc-centre":
            return knowledge.ENTRIES, knowledge.SOURCE
        return None

    def knowledge(self, args: dict, ctx: dict) -> dict:
        """Entries from this provider's patient guide, if it has one. Talk answers only from what comes back; an empty list means the guide does not cover it."""
        held = self.guide()
        if not held:
            return ok(entries=[])
        entries, source = held
        sms_name = next((f.sms_name for f in self.network.facilities if f.sms_name), self.network.name)
        found = knowledge.search(str(args.get("query") or ""), max(1, min(int(args.get("limit") or 3), 5)), entries=entries, source=source)
        return ok(entries=found, provider=self.network.name, sms_name=sms_name)

    def visit_status(self, args: dict, ctx: dict) -> dict:
        caller = str(ctx.get("caller_id") or "")
        found = self.store.visit(str(args.get("code") or ""), caller) if caller else None
        if not found:
            return refuse("not_found")
        return ok(code=found["code"], status=found["status"], starts=found["starts"].isoformat(), facility_name=self.store.by_id[found["facility_id"]].name, visit=found["visit"])

    def request(self, args: dict, ctx: dict) -> dict:
        """A request for this provider's staff. It carries the caller's reference and what they said, never a phone number."""
        caller = str(ctx.get("caller_id") or "")
        kind = str(args.get("kind") or "")
        summary = " ".join(str(args.get("summary") or "").split())
        if not caller or not summary or kind not in self.store.REQUEST_KINDS:
            return refuse("bad_request")
        return ok(request=self.store.add_request(kind, bool(args.get("urgent")), summary, caller))

    def emergency(self, args: dict, ctx: dict) -> dict:
        """The hospitals that take emergencies, each with the places it keeps for them and how many are free now. Nearest first when Talk says where from."""
        now = self.store.clock()
        pool = [f for f in self.store.facilities if f.emergency]
        lat, lon = args.get("lat"), args.get("lon")
        ranked = self.store.nearest(float(lat), float(lon), pool) if lat is not None and lon is not None else [(f, None) for f in pool]
        return ok(facilities=[{**self.describe(f, now, km), "places": f.emergency_places, "places_free": self.store.places_free(f)} for f, km in ranked])

    def emergency_hold(self, args: dict, ctx: dict) -> dict:
        """Keeps an emergency place for the caller (known here only by a reference, never a phone number) and puts it at the top of the front desk."""
        caller = str(ctx.get("caller_id") or "")
        f = self.store.by_id.get(str(args.get("facility_id") or ""))
        if not caller or f is None or not f.emergency:
            return refuse("bad_request")
        held = self.store.hold(f, caller)
        if held is None:
            return refuse("full")
        return ok(hold={**held, "facility_id": f.id, "name": f.name, "address": f.address})

    def request_status(self, args: dict, ctx: dict) -> dict:
        caller = str(ctx.get("caller_id") or "")
        found = self.store.request(str(args.get("code") or ""), caller) if caller else None
        if not found:
            return refuse("not_found")
        return ok(request=found)

    def reserve(self, args: dict, ctx: dict) -> dict:
        """Sets packs aside for the caller (known here only by a reference) and shows the order on the pharmacy's front desk."""
        caller = str(ctx.get("caller_id") or "")
        f = self.store.by_id.get(str(args.get("facility_id") or ""))
        drug = self.store.find_drug(str(args.get("drug") or ""))
        if not caller or f is None or f.kind != "pharmacy" or drug is None:
            return refuse("bad_request")
        order = self.store.reserve(f, drug, caller, int(args.get("qty") or 1))
        if order is None:
            return refuse("out_of_stock")
        return ok(order={**order, "pharmacy": f.name, "address": f.address})

    def catalogue(self, args: dict, ctx: dict) -> dict:
        """Every product this provider's pharmacies keep, as its own catalogue describes it. A provider with no pharmacy keeps none."""
        if not any(f.kind == "pharmacy" for f in self.store.facilities):
            return ok(products=[])
        return ok(products=[{"name": d.name, "use": data.USES.get(d.id, ""), "price": d.price, "prescription": d.prescription} for d in data.DRUGS])

    def stock(self, args: dict, ctx: dict) -> dict:
        now = self.store.clock()
        drug = self.store.find_drug(str(args.get("drug") or ""))
        if not drug:
            return ok(drug=None, pharmacies=[])
        lat, lon = args.get("lat"), args.get("lon")
        pharmacies = self.store.pharmacies_with(drug)
        ranked = self.store.nearest(float(lat), float(lon), pharmacies) if lat is not None and lon is not None else [(f, None) for f in pharmacies]
        out = []
        for f, km in ranked[:6]:
            row = self.describe(f, now, km)
            row["qty"], row["price"] = self.store.packs_left(f.id, drug.id), drug.price
            out.append(row)
        return ok(drug={"id": drug.id, "name": drug.name, "price": drug.price, "prescription": drug.prescription}, pharmacies=out)


# ---- the web service ------------------------------------------------------------------------------------------


def create_provider_app(network: data.Network, secret: str, store: HospitalStore | None = None, desk_key: str = "", owner=None, extras=None, texts=None,
                        payments=None) -> FastAPI:
    """`desk_key` lets the front desk confirm and mark visits and answer requests from its page (open the page with ?key=...). Empty: the page only shows the book.
    A hospital made in the onboarding wizard also passes `owner`, a function that says whether a request comes from the visitor it was made for (its page is then shown
    to that visitor alone, with staff access, and to anyone who brings the desk key), and `extras`, a function that gives the page what is particular to that hospital.
    `texts` is Talk's record of the texts it sent, asked by reference (sofa/services/notify.py), so the desk can show each one and whether it arrived, and
    `payments` is Talk's record of what each patient was asked to pay by transfer (sofa/services/payments.py), so the desk can show whether it has arrived."""
    store = store or HospitalStore(facilities=network.facilities)
    provider = Provider(network, store)
    app = FastAPI(title=network.name, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.provider = store, provider

    def verified(request: Request, body: bytes) -> None:
        stamp = request.headers.get("x-sofa-timestamp", "")
        good = stamp.isdigit() and abs(time.time() - int(stamp)) <= 300  # an old message cannot be sent again later
        if not (good and hmac.compare_digest(sign(secret, stamp, body), request.headers.get("x-sofa-signature", ""))):
            raise HTTPException(status_code=401, detail="bad signature")

    @app.post("/rpc")
    async def rpc(request: Request):
        body = await request.body()
        verified(request, body)
        try:
            message = json.loads(body)
        except ValueError:
            raise HTTPException(status_code=400, detail="not JSON") from None
        if message.get("op") == "list_tools":
            return {"tools": TOOLS}
        if message.get("op") == "call":
            return provider.call(str(message.get("tool") or ""), message.get("arguments") or {}, message.get("context") or {})
        raise HTTPException(status_code=400, detail="unknown operation")

    def staff(request: Request, key: str) -> bool:
        """Whether this request may act as the hospital's staff: it brings the desk key, or it comes from the visitor this hospital was made for."""
        return desk_page.key_matches(key, desk_key) or bool(owner and owner(request))

    @app.post("/desk/mark")
    async def mark(request: Request):
        form = await request.form()
        if not staff(request, str(form.get("key", ""))):
            raise HTTPException(status_code=403, detail="the desk key is needed")
        store.mark(str(form.get("code", "")), str(form.get("outcome", "")))
        return RedirectResponse(f"../?key={form.get('key', '')}", status_code=303)

    @app.post("/desk/confirm")
    async def confirm(request: Request):
        form = await request.form()
        if not staff(request, str(form.get("key", ""))):
            raise HTTPException(status_code=403, detail="the desk key is needed")
        store.confirm(str(form.get("code", "")))
        return RedirectResponse(f"../?key={form.get('key', '')}", status_code=303)

    @app.post("/desk/reply")
    async def reply(request: Request):
        form = await request.form()
        if not staff(request, str(form.get("key", ""))):
            raise HTTPException(status_code=403, detail="the desk key is needed")
        store.reply_request(str(form.get("code", "")), str(form.get("reply", "")))
        return RedirectResponse(f"../?key={form.get('key', '')}", status_code=303)

    @app.get("/", response_class=HTMLResponse)
    def desk(request: Request, key: str = "", embed: str = ""):
        """This provider's front desk: the requests for its care team, the appointment book, the queues and, where it has them, its stock list or patient guide.
        Made-up data, labelled as such. The page is never kept by a browser or a proxy, because a desk that shows an old queue is worse than no desk."""
        allowed = staff(request, key)
        if owner and not allowed:   # a hospital made for one visitor is not shown to anybody else
            raise HTTPException(status_code=404)
        page = desk_page.render(provider.network, store, desk_key, key, staff=allowed,
                                extras={"embedded": embed == "1", **(extras(request) if extras else {})}, texts=texts, payments=payments)
        return HTMLResponse(page, headers={"Cache-Control": "no-store"})

    return app
