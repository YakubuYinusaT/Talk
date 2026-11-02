"""Telephony callbacks (the provider's Voice XML) for the health front desk, and the turn code that every way into a conversation shares.

Every callback must answer inside the provider timeout and never return an empty body: any exception falls back to a cached "one moment" filler + Redirect, or a
polite goodbye.

Three ways in, one turn: a call over the callback path hands in a recording, a streamed call (sofa/sip) hands in the speech itself, and a typed conversation (the
/try page) hands in text. Each is heard its own way (`run_turn`, `run_text_turn`), then the same code runs the turn: the front desk, the trace, the record of it.
"""

import asyncio
import hashlib
import logging
import random
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func, select

from .. import hardening, voicexml
from ..audio import fetch_recording, to_16k_mono, wav_rms
from ..dialogue.outcome import Outcome, daypart, new_state
from ..dialogue.templates import LANG, render
from ..orchestrator.manager import CallManager
from ..health import scope
from ..models import Call, CallTurn, Caller, Notification
from ..services import caller_memory
from ..textutil import e164

log = logging.getLogger("sofa.voice")
router = APIRouter()

@dataclass(frozen=True)
class Line:
    """How one telephony provider is answered: its voice XML (sofa/voicexml.py or sofa/twiml.py) and where its callbacks live under /voice."""
    xml: object
    prefix: str = ""


AT = Line(voicexml)     # the first provider, whose callbacks are /voice/inbound, /voice/turn and so on
TEXT_NUMBER = "+2349990000"  # a typed conversation is a test call from a number that starts like this, followed by three digits (texts to it are never sent)


def _xml(body: str, reply_text: str | None = None, request: Request | None = None) -> Response:
    headers = {}
    if reply_text is not None and request and request.app.state.svc.settings.debug_headers:
        headers["X-Sofa-Reply-Text"] = reply_text.encode("ascii", "replace").decode()
    return Response(body, media_type="application/xml", headers=headers)


def _log_fields(kind: str, form) -> None:
    """Field NAMES only (never values): shows what the provider really sends, which the docs do not fully say."""
    log.info("voice %s fields: %s", kind, ",".join(sorted(form.keys())))


def _check_secret(request: Request, secret: str) -> None:
    if not hardening.callback_allowed(request, secret):   # a wrong secret or a wrong network looks the same: nothing is here
        raise HTTPException(status_code=404)


def _url(request: Request, path: str, secret: str, line: Line = AT) -> str:
    return f"{request.app.state.svc.settings.public_base_url.rstrip('/')}/voice/{line.prefix}{path}/{secret}"


WAIT_STAGES = 5  # wait_1 .. wait_5, then wait_giveup


async def _giveup(request: Request, secret: str, key: str, line: Line = AT) -> Response:
    """The answer is not coming in time: say so, ask whether there is anything else, and listen. If the caller has nothing more, the
    silence ends the call (max_silences): a line left open costs money."""
    svc = request.app.state.svc
    try:
        urls = [(await svc.audio.speak(render(k, {}), LANG))[0] for k in (key, "call_anything_else")]
        return _xml(line.xml.record(urls, _url(request, "turn", secret, line), svc.settings.record_timeout_seconds, svc.settings.record_max_seconds))
    except Exception:
        return await _fallback(request, secret, redirect_to=_url(request, "turn", secret, line), key=key, line=line)


async def _fallback(request: Request, secret: str, redirect_to: str | None = None, key: str = "filler", line: Line = AT) -> Response:
    """Never an empty body: a cached holding message + Redirect, or a goodbye."""
    svc = request.app.state.svc
    try:
        url, _ = await svc.audio.speak(render(key, {}), LANG)
        if redirect_to:
            return _xml(line.xml.redirect(redirect_to, [url]))
        return _xml(line.xml.play_and_hangup([url]))
    except Exception:
        return _xml(line.xml.say_and_hangup("Sorry, please call again."))


# ---- opening and closing a call ----------------------------------------------------------------------


async def _open_call(svc, session_id: str, caller: str, dest: str, *, typed: bool = False, visitor: str | None = None) -> str | None:
    """Record the call, start its session and return what the greeting says, or None when this caller has phoned too often. A typed conversation is a test
    call and is limited by the page that offers it, not by the hourly limit on a number."""
    with svc.session_factory() as db:
        if not typed:
            recent = db.scalar(select(func.count(Call.id)).where(Call.from_number == caller, Call.created_at > datetime.now(timezone.utc) - timedelta(hours=1)))
            if (recent or 0) >= svc.settings.max_calls_per_hour:
                return None
        person = db.scalar(select(Caller).where(Caller.phone == caller))
        if not person:
            person = Caller(phone=caller)
            db.add(person)
            db.flush()
        call = Call(caller_id=person.id, provider_session_id=session_id, from_number=caller, to_number=dest, is_test=typed or caller in svc.settings.test_numbers)
        db.add(call)
        db.flush()
        st = new_state()
        st.update(call_id=str(call.id), domain=None, typed=typed, phone=caller, visitor=visitor)   # who is asking decides which providers may be told about (sofa/health/scope.py)
        # the same person as last time: a typed or browser call is recognised by its browser, a phone call by its number
        s = svc.settings
        st["memory_key"] = (caller_memory.key_for("visitor", visitor, s.at_callback_secret) if visitor else None) if typed else caller_memory.key_for("phone", caller, s.at_callback_secret)
        known = caller_memory.load(db, st["memory_key"], s.caller_memory_days)
        if known:
            st["health_memory"] = {"req": {k: known[k] for k in ("origin", "area") if known.get(k)}, **({"known_place": known["place"]} if known.get("place") else {})}
        key = "greet_caller_returning" if person.name else "greet_caller_known" if known else "greet_caller"
        greeting = render(f"daypart_{daypart()}", {})
        # a random phrasing each call, so the front desk never sounds scripted
        text = render(key, {"name": person.name or "", "greeting": greeting}, random.randrange(1000))
        svc.sessions.set(session_id, st)
        db.commit()  # saved now: the voice is made after this, and the database is not held locked meanwhile
    return text


async def open_call(svc, session_id: str, caller: str, dest: str) -> str | None:
    """Someone phoned Talk. Returns what the greeting says, or None when this caller has phoned too often. Shared by the callback route and the streamed (SIP) call."""
    return await _open_call(svc, session_id, caller, dest)


async def open_text_session(svc, session_id: str, visitor: str | None = None) -> str:
    """Start a typed conversation: a test call from a reserved number (the last three digits come from the session id). `visitor` is the signed visitor of the onboarding wizard,
    when the page was opened by one: a hospital that visitor made is then among the places Talk knows. Returns the greeting."""
    digits = int(hashlib.sha256(session_id.encode()).hexdigest(), 16) % 1000
    text = await _open_call(svc, session_id, f"{TEXT_NUMBER}{digits:03d}", e164(svc.settings.talk_number) or "typed", typed=True, visitor=visitor)
    return text or ""


def close_call(svc, session_id: str, duration_s: int | None = None) -> None:
    """A streamed or typed call ended (the callback path gets this from the provider's status events): close the calls row and forget the session."""
    with svc.session_factory() as db:
        call = db.scalar(select(Call).where(Call.provider_session_id == session_id))
        if call:
            call.ended_at = datetime.now(timezone.utc)
            call.duration_s = duration_s if duration_s is not None else call.duration_s
            call.outcome = call.outcome or "ended"
            db.commit()
    svc.sessions.delete(session_id)


async def _inbound_call(request: Request, secret: str, form, caller: str, dest: str, line: Line = AT, session_id: str | None = None) -> Response:
    """Someone phoned Talk: greet them and ask what they need."""
    svc = request.app.state.svc
    try:
        text = await open_call(svc, session_id or str(form.get("sessionId") or uuid.uuid4()), caller, dest)
        if text is None:
            return _xml(line.xml.say_and_hangup("Sorry, please try again later."))
        audio_url, _ = await svc.audio.speak(text, LANG)
        body = line.xml.record([audio_url], _url(request, "turn", secret, line), svc.settings.record_timeout_seconds, svc.settings.record_max_seconds)
        return _xml(body, text, request)
    except Exception:
        log.exception("orchestrator inbound failed")
        return await _fallback(request, secret, line=line)


@router.api_route("/voice/inbound/{secret}", methods=["GET", "HEAD"], include_in_schema=False)
@router.api_route("/voice/events/{secret}", methods=["GET", "HEAD"], include_in_schema=False)
async def reachable(secret: str, request: Request):
    """A plain visit to a callback address answers 200, so a dashboard that checks the address before saving it (the telephony provider does) accepts it.
    It shows nothing and does nothing; the secret is still checked."""
    _check_secret(request, secret)
    return Response(content="ok", media_type="text/plain")


@router.post("/voice/inbound/{secret}")
async def inbound(secret: str, request: Request):
    _check_secret(request, secret)
    svc = request.app.state.svc
    form = await request.form()
    _log_fields("inbound", form)
    orchestrator = svc.settings.talk_number.strip()
    dest = e164(str(form.get("destinationNumber", "")))
    if orchestrator and dest != e164(orchestrator):  # a number that is not this service's
        return _xml(voicexml.say_and_hangup(render("no_service", {})))
    return await _inbound_call(request, secret, form, e164(str(form.get("callerNumber", ""))), dest or e164(orchestrator))


def _next_prompt(svc, outcome: Outcome, prompts: list[str], secret: str, line: Line = AT) -> str:
    """Voice XML for what happens after Talk speaks: hang up, or listen for speech."""
    base = svc.settings.public_base_url.rstrip("/")
    if outcome.end_call:
        return line.xml.play_and_hangup(prompts)
    return line.xml.record(prompts, f"{base}/voice/{line.prefix}turn/{secret}", svc.settings.record_timeout_seconds, svc.settings.record_max_seconds)


async def _speak_outcome(svc, outcome: Outcome) -> list[str]:
    """Audio for the reply. A model-worded sentence is new text, so the voice has to make it from scratch, which can be slow: past the time budget the
    stored template wording is spoken instead (always cached ahead of time), never a long silence."""
    template = outcome.extra.get("template") if outcome.action.endswith("|generated") else None
    if not template:
        return [(await svc.audio.speak(outcome.text, LANG))[0]]
    try:
        return [(await asyncio.wait_for(svc.audio.speak(outcome.text, LANG), timeout=svc.settings.tts_budget_seconds))[0]]
    except (asyncio.TimeoutError, Exception) as exc:
        log.warning("voice too slow for the worded reply (%s), speaking the template", type(exc).__name__)
        outcome.text = template
        outcome.action = outcome.action.replace("|generated", "|template_fallback")
        return [(await svc.audio.speak(outcome.text, LANG))[0]]


# ---- one turn --------------------------------------------------------------------------------------------


@dataclass
class Heard:
    """What the caller said in one turn, however it reached Talk."""
    text: str
    confidence: float | None  # None: typed, so there was no speech to be unsure of
    model: str


async def _process_turn(svc, session_id: str, recording_url: str | None, secret: str, turn_id: uuid.UUID, line: Line = AT,
                        auth: tuple[str, str] | None = None) -> tuple[str, str, bool]:
    """Run one caller turn. Returns (voice xml, reply text, ended). `auth` is what the provider asks for before it gives out a recording, if anything."""
    outcome, prompts = await run_turn(svc, session_id, recording_url, turn_id, auth=auth)
    return _next_prompt(svc, outcome, prompts, secret, line), outcome.text, outcome.end_call


async def run_turn(svc, session_id: str, recording_url: str | None, turn_id: uuid.UUID, wav16: bytes | None = None, stream: bool = False,
                   auth: tuple[str, str] | None = None) -> tuple[Outcome, list]:
    """Run one caller turn and return the reply with the addresses of its audio clips. A call over the callback path hands in the recording's address;
    a streamed call hands in the speech itself (`wav16`, already cut out and at 16 kHz) with a recording_url of "stream", and None for "nobody spoke".
    With `stream` the clips come back as texts, not yet voiced: the streamed call voices them as it speaks."""

    async def hear(turn: CallTurn, call: Call, lat: dict) -> Heard | None:
        if not recording_url:  # caller said nothing
            return None
        t = time.perf_counter()
        if wav16 is not None:  # a streamed call: the speech is already here
            raw = audio = wav16
        else:
            raw = await fetch_recording(recording_url, allowed=svc.settings.recording_hosts, auth=auth)
            audio = to_16k_mono(raw)
        turn.audio_path = svc.audio.save_call_audio(call.id, turn.seq, raw)
        lat["audio_fetch"] = int((time.perf_counter() - t) * 1000)
        rms = wav_rms(audio)
        lat["rms"] = int(rms)
        if rms < svc.settings.silence_rms:  # nobody spoke: a quiet line makes the recogniser invent a sentence, so it is treated as silence
            return None
        t = time.perf_counter()
        result = await svc.asr.transcribe(audio, LANG)
        lat["asr"] = int((time.perf_counter() - t) * 1000)
        return Heard(result.text, result.confidence, result.model)

    outcome, prompts, _trace = await _run(svc, session_id, turn_id, recording_url, hear, stream=stream)
    return outcome, prompts


async def run_text_turn(svc, session_id: str, text: str) -> dict:
    """One typed turn of a conversation opened with `open_text_session`, through the same front desk as a phone call (no speech recognition, nothing voiced).
    Returns the reply, whether the call ended, the action taken and the trace of what happened inside the turn."""

    async def hear(turn: CallTurn, call: Call, lat: dict) -> Heard:
        return Heard(text, None, "typed")

    outcome, _prompts, trace = await _run(svc, session_id, uuid.uuid4(), None, hear, voiced=False)
    if outcome.end_call:
        close_call(svc, session_id)
    return {"reply": outcome.text, "ended": outcome.end_call, "action": outcome.action.split("|")[0], "trace": trace}


async def run_spoken_turn(svc, session_id: str, audio: bytes) -> dict:
    """One spoken turn of a call made from the browser on the Try it page: the same speech recognition, front desk and voice as a phone call. The speech is
    not kept. Returns what was heard, the reply with the addresses of its audio, whether the call ended and the trace of the turn."""

    async def hear(turn: CallTurn, call: Call, lat: dict) -> Heard | None:
        t = time.perf_counter()
        wav = await asyncio.to_thread(to_16k_mono, audio)
        lat["audio_fetch"] = int((time.perf_counter() - t) * 1000)
        if wav_rms(wav) < svc.settings.silence_rms:   # nothing was said, only the room
            return None
        t = time.perf_counter()
        result = await svc.asr.transcribe(wav, LANG)
        lat["asr"] = int((time.perf_counter() - t) * 1000)
        return Heard(result.text, result.confidence, result.model)

    outcome, prompts, trace = await _run(svc, session_id, uuid.uuid4(), None, hear)
    if outcome.end_call:
        close_call(svc, session_id)
    heard = next((str(e.get("text") or "") for e in trace if e.get("step") == "heard"), "")
    return {"heard": heard, "reply": outcome.text, "audio": prompts, "ended": outcome.end_call, "action": outcome.action.split("|")[0], "trace": trace}


async def _run(svc, session_id: str, turn_id: uuid.UUID, recording_url: str | None, hear, *, stream: bool = False,
               voiced: bool = True) -> tuple[Outcome, list, list[dict]]:
    """The turn itself, whichever way the words arrived. `hear` fills in what the caller said (None: nobody spoke). Returns the reply, its audio clips (none when
    `voiced` is False) and the trace of the turn. The whole turn is run on behalf of the one who is asking, so that the providers shown to a caller are the right ones."""
    st = svc.sessions.get(session_id)
    with scope.asking((st or {}).get("visitor"), (st or {}).get("phone")):
        return await _run_turn(svc, session_id, turn_id, recording_url, hear, stream=stream, voiced=voiced)


async def _run_turn(svc, session_id: str, turn_id: uuid.UUID, recording_url: str | None, hear, *, stream: bool = False,
                    voiced: bool = True) -> tuple[Outcome, list, list[dict]]:
    t0 = time.perf_counter()
    lat: dict[str, int] = {}
    st = svc.sessions.get(session_id)
    if not st:
        raise LookupError("unknown session")
    with svc.session_factory() as db:
        call = db.get(Call, uuid.UUID(st["call_id"]))
        person = db.get(Caller, call.caller_id)
        seq = (db.scalar(select(func.max(CallTurn.seq)).where(CallTurn.call_id == call.id)) or 0) + 1
        turn = CallTurn(id=turn_id, call_id=call.id, seq=seq, recording_url=recording_url)
        db.add(turn)
        db.commit()  # the turn's first write is saved now, so the database is not locked for the seconds it takes to fetch, hear, understand and speak
        mgr = CallManager(db, svc, st, call, person, turn_id, started=t0)
        try:
            if not st.get("typed") and time.time() - st.get("t0", time.time()) > svc.settings.max_call_seconds:  # the longest a call may run
                outcome = Outcome(render("call_time_limit", {}), "call_time_limit", True, "time_limit")
                call.outcome = call.outcome or "time_limit"
            else:
                heard = await hear(turn, call, lat)
                if heard is None:
                    outcome = await mgr.on_silence()
                else:
                    turn.asr_model, turn.transcript, turn.asr_confidence = heard.model, heard.text, heard.confidence
                    mgr.note("heard", text=heard.text, model=heard.model, confidence=heard.confidence, ms=lat.get("asr", 0))
                    t = time.perf_counter()
                    outcome = await mgr.handle(heard.text, heard.confidence if heard.confidence is not None else 0.0)
                    lat["understand_and_act"] = int((time.perf_counter() - t) * 1000)
            turn.llm_json = mgr.raw_json
        except Exception as exc:
            log.exception("turn failed")
            db.rollback()
            db.add(turn)
            turn.error = repr(exc)
            outcome = Outcome(render("repeat_prompt", {}), "repeat_prompt", action="error")

        prompts: list = []
        reply_path = None
        if voiced:
            t = time.perf_counter()
            if not person.consent_recorded_at and recording_url:
                notice = render("consent", {})
                if stream:
                    prompts.append(notice)
                else:
                    prompts.append((await svc.audio.speak(notice, LANG))[0])  # recording notice, once per person, after the greeting reply
                person.consent_recorded_at = datetime.now(timezone.utc)
            if stream:  # the streamed call voices the reply itself, so it can start speaking before the rest is made
                prompts.append(outcome.text)
            else:
                prompts.extend(await _speak_outcome(svc, outcome))
            reply_path = str(svc.audio.out_dir / f"{svc.audio.key(outcome.text, LANG)}.wav")
            lat["tts"] = int((time.perf_counter() - t) * 1000)
        lat["total"] = int((time.perf_counter() - t0) * 1000)

        mgr.note("replied", text=outcome.text, action=outcome.action.split("|")[0])
        turn.trace = mgr.trace
        turn.action_taken, turn.reply_text, turn.reply_audio_path, turn.latency_ms = outcome.action, outcome.text, reply_path, lat
        svc.sessions.set(session_id, st)
        db.commit()
        return outcome, prompts, mgr.trace


@router.post("/voice/turn/{secret}")
async def turn(secret: str, request: Request):
    _check_secret(request, secret)
    svc = request.app.state.svc
    form = await request.form()
    _log_fields("turn", form)
    session_id = str(form.get("sessionId", ""))
    recording_url = str(form.get("recordingUrl") or "") or None
    task = asyncio.create_task(_process_turn(svc, session_id, recording_url, secret, uuid.uuid4()))
    return await _reply_or_hold(request, secret, task)


async def _reply_or_hold(request: Request, secret: str, task: asyncio.Task, line: Line = AT) -> Response:
    """The reply if it is ready in a moment; otherwise a holding message now and the reply when it is ready."""
    svc = request.app.state.svc
    done, _ = await asyncio.wait({task}, timeout=svc.settings.filler_after_seconds)
    if task in done:
        try:
            result = task.result()
            return _xml(result[0], result[1], request)
        except Exception:
            log.exception("voice task failed")
            return await _fallback(request, secret, redirect_to=_url(request, "turn", secret, line), line=line)  # carry on: never hang up on a caller
    turn_id = str(uuid.uuid4())
    svc.turn_tasks[turn_id] = task
    return await _fallback(request, secret, redirect_to=f"{_url(request, 'continue', secret, line)}/{turn_id}?n=1", line=line)


@router.post("/voice/continue/{secret}/{turn_id}")
async def continue_turn(secret: str, turn_id: str, request: Request):
    _check_secret(request, secret)
    return await _continue(request, secret, turn_id)


async def _continue(request: Request, secret: str, turn_id: str, line: Line = AT) -> Response:
    """The caller has heard a holding message: the reply if it is ready now, otherwise the next holding message, and after the last one an apology."""
    svc = request.app.state.svc
    task = svc.turn_tasks.get(turn_id)
    again = _url(request, "turn", secret, line)
    if not task:
        return await _fallback(request, secret, redirect_to=again, line=line)
    n = int(request.query_params.get("n", "1") or 1)
    done, _ = await asyncio.wait({task}, timeout=svc.settings.filler_every_seconds)
    if task in done:
        svc.turn_tasks.pop(turn_id, None)
        try:
            result = task.result()
            return _xml(result[0], result[1], request)
        except Exception:
            log.exception("continue failed")
            return await _fallback(request, secret, redirect_to=again, line=line)
    if n > WAIT_STAGES:  # long enough: apologise, keep the line open and listen again
        svc.turn_tasks.pop(turn_id, None)
        return await _giveup(request, secret, "wait_giveup", line=line)
    # still working: the next holding message, then wait again
    return await _fallback(request, secret, redirect_to=f"{_url(request, 'continue', secret, line)}/{turn_id}?n={n + 1}", key=f"wait_{n}", line=line)


@router.post("/voice/events/{secret}")
async def events(secret: str, request: Request):
    """Call status changes and call end: close the calls row with duration and cost."""
    _check_secret(request, secret)
    svc = request.app.state.svc
    form = await request.form()
    _log_fields("events", form)
    session_id = str(form.get("sessionId", ""))
    if str(form.get("isActive", "1")) == "0" and session_id:
        with svc.session_factory() as db:
            call = db.scalar(select(Call).where(Call.provider_session_id == session_id))
            if call:
                call.ended_at = datetime.now(timezone.utc)
                dur = form.get("durationInSeconds")
                call.duration_s = int(dur) if dur and str(dur).isdigit() else call.duration_s
                call.cost = str(form.get("amount") or "") or call.cost
                call.outcome = call.outcome or "ended"
                db.commit()
        svc.sessions.delete(session_id)
    return Response("ok")


# What the text message provider reports about a text it accepted: Sent, Submitted and Buffered are on the way, Success is on the phone,
# Failed and Rejected are not coming (the reason is in failureReason, e.g. the handset was off or the sender id was refused).
SMS_REPORT_STATUS = {"success": "delivered", "failed": "failed", "rejected": "rejected", "buffered": "buffered", "sent": "sent", "submitted": "sent"}
SMS_FINAL = ("delivered", "failed", "rejected")  # a late "Buffered" or "Sent" never undoes one of these


@router.api_route("/sms/delivery/{secret}", methods=["GET", "HEAD"], include_in_schema=False)
async def sms_delivery_reachable(secret: str, request: Request):
    """Answers 200 to a plain visit, so the dashboard accepts the address (see `reachable`)."""
    _check_secret(request, secret)
    return Response(content="ok", media_type="text/plain")


@router.post("/sms/delivery/{secret}")
async def sms_delivery(secret: str, request: Request):
    """A delivery report for one text: update the notification it belongs to, and log why when the text did not arrive."""
    _check_secret(request, secret)
    svc = request.app.state.svc
    form = await request.form()
    _log_fields("sms delivery", form)
    message_id, reported = str(form.get("id", "")), str(form.get("status", "")).strip().lower()
    status = SMS_REPORT_STATUS.get(reported)
    if not message_id or not status:
        return Response("ok")
    if status in ("failed", "rejected"):
        log.error("sms %s %s to ...%s: %s", message_id, reported, str(form.get("phoneNumber", ""))[-4:], form.get("failureReason") or "no reason given")
    with svc.session_factory() as db:
        row = db.scalar(select(Notification).where(Notification.provider_message_id == message_id))
        if row and row.status not in SMS_FINAL:
            row.status = status
            db.commit()
    return Response("ok")
