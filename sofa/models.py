"""Talk's own records: who called, what was said and done on each call, the texts sent, and the visits and requests it is following up. Phones are E.164.

The hospitals' records are not here: each provider system keeps its own (sofa/health)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Row:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


def fk(table: str, nullable: bool = False):
    return mapped_column(Uuid, ForeignKey(f"{table}.id"), nullable=nullable, index=True)


# ---- callers -----------------------------------------------------------------------------


class Caller(Row, Base):
    __tablename__ = "callers"
    phone: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str | None] = mapped_column(String(200))
    consent_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # when the caller was told that calls are recorded


class CallerMemory(Row, Base):
    """What Sofa remembers about a person from one call to the next (sofa/services/caller_memory.py). The key is one-way: no phone number is stored here."""
    __tablename__ = "caller_memory"
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    data: Mapped[str] = mapped_column(Text, default="{}")


# ---- calls -------------------------------------------------------------------------------


class Call(Row, Base):
    __tablename__ = "calls"
    caller_id: Mapped[uuid.UUID | None] = fk("callers", nullable=True)
    direction: Mapped[str] = mapped_column(String(10), default="inbound")
    provider_session_id: Mapped[str] = mapped_column(String(100), index=True)
    from_number: Mapped[str] = mapped_column(String(20))
    to_number: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(30))
    handoff_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    duration_s: Mapped[int | None] = mapped_column(Integer)
    cost: Mapped[str | None] = mapped_column(String(30))
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)
    service_domain: Mapped[str | None] = mapped_column(String(20))  # the last service the caller asked for
    turns: Mapped[list["CallTurn"]] = relationship(back_populates="call", order_by="CallTurn.seq")


class CallTurn(Row, Base):
    __tablename__ = "call_turns"
    call_id: Mapped[uuid.UUID] = fk("calls")
    seq: Mapped[int] = mapped_column(Integer)
    recording_url: Mapped[str | None] = mapped_column(Text)
    audio_path: Mapped[str | None] = mapped_column(Text)
    asr_model: Mapped[str | None] = mapped_column(String(100))
    transcript: Mapped[str | None] = mapped_column(Text)
    asr_confidence: Mapped[float | None] = mapped_column(Float)
    llm_json: Mapped[dict | None] = mapped_column(JSON)
    action_taken: Mapped[str | None] = mapped_column(String(50))
    reply_text: Mapped[str | None] = mapped_column(Text)
    reply_audio_path: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[dict | None] = mapped_column(JSON)  # per stage + total
    trace: Mapped[list | None] = mapped_column(JSON)  # what happened inside the turn, step by step: heard, understood, read, asked, booked, request, replied (never a phone number)
    error: Mapped[str | None] = mapped_column(Text)
    call: Mapped[Call] = relationship(back_populates="turns")


# ---- texts and hand-offs -----------------------------------------------------------------


class Notification(Row, Base):
    __tablename__ = "notifications"
    caller_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    channel: Mapped[str] = mapped_column(String(10), default="sms")
    template: Mapped[str] = mapped_column(String(50))
    to_number: Mapped[str] = mapped_column(String(20))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    provider_message_id: Mapped[str | None] = mapped_column(String(100))


class WhatsAppContact(Row, Base):
    """A caller who chats with Sofa on WhatsApp, and when they last wrote: WhatsApp lets Talk write freely only within 24 hours of that."""
    __tablename__ = "wa_contacts"
    caller_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True, index=True)
    last_inbound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Payment(Row, Base):
    """A payment Talk asked a caller to make by bank transfer, for one visit or one medicine order (sofa/services/payments.py)."""
    __tablename__ = "health_payments"     # not "payments": an older database on the live server already has a table of that name
    reference: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    purpose: Mapped[str] = mapped_column(String(20))                    # visit | medicine
    code: Mapped[str] = mapped_column(String(20), index=True)           # the booking or order code the payment is for
    place: Mapped[str] = mapped_column(String(160))
    amount: Mapped[int] = mapped_column(Integer)                       # naira
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | paid
    channel: Mapped[str] = mapped_column(String(20), default="simulated")   # paystack | simulated
    bank: Mapped[str] = mapped_column(String(80), default="")
    account_number: Mapped[str] = mapped_column(String(20), default="")
    account_name: Mapped[str] = mapped_column(String(160), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    caller_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class Handoff(Row, Base):
    """A request Talk could not finish, passed to the people who follow up."""
    __tablename__ = "handoffs"
    call_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reason: Mapped[str] = mapped_column(String(50))
    service_domain: Mapped[str | None] = mapped_column(String(20))  # the service whose provider follows up
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | resolved


# ---- what Talk follows up -----------------------------------------------------------------


class HealthAppointment(Row, Base):
    """What Talk remembers about a visit it booked, so it can remind the patient and follow up afterwards: the provider's booking code, where, when and what became of it.
    No health details are kept here: a text names the place by the discreet name the provider gives it, never by what is treated there."""
    __tablename__ = "health_appointments"
    caller_id: Mapped[uuid.UUID] = fk("callers")
    provider: Mapped[str] = mapped_column(String(50))                  # the provider system's name for Talk (its service domain)
    code: Mapped[str] = mapped_column(String(20), index=True)
    facility_name: Mapped[str] = mapped_column(String(160))
    sms_name: Mapped[str] = mapped_column(String(160))
    starts_local: Mapped[str] = mapped_column(String(25))               # Lagos time, ISO
    status: Mapped[str] = mapped_column(String(20), default="booked")   # booked | attended | no_show | cancelled
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    followed_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HealthRequest(Row, Base):
    """Something Talk passed to a provider's staff for a caller (a question the patient guide does not cover, an emergency to know about), so the answer can be texted
    back. The staff see the request on the provider's own front desk; Talk keeps only its code, where it went and whether the answer has been texted."""
    __tablename__ = "health_requests"
    caller_id: Mapped[uuid.UUID] = fk("callers")
    provider: Mapped[str] = mapped_column(String(50))                  # the provider system's name for Talk (its service domain)
    code: Mapped[str] = mapped_column(String(20), index=True)
    kind: Mapped[str] = mapped_column(String(20))                      # question | person | emergency
    urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    facility_name: Mapped[str] = mapped_column(String(160))
    sms_name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="open")    # open | answered | expired
    texted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---- the onboarding demonstration -----------------------------------------------------------


class DemoHospital(Row, Base):
    """A simulated hospital that one visitor made in the onboarding wizard. It holds the visitor's choices and the secret of its signed connection with Talk; the hospital's own
    records (its appointment book) are in a database file of their own, as for any provider. It is removed when it expires. Nothing here is real: the data is made up."""
    __tablename__ = "demo_hospitals"
    visitor: Mapped[str] = mapped_column(String(64), index=True)        # the visitor the wizard gave a signed cookie to: the only one who can see this hospital
    slug: Mapped[str] = mapped_column(String(40), unique=True)          # demo-<8 hex>: its address is /synthetic/<slug>/ and its service domain follows from it
    template: Mapped[str] = mapped_column(String(30))
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)        # a hash of the address it was started from, for the limit per address (never the address)
    state: Mapped[str] = mapped_column(String(10), default="draft")     # draft | live | retired
    step: Mapped[int] = mapped_column(Integer, default=1)               # the furthest step of the wizard the visitor has reached
    profile: Mapped[dict] = mapped_column(JSON, default=dict)           # everything the visitor entered, and when each part of the journey happened
    secret: Mapped[str | None] = mapped_column(String(128))             # the hospital's own signing secret: it is never logged or put in a page except the masked control
    desk_key: Mapped[str | None] = mapped_column(String(64))            # the front-desk assistant's key
    owner_phone: Mapped[str | None] = mapped_column(String(20))         # only when the visitor gave their own number and ticked the consent box
    phone_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
