"""Every outbound message is a notifications row."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Notification, WhatsAppContact

TEST_PREFIX = "+2349990"  # numbers reserved for typed test conversations (the /try page): a text to one is recorded, never sent

# What a front desk calls each kind of text, and how it shows what became of one: a tick when the provider accepted it, two when the phone received it.
LABELS = {"health_pay": "Payment details", "health_paid": "Payment received", "health_confirmed": "Visit confirmed", "health_reminder": "Reminder",
          "health_thanks": "Thank you", "health_missed": "Missed visit", "health_request_reply": "Reply to request", "health_notice": "Details sent",
          "health_staff_alert": "Staff alert"}
TICKS = {"queued": ("", "Queued", "neutral"), "sent": ("✓", "Sent", "neutral"), "buffered": ("✓", "Sent", "neutral"), "delivered": ("✓✓", "Delivered", "success"),
         "failed": ("✕", "Not delivered", "danger"), "rejected": ("✕", "Not delivered", "danger"), "mock_sent": ("✓", "Test", "neutral"),
         "not_sent_abroad": ("", "Not sent", "neutral"), "read": ("✓✓", "Read", "success")}


def texts_about(session_factory, codes: set[str], limit: int = 40) -> list[dict]:
    """The texts Talk sent about one provider's visits, requests and emergency places, newest first: found by the reference each one carries. A front desk sees
    the words that were sent and what became of them, and only the last four digits of the number."""
    if not codes:
        return []
    found = []
    with session_factory() as db:
        for note in db.scalars(select(Notification).where(Notification.template.in_(LABELS)).order_by(Notification.created_at.desc()).limit(400)):
            code = next((c for c in codes if c in note.body), None)
            if not code:
                continue
            ticks, word, tone = TICKS.get(note.status, ("", note.status.replace("_", " ").capitalize(), "neutral"))
            found.append({"label": LABELS[note.template], "code": code, "body": note.body, "to": note.to_number[-4:], "at": note.created_at,
                          "ticks": ticks, "state": word, "tone": tone})
            if len(found) >= limit:
                break
    return found


WINDOW_HOURS = 24     # WhatsApp lets a business write freely only within this long of the person's last message


async def send_followup(db: Session, services, *, person, body: str, template: str, wa_template: tuple[str, list[str]] | None = None) -> Notification:
    """A follow-up to a person, on the channel they use. Someone who chats with Sofa on WhatsApp gets it there: as a normal message within 24 hours of their
    last message, and outside that only as an approved template (`wa_template`: its kind and its values); with no template, it goes by SMS."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    contact = db.scalar(select(WhatsAppContact).where(WhatsAppContact.caller_id == person.id))
    wa = getattr(services, "whatsapp", None)
    if contact and wa:
        last = contact.last_inbound_at if contact.last_inbound_at.tzinfo else contact.last_inbound_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - last < timedelta(hours=WINDOW_HOURS):
            return await send_sms(db, services, to=person.phone, body=body, template=template, caller_id=person.id, channel="whatsapp")
        name = services.settings.whatsapp_reminder_template
        if wa_template and name:
            note = Notification(caller_id=person.id, channel="whatsapp", template=template, to_number=person.phone, body=body)
            db.add(note)
            db.flush()
            note.status, note.provider_message_id = await wa.send_template(person.phone, name, services.settings.whatsapp_template_language, wa_template[1])
            if note.status == "sent":
                return note
    return await send_sms(db, services, to=person.phone, body=body, template=template, caller_id=person.id)


def saw_on_whatsapp(db: Session, caller_id) -> None:
    """The person wrote on WhatsApp just now: for the next 24 hours Talk may write back freely."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    row = db.scalar(select(WhatsAppContact).where(WhatsAppContact.caller_id == caller_id))
    if row is None:
        db.add(WhatsAppContact(caller_id=caller_id, last_inbound_at=datetime.now(timezone.utc)))
    else:
        row.last_inbound_at = datetime.now(timezone.utc)


async def send_sms(db: Session, services, *, to: str, body: str, template: str, caller_id=None, channel: str = "sms") -> Notification:
    """A text to the caller: by SMS, or as a WhatsApp message to a person who is chatting with Sofa on WhatsApp."""
    note = Notification(caller_id=caller_id, channel=channel, template=template, to_number=to, body=body)
    db.add(note)
    db.flush()
    if channel == "whatsapp" and getattr(services, "whatsapp", None):
        note.status, note.provider_message_id = await services.whatsapp.send_text(to, body)
        return note
    if to.startswith(TEST_PREFIX):
        note.status, note.provider_message_id = "mock_sent", None
        return note
    if not to.startswith("+234"):   # the text-message service reaches Nigerian numbers: a caller from abroad is never told that a text is on its way
        note.status, note.provider_message_id = "not_sent_abroad", None
        return note
    status, message_id = await services.sms.send(to, body)
    note.status, note.provider_message_id = status, message_id
    return note
