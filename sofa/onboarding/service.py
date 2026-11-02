"""Hospitals made at run time by the onboarding wizard, and everything that keeps them apart, safe and temporary.

A hospital made in the wizard is a real provider system, not a picture of one. It has its own secret, its own database file (its appointment book), and its own web app that
speaks the same signed contract as the four simulated systems (sofa/health/provider.py). When the visitor presses "Go live", Talk is told about it at once, with no restart:
the health front desk then finds it, searches it and books into it through the normal path. Nothing in Talk is written for any one hospital.

  * Scope: a hospital is shown to the visitor who made it (a signed cookie, sofa/onboarding/visitor.py), and to the phone number that visitor gave with their consent. Nobody
    else is told that it exists, and its front desk page answers 404 to everybody else.
  * Lifetime: it is kept in Talk's database so that a restart does not lose it, it expires after DEMO_ONBOARDING_HOURS, and the scheduler removes it, its secret and its files.
  * Limits: only so many hospitals may exist at once, and one address may only start so many in an hour.
  * Safety: the data is made up, free text is checked and limited (hospital_profile.py), no phone number reaches a provider (callers are only a reference), and the secret is never
    logged. It is shown to its owner only in a masked control.
"""

import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from starlette.routing import Mount

from ..health import provider as provider_module
from ..health import speak
from ..health.links import ProviderError, ProviderSpec, ToolSpec
from ..health.store import HospitalStore
from ..health.when import lagos_now, say_day, say_time
from ..models import DemoHospital
from ..services.notify import TEST_PREFIX
from ..textutil import e164
from . import hospital_profile
from . import visitor as who

log = logging.getLogger("sofa.onboarding")
SAMPLE_BOOKINGS = 4
STEP_AFTER_CREATION = 2     # a hospital that has just been started is on step 2 of the wizard


class Refused(Exception):
    """A new hospital cannot be started right now. The message is a full, polite sentence for the visitor."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@dataclass
class Entry:
    """What Talk and the provider apps need to know about one hospital that exists at run time, held in memory so that every turn of every call can ask quickly."""
    slug: str
    visitor: str
    expires_at: datetime
    spec: ProviderSpec
    assistant: dict | None = None
    live: bool = False                 # Talk may use it: set by "Go live", and again after a restart
    owner_phone: str | None = None     # the visitor's own number, only if they gave it and ticked the consent box


def aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def domain_of(slug: str) -> str:
    return "health_" + slug.replace("-", "_")


class Onboarding:
    def __init__(self, app, svc, clock=lagos_now):
        self.app, self.svc, self.settings = app, svc, svc.settings
        self.clock = clock                     # the hospitals' own clock (Lagos time); the tests fix it
        self.entries: dict[str, Entry] = {}
        self.apps: dict = {}
        self.mounts: dict = {}

    # ---- time, visitors and addresses ------------------------------------------------------------------

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    @property
    def key(self) -> str:
        return self.settings.at_callback_secret

    def visitor_of(self, request) -> str | None:
        return who.read(request.cookies, self.key)

    def hash_address(self, ip: str) -> str:
        return hashlib.sha256(f"address|{ip}|{self.key}".encode()).hexdigest()[:40]

    # ---- what Talk may use -----------------------------------------------------------------------------------

    def specs_for(self, visitor: str | None, phone: str | None) -> list[ProviderSpec]:
        """The hospitals made in the wizard that this asker may be told about: the ones made for this visitor, and the ones whose owner gave this phone number."""
        now = self.now()
        return [e.spec for e in self.entries.values() if e.live and e.expires_at > now
                and ((visitor and e.visitor == visitor) or (phone and e.owner_phone and e.owner_phone == phone))]

    def spec_of(self, domain: str) -> ProviderSpec | None:
        """A hospital by its service domain, for the scheduler's follow-ups after the call that booked a visit has ended."""
        now = self.now()
        return next((e.spec for e in self.entries.values() if e.spec.domain == domain and e.expires_at > now), None)

    def any_live(self) -> bool:
        return any(e.live for e in self.entries.values())

    def confirmation_phone(self, domain: str, caller_phone: str) -> str:
        """Where the text that says the hospital confirmed a visit goes. A conversation typed in the browser has a reserved number that no text is ever sent to; a visitor who gave
        their own number, and ticked the box that says so, is texted there instead. A real caller is always texted on the number they called from."""
        entry = next((e for e in self.entries.values() if e.spec.domain == domain), None)
        if entry and entry.owner_phone and caller_phone.startswith(TEST_PREFIX):
            return entry.owner_phone
        return caller_phone

    # ---- finding and keeping a visitor's hospital ----------------------------------------------------------

    def hospital_of(self, db, visitor: str | None) -> DemoHospital | None:
        if not visitor:
            return None
        row = db.scalar(select(DemoHospital).where(DemoHospital.visitor == visitor, DemoHospital.state != "retired").order_by(DemoHospital.created_at.desc()))
        return row if row and aware(row.expires_at) > self.now() else None

    def save(self, db, row: DemoHospital, profile: dict | None = None, **fields) -> DemoHospital:
        """Keep a change. The profile is replaced as a whole, so that the database notices it changed."""
        if profile is not None:
            row.profile = profile
        for name, value in fields.items():
            setattr(row, name, value)
        db.commit()
        return row

    def event(self, db, row: DemoHospital, name: str) -> None:
        """Remember when part of the journey first happened, for the summary at the end."""
        events = row.profile.get("events", {})
        if name not in events:
            self.save(db, row, {**row.profile, "events": {**events, name: self.now().isoformat()}})

    def create(self, db, visitor: str, ip: str, template: str) -> DemoHospital:
        """Start a hospital from a template. Refused politely when too many are alive, or when this address has started too many in the last hour. A visitor has one hospital at a
        time: starting another removes the first, with its data."""
        if template not in hospital_profile.TEMPLATES:
            raise hospital_profile.Invalid("Please choose one of the three templates.")
        now = self.now()
        address = self.hash_address(ip)
        recent = db.scalar(select(func.count(DemoHospital.id)).where(DemoHospital.ip_hash == address, DemoHospital.created_at > now - timedelta(hours=1))) or 0
        if recent >= self.settings.demo_onboarding_per_address_per_hour:
            raise Refused(429, "You have started several demonstration hospitals in the last hour, which is the most that one network may start. Please try again a little later.")
        mine = list(db.scalars(select(DemoHospital).where(DemoHospital.visitor == visitor, DemoHospital.state != "retired")))
        active = db.scalar(select(func.count(DemoHospital.id)).where(DemoHospital.state != "retired", DemoHospital.expires_at > now)) or 0
        if active - len(mine) >= self.settings.demo_onboarding_max_active:
            raise Refused(503, "Every demonstration hospital is in use at the moment. Each one is removed 24 hours after it was made, so please try again in a little while.")
        for old in mine:
            self.retire(db, old)
        profile = hospital_profile.new_profile(template)
        profile["events"] = {"created": now.isoformat()}
        row = DemoHospital(visitor=visitor, slug="demo-" + secrets.token_hex(4), template=template, ip_hash=address, state="draft", step=STEP_AFTER_CREATION, profile=profile,
                           expires_at=now + timedelta(hours=self.settings.demo_onboarding_hours))
        db.add(row)
        db.commit()
        return row

    # ---- the hospital as a running provider ----------------------------------------------------------------

    def spec_for(self, row: DemoHospital) -> ProviderSpec:
        domain = domain_of(row.slug)
        tools = tuple(ToolSpec(f"{domain}.{t['name']}", t["name"], t["description"]) for t in provider_module.TOOLS)
        config = tuple(sorted({"group": "health", "kind": "clinics", "owner": row.profile["owner"], "scope": "visitor"}.items()))
        return ProviderSpec(domain, row.profile["name"], self.settings.provider_endpoint(row.slug), row.secret or "", config, tools)

    def database_path(self, slug: str) -> str:
        folder = Path(self.settings.hospital_db_dir or self.settings.storage_dir)
        return ":memory:" if str(folder) == ":memory:" else str(folder / f"provider_{slug}.db")

    def is_owner(self, request, slug: str) -> bool:
        entry = self.entries.get(slug)
        return bool(entry and entry.visitor and self.visitor_of(request) == entry.visitor)

    def desk_extras(self, slug: str) -> dict:
        entry = self.entries.get(slug)
        return {"back": {"href": "/onboard/step/7", "label": "Back to the wizard", "long": "Back to the onboarding wizard"}, "assistant": entry.assistant if entry else None}

    def seed(self, store: HospitalStore, facility) -> None:
        """Fill the appointment book with a few made-up visits tomorrow morning, as if the hospital's paper book had just been copied into it."""
        now = store.clock()
        slots = []
        for ahead in range(1, 5):
            slots += [s for s in store.free_slots(facility, now.date() + timedelta(days=ahead), now) if 9 <= s.hour < 12]
            if len(slots) >= SAMPLE_BOOKINGS:
                break
        visits = [s for s in facility.services if s != "emergency care"] or ["general consultation"]
        for i, slot in enumerate(slots[:SAMPLE_BOOKINGS]):
            store.book(facility, slot, visits[i % len(visits)], f"sample-{i + 1}-{facility.id}")

    def ensure_provider(self, row: DemoHospital, fresh: bool = True) -> None:
        """Make the hospital run, or bring a running one up to date with what the visitor has since changed. Nothing is restarted."""
        network = hospital_profile.network_of(row.profile, row.slug, row.template)
        entry = self.entries.get(row.slug)
        if row.slug in self.apps:
            provider = self.apps[row.slug].state.provider
            provider.network = network
            provider.store.facilities = network.facilities
            provider.store.by_id = {f.id: f for f in network.facilities}
        else:
            folder = Path(self.settings.hospital_db_dir or self.settings.storage_dir)
            if str(folder) != ":memory:":
                folder.mkdir(parents=True, exist_ok=True)
            store = HospitalStore(self.database_path(row.slug), clock=lambda: self.clock(), facilities=network.facilities)
            if fresh and row.profile.get("samples"):
                self.seed(store, network.facilities[0])
            app = provider_module.create_provider_app(network, row.secret or "", store, row.desk_key or "", owner=lambda request, slug=row.slug: self.is_owner(request, slug),
                                                      extras=lambda request, slug=row.slug: self.desk_extras(slug))
            mount = Mount(f"/synthetic/{row.slug}", app=app)
            self.app.router.routes = [*self.app.router.routes, mount]     # a new list, so that a request being routed at this moment is not disturbed
            self.apps[row.slug], self.mounts[row.slug] = app, mount
            self.svc.provider_links.register_local(domain_of(row.slug), app)
        self.entries[row.slug] = Entry(row.slug, row.visitor, aware(row.expires_at), self.spec_for(row), row.profile.get("assistant"),
                                       entry.live if entry else row.state == "live", row.owner_phone if row.phone_consent_at else None)

    def connect(self, db, row: DemoHospital) -> DemoHospital:
        """Step 5: the signed connection. The hospital gets a fresh secret of its own the first time, and starts running with its own database."""
        if not row.secret:
            row.secret = secrets.token_hex(32)
            db.commit()
        self.ensure_provider(row)
        self.event(db, row, "connected")
        return row

    def go_live(self, db, row: DemoHospital, phone: str | None = None) -> DemoHospital:
        """Step 6: Talk starts using the hospital now. With the visitor's consent and number, calls from that phone also see it."""
        self.ensure_provider(row)
        self.save(db, row, state="live", step=max(row.step, 7), owner_phone=phone, phone_consent_at=self.now() if phone else None)
        self.entries[row.slug].live = True
        self.entries[row.slug].owner_phone = phone
        self.event(db, row, "live")
        return row

    def sync(self, row: DemoHospital) -> None:
        """The visitor changed something after the connection was made: the running hospital follows."""
        if row.slug in self.apps:
            self.ensure_provider(row, fresh=False)

    def phone_of(self, phone: str) -> str:
        """The visitor's own number, in the form Talk knows callers by. The numbers reserved for typed conversations are refused: they are never texted."""
        number = e164(phone)
        if not number or not number[1:].isdigit() or not 10 <= len(number) - 1 <= 15:
            raise hospital_profile.Invalid("Please write your phone number with its area code, for example 0803 000 0000, or leave it empty and tick nothing.")
        if number.startswith(TEST_PREFIX):
            raise hospital_profile.Invalid("That number is kept for the typed conversations, which are never sent any text. Please write your own number, or leave it empty.")
        return number

    # ---- removing hospitals --------------------------------------------------------------------------------

    def destroy_runtime(self, slug: str) -> None:
        """Stop the hospital: Talk forgets it, its address is closed and its records are deleted. The row in Talk's database is dealt with by the caller."""
        entry, app, mount = self.entries.pop(slug, None), self.apps.pop(slug, None), self.mounts.pop(slug, None)
        if mount is not None:
            self.app.router.routes = [r for r in self.app.router.routes if r is not mount]
        if entry:
            self.svc.provider_links.unregister_local(entry.spec.domain)
        if app is not None:
            try:
                app.state.store.db.close()
            except Exception:
                log.warning("the records of %s could not be closed", slug)
        path = self.database_path(slug)
        if path != ":memory:":
            for suffix in ("", "-wal", "-shm"):
                try:
                    Path(path + suffix).unlink(missing_ok=True)
                except OSError:
                    log.warning("a record file of %s could not be deleted", slug)

    def retire(self, db, row: DemoHospital) -> None:
        """A visitor who starts another hospital gives up the first. Its data and secret are gone; a bare row stays until it would have expired, so that the limit per address holds."""
        self.destroy_runtime(row.slug)
        self.save(db, row, {"retired": True}, state="retired", secret=None, desk_key=None, owner_phone=None, phone_consent_at=None)

    def sweep(self) -> int:
        """Remove every hospital whose time is up. The scheduler runs this on every pass. Returns how many were removed."""
        now = self.now()
        removed = 0
        with self.svc.session_factory() as db:
            for row in list(db.scalars(select(DemoHospital).where(DemoHospital.expires_at <= now))):
                self.destroy_runtime(row.slug)
                db.delete(row)
                removed += 1
            db.commit()
        for slug in [s for s, e in self.entries.items() if e.expires_at <= now]:
            self.destroy_runtime(slug)
        if removed:
            log.info("%d demonstration hospital(s) removed because their time was up", removed)
        return removed

    def restore(self) -> int:
        """After a restart: every hospital that has not expired runs again, with the appointment book it had."""
        count = 0
        with self.svc.session_factory() as db:
            for row in db.scalars(select(DemoHospital).where(DemoHospital.state != "retired", DemoHospital.expires_at > self.now())):
                if row.secret:
                    self.ensure_provider(row, fresh=False)
                    count += 1
        return count

    # ---- the signed connection, tried out ---------------------------------------------------------------------

    async def test_connection(self, db, row: DemoHospital) -> dict:
        """Two real signed requests through the same code that Talk uses on every call. The first is a correctly signed question, which the hospital must answer. The second is signed
        with a wrong secret, which the hospital must refuse. Both the answer and the refusal are what a visitor should see."""
        spec, links = self.spec_for(row), self.svc.provider_links
        checks = []
        started = time.perf_counter()
        try:
            result = await links.call(db, spec, ToolSpec(f"{spec.domain}.search", "search"), {"ids": [row.slug], "limit": 1}, {"phone": "connection-test", "call_id": None})
            places = result.data.get("facilities") or []
            ms = int((time.perf_counter() - started) * 1000)
            good = result.ok and len(places) == 1
            checks.append({"title": "A correctly signed question", "ok": good, "ms": ms,
                           "text": (f"The hospital answered in {ms} milliseconds. It reported one place, {places[0]['name']}, and said that it is " + ("open now." if places[0].get("open_now") else "closed now.")) if good
                           else "The hospital answered, but not with the place that was expected."})
        except ProviderError as exc:
            checks.append({"title": "A correctly signed question", "ok": False, "ms": None, "text": f"Talk could not get an answer from the hospital: {exc}."})
        started = time.perf_counter()
        try:
            await links.call(db, replace(spec, signing_secret=secrets.token_hex(16)), ToolSpec(f"{spec.domain}.search", "search"), {"ids": [row.slug], "limit": 1}, {"phone": "connection-test", "call_id": None})
            checks.append({"title": "A question signed with a wrong secret", "ok": False, "ms": None, "text": "The hospital answered a request that was signed with the wrong secret, which it must never do."})
        except ProviderError as exc:
            checks.append({"title": "A question signed with a wrong secret", "ok": "401" in str(exc), "ms": int((time.perf_counter() - started) * 1000),
                           "text": "The hospital refused it, as it should. Only a request signed with this hospital's own secret is answered." if "401" in str(exc) else f"The request failed, but not in the expected way: {exc}."})
        outcome = {"ok": all(c["ok"] for c in checks), "checks": checks, "at": self.now().isoformat()}
        self.save(db, row, {**row.profile, "connection": outcome})
        return outcome

    async def glimpse(self, db, row: DemoHospital) -> dict | None:
        """What Talk itself reads from the hospital, asked the way a call asks it (the same signed request), and said the way Talk would say it."""
        spec = self.spec_for(row)
        area = hospital_profile.data.AREAS[row.profile["area"]]
        started = time.perf_counter()
        try:
            result = await self.svc.provider_links.call(db, spec, ToolSpec(f"{spec.domain}.search", "search"), {"lat": area.lat, "lon": area.lon, "limit": 1, "need": row.profile["services"][0]},
                                                        {"phone": "connection-test", "call_id": None})
        except ProviderError:
            return None
        places = result.data.get("facilities") or []
        if not places:
            return None
        return {"text": speak.place_line(places[0], self.clock()), "ms": int((time.perf_counter() - started) * 1000)}

    # ---- the journey, as it stands ------------------------------------------------------------------------

    def appointments(self, row: DemoHospital) -> list[dict]:
        """The visits that came through Talk, as the hospital's own book holds them (the sample visits that filled the book are left out)."""
        app = self.apps.get(row.slug)
        if app is None:
            return []
        store, today = app.state.store, app.state.store.clock().date()
        out = []
        for r in store.db.execute("SELECT * FROM appointments WHERE caller_ref NOT LIKE 'sample-%' ORDER BY created").fetchall():
            start = datetime.fromisoformat(r["starts"])
            out.append({"code": r["code"], "starts": r["starts"], "when": f"{say_day(start.date(), today)} at {say_time(start)}", "visit": r["visit"], "status": r["status"]})
        return out
