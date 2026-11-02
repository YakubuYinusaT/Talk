"""Follow-up: Talk looks after the patient before and after a visit it booked, so the clinic's book stays true and nobody is lost.

One pass, run by the scheduler (and by hand with `python -m scripts.health_followups`):

  * a visit that the hospital's staff have confirmed on their front desk gets a text that says so (once, as soon as Talk learns of it);
  * a visit coming up within a day gets a reminder text (once);
  * a visit whose time has passed is checked with the clinic's own system: attended, did not come, or still not marked;
  * a patient who came gets a thank-you and an offer of the next visit; one who did not gets a "we missed you, call to book a new time" (once each).

The clinic stays the source of truth: Talk changes its own record only to match what the clinic's system says. Texts go out only between 7 in the morning and 8 in the
evening, name the place by its discreet name (never by what is treated there), and say nothing about the patient's health.
"""

import logging
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select

from ..models import Caller, HealthAppointment, HealthRequest
from ..services.notify import send_sms
from .when import say_day, say_time

log = logging.getLogger("sofa.health")
FIRST_HOUR, LAST_HOUR = 7, 20          # texts only go out in these hours, Lagos time
REMIND_WITHIN_HOURS = 24
GIVE_UP_AFTER_DAYS = 3                  # a visit the clinic never marks is left alone after this long
REQUEST_EXPIRES_DAYS = 7                # a request the staff never answer is no longer asked about after this long
CONFIRM_BATCH = 50                      # the most visits asked about, in one pass, to find out whether the staff have confirmed them


async def announce_confirmations(svc, domain: str | None = None, now: datetime | None = None) -> list[dict]:
    """Ask the hospitals about the visits Talk booked that still show as booked here. For each one the hospital's staff have confirmed, text the patient once to say so
    and keep Talk's own record true. `domain` limits the pass to one hospital (the onboarding wizard asks about its own hospital every few seconds). Returns what was
    sent: the booking code, the text and whether it was really sent or only recorded."""
    adapter = svc.orchestrator.adapter("health")
    if not adapter:
        return []
    now = now or adapter.now()
    sent: list[dict] = []
    with svc.session_factory() as db:
        query = select(HealthAppointment).where(HealthAppointment.status == "booked").order_by(HealthAppointment.created_at.desc()).limit(CONFIRM_BATCH)
        if domain:
            query = query.where(HealthAppointment.provider == domain)
        for row in list(db.scalars(query)):
            person, spec = db.get(Caller, row.caller_id), adapter.find_spec(row.provider)
            if not person or not spec or datetime.fromisoformat(row.starts_local) <= now:
                continue
            ctx = SimpleNamespace(db=db, svc=svc, person=person, call=None)
            answer = await adapter.provider_call(ctx, spec, "visit_status", {"code": row.code})
            if (answer or {}).get("status") != "confirmed":
                continue
            to = adapter.demo.confirmation_phone(row.provider, person.phone) if adapter.demo else person.phone    # a visitor who agreed to it is texted on their own phone
            note = await send_sms(db, svc, to=to, body=confirmed_text(row, now), template="health_confirmed", caller_id=person.id)
            if note.status in ("sent", "mock_sent"):
                row.status = "confirmed"
                sent.append({"code": row.code, "text": note.body, "status": note.status})
        db.commit()
    return sent


def reminder_text(row: HealthAppointment, now: datetime) -> str:
    start = datetime.fromisoformat(row.starts_local)
    return (f"This is a friendly reminder that your appointment at {row.sms_name} is {say_day(start.date(), now.date())} at {say_time(start)}. Your booking code is {row.code}. "
            "Please arrive 15 minutes early. If you need to change or cancel it, please call this number.")


def confirmed_text(row: HealthAppointment, now: datetime) -> str:
    start = datetime.fromisoformat(row.starts_local)
    return (f"Good news from {row.sms_name}: the hospital has confirmed your appointment for {say_day(start.date(), now.date())} at {say_time(start)}. Your booking code is {row.code}. "
            "Please arrive 15 minutes early. If you need to change or cancel it, please call this number.")


def attended_text(row: HealthAppointment, now: datetime) -> str:
    start = datetime.fromisoformat(row.starts_local)
    return (f"Thank you for coming to {row.sms_name} on {say_day(start.date(), now.date())}. If you have any questions about your visit, please call this number at any time. "
            "To book your next visit, please call and say that you would like to book an appointment.")


def reply_text(row: HealthRequest, reply: str) -> str:
    return f"The care team at {row.sms_name} has replied to your request {row.code}: {reply} If you need more help, please call this number."


def missed_text(row: HealthAppointment, now: datetime) -> str:
    start = datetime.fromisoformat(row.starts_local)
    return (f"We missed you at {row.sms_name} on {say_day(start.date(), now.date())}. To book a new time, please call this number and say that you would like to book an appointment.")


async def run(svc, now: datetime | None = None) -> dict:
    """One pass over every visit Talk booked that is not finished. `now` is Lagos time (a plain datetime); tests give their own. Returns what it did."""
    adapter = svc.orchestrator.adapter("health")
    done = {"confirmed": 0, "reminders": 0, "attended": 0, "missed": 0, "thanked": 0, "chased": 0, "not_marked": 0, "replied": 0}
    if not adapter or not adapter.has_providers():
        return done
    now = now or adapter.now()
    done["confirmed"] = len(await announce_confirmations(svc, now=now))
    can_text = FIRST_HOUR <= now.hour < LAST_HOUR
    stamp = datetime.now(timezone.utc)
    with svc.session_factory() as db:
        rows = list(db.scalars(select(HealthAppointment).where(HealthAppointment.status.in_(("booked", "confirmed", "attended", "no_show"))).order_by(HealthAppointment.starts_local)))
        for row in rows:
            person = db.get(Caller, row.caller_id)
            if not person:
                continue
            start = datetime.fromisoformat(row.starts_local)
            if row.status in ("booked", "confirmed") and start > now:
                if row.reminded_at is None and (start - now).total_seconds() <= REMIND_WITHIN_HOURS * 3600 and can_text:
                    note = await send_sms(db, svc, to=person.phone, body=reminder_text(row, now), template="health_reminder", caller_id=person.id)
                    if note.status in ("sent", "mock_sent"):
                        row.reminded_at, done["reminders"] = stamp, done["reminders"] + 1
                continue
            if row.status in ("booked", "confirmed"):      # its time has passed: what does the clinic's own book say?
                spec = adapter.find_spec(row.provider)
                ctx = SimpleNamespace(db=db, svc=svc, person=person, call=None)
                answer = await adapter.provider_call(ctx, spec, "visit_status", {"code": row.code}) if spec else None
                state = (answer or {}).get("status")
                if state in ("attended", "no_show", "cancelled"):
                    row.status = state
                    if state in ("attended", "no_show"):
                        done["attended" if state == "attended" else "missed"] += 1
                else:
                    if (now - start).days >= GIVE_UP_AFTER_DAYS:
                        done["not_marked"] += 1
                    continue
            if row.status in ("attended", "no_show") and row.followed_up_at is None and can_text:
                body = attended_text(row, now) if row.status == "attended" else missed_text(row, now)
                template = "health_thanks" if row.status == "attended" else "health_missed"
                note = await send_sms(db, svc, to=person.phone, body=body, template=template, caller_id=person.id)
                if note.status in ("sent", "mock_sent"):
                    row.followed_up_at = stamp
                    done["thanked" if row.status == "attended" else "chased"] += 1
        for req in list(db.scalars(select(HealthRequest).where(HealthRequest.status == "open"))):    # a request the provider's staff have answered: the answer is texted back, once
            created = req.created_at if req.created_at.tzinfo else req.created_at.replace(tzinfo=timezone.utc)
            if (stamp - created).days >= REQUEST_EXPIRES_DAYS:
                req.status = "expired"
                continue
            person = db.get(Caller, req.caller_id)
            spec = adapter.find_spec(req.provider)
            if not person or not spec or not can_text:
                continue
            ctx = SimpleNamespace(db=db, svc=svc, person=person, call=None)
            found = ((await adapter.provider_call(ctx, spec, "request_status", {"code": req.code})) or {}).get("request") or {}
            if found.get("status") == "answered" and found.get("reply"):
                note = await send_sms(db, svc, to=person.phone, body=reply_text(req, found["reply"]), template="health_request_reply", caller_id=person.id)
                if note.status in ("sent", "mock_sent"):
                    req.status, req.texted_at, done["replied"] = "answered", stamp, done["replied"] + 1
        db.commit()
    if any(done.values()):
        log.info("health follow-up: %s", ", ".join(f"{k} {v}" for k, v in done.items() if v))
    return done
