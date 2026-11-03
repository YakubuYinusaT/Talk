"""Chatting with Sofa on WhatsApp, through Meta's WhatsApp Cloud API.

A message goes through the same front desk as a phone call: the same model reading the whole conversation, the same providers, the same memory of the person
(known by their WhatsApp number). A photo of a medicine pack or a prescription is read by Muse Spark, and what it shows becomes part of the conversation, so
"Do you have this?" with a photo of a pack, or a prescription with two medicines on it, is answered like the same words typed. The account number to pay into
and the order details come as WhatsApp messages, and Meta's delivery reports (sent, delivered, read) show on the clinic's or pharmacy's front desk.

Meta must hear back within seconds, so each message is answered in the background; a message Meta sends twice is answered once.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel
from sqlalchemy import select

from ..models import Notification
from . import voice

log = logging.getLogger("sofa.whatsapp")
router = APIRouter()

CONVERSATION_MINUTES = 30      # a person who writes again after this long starts a new conversation (Sofa still remembers them)
INLINE = False                 # tests answer each message before the webhook returns
STATUS_RANK = {"sent": 1, "delivered": 2, "read": 3}

_seen: dict[str, float] = {}             # message ids answered in the last hour
_locks: dict[str, asyncio.Lock] = {}     # one message at a time from each person
_tasks: set = set()


class Photo(BaseModel):
    kind: Literal["prescription", "medicine_pack", "other"] | None = "other"
    medicines: list[str] | None = []
    summary: str | None = ""


PHOTO_PROMPT = ("PHOTO. A person chatting with Talk, a health assistant in Lagos, sent this photo. Say what it is: a prescription, a medicine pack, or something "
                "else. List every medicine name you can read on it, exactly as written, with its strength. Give a one-sentence summary without any personal "
                "details (no names of patients, no phone numbers). Do not judge whether the medicine is right for anyone. Answer JSON only.")


def signed(secret: str, body: bytes, header: str) -> bool:
    """Meta signs each webhook with HMAC-SHA256 of the raw body, keyed with the app secret."""
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return bool(secret) and hmac.compare_digest(expected, header or "")


@router.get("/whatsapp/webhook", include_in_schema=False)
async def verify(request: Request):
    """Meta's check of the webhook address when it is set: the verify token must match, and the challenge is sent back."""
    s, q = request.app.state.svc.settings, request.query_params
    if s.whatsapp_verify_token and q.get("hub.mode") == "subscribe" and hmac.compare_digest(q.get("hub.verify_token", ""), s.whatsapp_verify_token):
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(status_code=403, detail="verification failed")


@router.post("/whatsapp/webhook", include_in_schema=False)
async def receive(request: Request):
    svc = request.app.state.svc
    body = await request.body()
    if not signed(svc.settings.whatsapp_app_secret, body, request.headers.get("x-hub-signature-256", "")):
        raise HTTPException(status_code=401, detail="bad signature")
    try:
        event = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="not JSON") from None
    for entry in event.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            record_statuses(svc, value.get("statuses") or [])
            for message in value.get("messages") or []:
                if not fresh(str(message.get("id") or "")):
                    continue
                work = answer(svc, message)
                if INLINE:
                    await work
                else:
                    task = asyncio.create_task(work)
                    _tasks.add(task)
                    task.add_done_callback(_tasks.discard)
    return Response("ok")


def fresh(message_id: str) -> bool:
    """True the first time a message is seen. Meta sends a message again when it did not hear back in time."""
    now = time.time()
    for old in [k for k, t in _seen.items() if now - t > 3600]:
        _seen.pop(old, None)
    if not message_id or message_id in _seen:
        return False
    _seen[message_id] = now
    return True


def record_statuses(svc, statuses: list[dict]) -> None:
    """Meta's delivery reports for the messages Talk sent: a message moves on from sent to delivered to read, and never back."""
    if not statuses:
        return
    with svc.session_factory() as db:
        for s in statuses:
            row = db.scalar(select(Notification).where(Notification.provider_message_id == str(s.get("id") or "")))
            status = str(s.get("status") or "")
            if not row or row.status == "failed":
                continue
            if status == "failed" or STATUS_RANK.get(status, 0) > STATUS_RANK.get(row.status, 0):
                row.status = status
        db.commit()


def session_of(svc, wa_id: str) -> str:
    return "wa-" + hashlib.sha256(f"whatsapp|{wa_id}|{svc.settings.at_callback_secret}".encode()).hexdigest()[:20]


async def conversation(svc, wa_id: str) -> str | None:
    """The person's conversation: the one in progress, or a new one after a pause. None when this number has written too often."""
    sid = session_of(svc, wa_id)
    st = svc.sessions.get(sid)
    if st and time.time() - st.get("wa_seen", 0) > CONVERSATION_MINUTES * 60:
        voice.close_call(svc, sid)
        st = None
    if not st:
        if await voice.open_call(svc, sid, f"+{wa_id}", f"whatsapp:{svc.settings.whatsapp_phone_number_id}") is None:
            return None
        st = svc.sessions.get(sid)
        st["channel"] = "whatsapp"
    st["wa_seen"] = time.time()
    svc.sessions.set(sid, st)
    return sid


def remember_contact(svc, wa_id: str) -> None:
    """This person chats on WhatsApp and wrote just now: their reminders and other follow-ups come here (sofa/services/notify.py)."""
    from ..models import Caller
    from ..services.notify import saw_on_whatsapp

    with svc.session_factory() as db:
        person = db.scalar(select(Caller).where(Caller.phone == f"+{wa_id}"))
        if person:
            saw_on_whatsapp(db, person.id)
            db.commit()


async def words_of(svc, message: dict) -> str | None:
    """What the person said: the text, or what their photo shows, in words the front desk reads. None for what Sofa cannot read here."""
    kind = message.get("type")
    if kind == "text":
        return str((message.get("text") or {}).get("body") or "").strip()[:1000]
    if kind == "image" and svc.whatsapp:
        image = message.get("image") or {}
        got = await svc.whatsapp.media(str(image.get("id") or ""))
        caption = str(image.get("caption") or "").strip()[:500]
        if got is None:
            return None
        photo = await svc.llm.see(Photo, PHOTO_PROMPT, got[0], got[1], caption)
        medicines = [m for m in (photo.medicines or []) if m and m.strip()]     # read by Muse Spark 1.3 (VISION_MODEL), the photo itself is not kept
        log.info("a %s photo read by %s: %d medicines", photo.kind, getattr(svc.llm, "vision_model", ""), len(photo.medicines or []))
        if not medicines:     # whatever the photo is called, it is read when the model found a medicine on it
            return None
        what = "a prescription" if photo.kind == "prescription" else "a medicine pack"
        return f"I am sending a photo of {what}. The medicines on it are: {'; '.join(m[:80] for m in medicines[:6])}. {caption}".strip()
    return None


async def answer(svc, message: dict) -> None:
    wa_id = str(message.get("from") or "")
    if not wa_id or not svc.whatsapp:
        return
    lock = _locks.setdefault(wa_id, asyncio.Lock())
    async with lock:
        try:
            said = await words_of(svc, message)
            if said is None:
                await svc.whatsapp.send_text(wa_id, "I could not read that. Please type your message, or send a clear photo of the medicine pack or the prescription.")
                return
            sid = await conversation(svc, wa_id)
            if sid is None:
                await svc.whatsapp.send_text(wa_id, "Sorry, please try again a little later.")
                return
            remember_contact(svc, wa_id)
            result = await voice.run_text_turn(svc, sid, said)
            await svc.whatsapp.send_text(wa_id, result["reply"])
            if result.get("ended"):
                svc.sessions.delete(sid)
        except Exception:     # one failed answer must never stop the next message from being answered
            log.exception("a WhatsApp message could not be answered")
            await svc.whatsapp.send_text(wa_id, "Sorry, something went wrong on our side. Please send your message again.")
