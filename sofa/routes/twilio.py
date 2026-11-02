"""Callbacks for the second telephony provider, Twilio, so that a visitor outside Nigeria can ring Talk on a local number in their own country.

Twilio's voice webhook points at Talk directly, so the call is answered by Talk as it happens; it is not a forwarded call. The turns go through the same
code as a call on the first provider (sofa/routes/voice.py): the same speech recognition, front desk and voice, and the same holding messages while a
slow reply is made. Only the voice XML (sofa/twiml.py) and the names of the form fields differ.

  POST /voice/twilio/inbound/{secret}          a call comes in: greet the caller and listen
  POST /voice/twilio/turn/{secret}             the caller finished speaking: the recording's address is in RecordingUrl
  POST /voice/twilio/continue/{secret}/{turn}  a slow reply: the caller heard a holding message, so give the reply or the next message
  POST /voice/twilio/status/{secret}           the call ended

Every request must carry the callback secret in its address, like the first provider's. When TWILIO_AUTH_TOKEN is set, Twilio's own signature of the
request (X-Twilio-Signature) must also be right, so that a request that does not come from Twilio is refused even if the address leaks. The recordings
are downloaded with the account's key, because Twilio protects them with HTTP basic authentication.
"""

import asyncio
import base64
import hashlib
import hmac
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .. import twiml
from ..textutil import e164
from . import voice

log = logging.getLogger("sofa.twilio")
router = APIRouter(prefix="/voice/twilio")
LINE = voice.Line(twiml, "twilio/")
ENDED = ("completed", "busy", "failed", "no-answer", "canceled")


def signature(token: str, url: str, form: dict) -> str:
    """Twilio's signature of a request: HMAC-SHA1 of the full address followed by every form field name and value, sorted by name, in base64."""
    payload = url + "".join(f"{k}{form[k]}" for k in sorted(form))
    return base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()).decode()


async def checked_form(request: Request, secret: str) -> dict:
    """The form Twilio sent, after the secret in the address and, when a token is set, Twilio's signature have been checked. Anything else is a 404, so a
    stranger learns nothing about the address."""
    svc = request.app.state.svc
    if not hmac.compare_digest(secret, svc.settings.at_callback_secret):
        raise HTTPException(status_code=404)
    form = {k: str(v) for k, v in (await request.form()).items()}
    token = svc.settings.twilio_auth_token
    if token:
        # Twilio signs the address it called, which is the public one, not the address this process sees behind the web server
        url = svc.settings.public_base_url.rstrip("/") + request.url.path + (f"?{request.url.query}" if request.url.query else "")
        if not hmac.compare_digest(signature(token, url, form), request.headers.get("x-twilio-signature", "")):
            log.warning("a Twilio callback was refused because its signature did not match")
            raise HTTPException(status_code=404)
    return form


def recording_key(svc) -> tuple[str, str] | None:
    s = svc.settings
    return (s.twilio_account_sid, s.twilio_auth_token) if s.twilio_account_sid and s.twilio_auth_token else None


@router.post("/inbound/{secret}")
async def inbound(secret: str, request: Request):
    form = await checked_form(request, secret)
    return await voice._inbound_call(request, secret, form, e164(form.get("From", "")), e164(form.get("To", "")), line=LINE,
                                     session_id=form.get("CallSid") or str(uuid.uuid4()))


@router.post("/turn/{secret}")
async def turn(secret: str, request: Request):
    form = await checked_form(request, secret)
    svc = request.app.state.svc
    recording = form.get("RecordingUrl") or ""
    duration = form.get("RecordingDuration") or "1"
    if not recording or (duration.isdigit() and int(duration) == 0):
        recording = None          # the caller said nothing
    elif recording.startswith("https://") and not recording.endswith((".wav", ".mp3")):
        recording += ".wav"       # the recording itself, as a file the speech step can read
    task = asyncio.create_task(voice._process_turn(svc, form.get("CallSid", ""), recording, secret, uuid.uuid4(), line=LINE, auth=recording_key(svc)))
    return await voice._reply_or_hold(request, secret, task, line=LINE)


@router.post("/continue/{secret}/{turn_id}")
async def continue_turn(secret: str, turn_id: str, request: Request):
    await checked_form(request, secret)
    return await voice._continue(request, secret, turn_id, line=LINE)


@router.post("/status/{secret}")
async def status(secret: str, request: Request):
    """The call ended: close it with its length, and forget its conversation."""
    form = await checked_form(request, secret)
    if form.get("CallStatus") in ENDED and form.get("CallSid"):
        duration = form.get("CallDuration") or ""
        voice.close_call(request.app.state.svc, form["CallSid"], int(duration) if duration.isdigit() else None)
    return Response("ok", media_type="text/plain")
