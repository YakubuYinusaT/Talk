"""Try it (/try): a visitor types to Talk in the browser and sees what happened inside each reply.

It goes through the same path as a phone call (the same language model, the same front desk, the same four simulated providers). A visitor can call
from the browser, which also uses the same speech recognition and voice, or type, which leaves the speech out. Nothing leaves the page: the text message a call would send is recorded as sent without calling
the text-message service, and a booking made here lands on the provider's own front desk like any other.

  GET  /try         the page
  POST /try/start   {} -> {"session", "greeting", ...}
  POST /try/turn    {"session", "text"} -> {"reply", "ended", "action", "trace", "steps_html", "turns_left"}
  POST /try/speak   {"session", "audio"} -> the same, with "heard" and the "audio" of the reply: a call made from the browser, through the same speech
                    recognition and voice as a phone call

The feature is guarded because every turn costs a model call: JSON only, at most 300 characters a message, a per-network hourly limit, a limit on the
messages in one conversation, a conversation that expires, and a cap on everything at once. Nothing it sends back holds a secret or a phone number.
"""

import asyncio
import base64
import logging
import re
from urllib.parse import urlparse
import secrets
import time
import uuid
from collections import deque

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..onboarding import visitor as who
from ..web import ui
from . import voice

log = logging.getLogger("sofa.try")
router = APIRouter(prefix="/try")
templates = ui.templates

MAX_CHARS = 300
MAX_AUDIO_BYTES = 1_000_000   # about thirty seconds of the 16 kHz speech the page sends: one sentence is far shorter
MAX_SESSIONS = 500           # conversations alive at once, across everyone
HOUR = 3600.0
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

# Ready-made conversations the visitor can step through one sentence at a time. Every line is something a real caller might say, in the polite, natural way people
# speak on the telephone, and every conversation is meant to be run in order from the start (a booking has to exist before it can be cancelled). The page shows only
# the title, because what each conversation does is clear from its sentences.
SCRIPTS = [
    {"title": "Book a clinic visit",
     "lines": ["Please help me find the nearest clinic for antenatal care.", "I am in Surulere.", "Yes, please book the private clinic.", "Tomorrow morning, please.",
               "Yes, please go ahead."]},
    {"title": "Book, then cancel",
     "lines": ["I would like to book an appointment, please.", "I am in Yaba, please.", "The first one, please.", "Tomorrow morning, please.", "Yes, please go ahead.",
               "Please can you cancel my appointment for tomorrow?", "Yes, please."]},
    {"title": "Medicine stock",
     "lines": ["Hello, do you have amoxicillin in stock, please?", "Thank you. Do you have paracetamol in stock as well, please?"]},
    {"title": "Ask the cancer centre",
     "lines": ["What should I bring to my first visit at the cancer centre, please?", "Thank you. Could you also ask the centre about parking, please?"]},
    {"title": "Emergency",
     "lines": ["Please, my brother is not breathing, we are in Ikeja."]},
]


def now() -> float:
    return time.monotonic()


def enabled(request: Request) -> None:
    if not getattr(request.app.state.svc.settings, "try_page_enabled", True):
        raise HTTPException(404)


def state(request: Request) -> dict:
    st = getattr(request.app.state, "try_state", None)
    if st is None:
        st = request.app.state.try_state = {"sessions": {}, "ip_turns": {}, "ip_starts": {}, "all_turns": deque()}
    return st


def client_ip(request: Request) -> str:
    """Who is asking, for the hourly limit. Behind the web server in front of the app the real address is the last one it appended to X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for", "")
    last = forwarded.split(",")[-1].strip() if forwarded else ""
    return last or (request.client.host if request.client else "unknown")


def within_hour(window: deque, limit: int, t: float) -> bool:
    """Drop what is older than an hour, then say whether one more fits under the limit."""
    while window and t - window[0] > HOUR:
        window.popleft()
    return len(window) < limit


def purge(st: dict, minutes: int, t: float) -> None:
    for sid in [k for k, v in st["sessions"].items() if t - v["created"] > minutes * 60]:
        del st["sessions"][sid]
    for table in ("ip_turns", "ip_starts"):
        for ip in [k for k, w in st[table].items() if not w or t - w[-1] > HOUR]:
            del st[table][ip]


def refuse(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


async def body_of(request: Request):
    """The JSON object the page sent, or the refusal to give: this feature takes nothing but JSON."""
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        return refuse(415, "This takes JSON only.")
    try:
        body = await request.json()
    except ValueError:
        return refuse(400, "That was not valid JSON.")
    return body if isinstance(body, dict) else refuse(400, "Send a JSON object.")


@router.get("")
async def page(request: Request, _=Depends(enabled)):
    svc = request.app.state.svc
    s = svc.settings
    whatsapp = await svc.whatsapp.display_number() if getattr(svc, "whatsapp", None) else ""     # chatting is on WhatsApp first, here as a backup
    return templates.TemplateResponse(request, "try.html", {
        "whatsapp": whatsapp,
        "request": request, "brand": "Talk", "scripts": SCRIPTS, "max_chars": MAX_CHARS, "max_turns": s.try_max_turns, "minutes": s.try_session_minutes,
        "providers": ui.providers(), "test_number": getattr(s, "test_number", ""),
        "numbers": [n for n in (getattr(s, "test_number", ""), getattr(s, "test_number_international", "")) if n],
    })


@router.post("/start")
async def start(request: Request, _=Depends(enabled)):
    svc = request.app.state.svc
    s = svc.settings
    body = await body_of(request)
    if isinstance(body, JSONResponse):
        return body
    st, t, ip = state(request), now(), client_ip(request)
    purge(st, s.try_session_minutes, t)
    starts = st["ip_starts"].setdefault(ip, deque())
    if not within_hour(starts, max(5, s.try_turns_per_hour // 4), t):
        return refuse(429, "Too many conversations this hour. Please try again later.")
    if len(st["sessions"]) >= MAX_SESSIONS:
        return refuse(503, "Talk is busy. Please try again shortly.")
    session = secrets.token_urlsafe(16)
    onboarding = getattr(svc, "onboarding", None)
    # The browser is recognised from one conversation to the next by a random identifier in a signed cookie, the same one the onboarding wizard uses, so that
    # Sofa remembers this visitor as it remembers a caller by their number. A visitor who made a hospital in the wizard also sees it here, and nobody else does.
    visitor, cookie = who.read(request.cookies, s.at_callback_secret), None
    if not visitor and s.caller_memory_days > 0:
        visitor, cookie = who.issue(s.at_callback_secret)
    if onboarding and visitor:
        with svc.session_factory() as db:
            if onboarding.hospital_of(db, visitor):
                session = f"onb-{who.tag(visitor)}-{session}"     # so that the Live calls page and the wizard's summary can recognise these conversations
    try:
        greeting = await voice.open_text_session(svc, session, visitor)
    except Exception:
        log.exception("could not open a text session")
        return refuse(502, "Talk could not start. Please try again.")
    starts.append(t)
    st["sessions"][session] = {"created": t, "turns": 0, "ended": False, "busy": False}
    out = {"session": session, "greeting": ui.scrub(greeting), "max_turns": s.try_max_turns, "minutes": s.try_session_minutes}
    if body.get("mode") == "call":
        try:
            out["audio"] = [path_of((await svc.audio.speak(greeting, voice.LANG))[0])]
        except Exception:
            log.exception("the greeting could not be voiced")
            out["audio"] = []
        out["voice"] = getattr(svc.tts, "tag", "")
    if not cookie:
        return out
    response = JSONResponse(out)
    response.set_cookie(who.COOKIE, cookie, max_age=s.caller_memory_days * 86400, httponly=True, samesite="lax", secure=str(s.public_base_url).startswith("https://"), path="/")
    return response


def path_of(url: str) -> str:
    """The audio's own address on this site, so that the page plays it from wherever it was opened."""
    return urlparse(url).path


async def guarded(request: Request, session, run) -> dict | JSONResponse:
    """Runs one turn of a conversation, typed or spoken, inside the same limits: a live conversation that has not ended, one turn at a time, a limit on the
    turns of one conversation and on the turns from one network and from everyone in an hour."""
    s = request.app.state.svc.settings
    st, t, ip = state(request), now(), client_ip(request)
    purge(st, s.try_session_minutes, t)
    info = st["sessions"].get(session) if isinstance(session, str) else None
    if info is None:
        return refuse(404, "This conversation has expired. Please start over.")
    if info["ended"]:
        return refuse(409, "This call has ended. Please start over.")
    if info["busy"]:
        return refuse(409, "Talk is still replying.")
    if info["turns"] >= s.try_max_turns:
        return refuse(429, f"This conversation is limited to {s.try_max_turns} messages. Please start over.")
    mine, everyone = st["ip_turns"].setdefault(ip, deque()), st["all_turns"]
    if not within_hour(mine, s.try_turns_per_hour, t) or not within_hour(everyone, s.try_turns_per_hour * 10, t):
        return refuse(429, "Too many messages this hour. Please try again later.")
    mine.append(t)
    everyone.append(t)
    info["turns"] += 1
    info["busy"] = True
    try:
        result = await run()
    except Exception:
        log.exception("a turn on the Try it page failed")
        return refuse(502, "Talk could not reply. Please try again.")
    finally:
        info["busy"] = False
    info["ended"] = bool(result.get("ended"))
    trace = ui.scrub_data(result.get("trace") or [])
    return {"reply": ui.scrub(str(result.get("reply") or "")), "ended": info["ended"], "action": ui.scrub(str(result.get("action") or "")), "trace": trace,
            "steps_html": ui.render_steps(ui.describe_trace(trace)), "turns_left": max(0, s.try_max_turns - info["turns"]),
            **({"heard": ui.scrub(str(result.get("heard") or ""))} if "heard" in result else {}), **({"_audio": result["audio"]} if "audio" in result else {})}


@router.post("/turn")
async def turn(request: Request, _=Depends(enabled)):
    svc = request.app.state.svc
    body = await body_of(request)
    if isinstance(body, JSONResponse):
        return body
    session, text = body.get("session"), body.get("text")
    if not isinstance(session, str) or not isinstance(text, str):
        return refuse(400, "Send the session and the text.")
    text = CONTROL.sub("", text).strip()
    if not text:
        return refuse(400, "Please type a message.")
    if len(text) > MAX_CHARS:
        return refuse(400, f"Please keep it to {MAX_CHARS} characters or fewer.")
    return await guarded(request, session, lambda: voice.run_text_turn(svc, session, text))


@router.post("/pay")
async def pay(request: Request, _=Depends(enabled)):
    """The visitor makes the transfer for a payment of their own conversation, as a caller would from their bank app. Every payment of this build is a test one:
    simulated, or made in Paystack's test mode (a live key is refused), and Paystack's test mode has no way to pretend that a customer paid."""
    from sqlalchemy import select

    from ..models import Call, Payment
    from .payments import confirm

    svc = request.app.state.svc
    body = await body_of(request)
    if isinstance(body, JSONResponse):
        return body
    session, reference = body.get("session"), body.get("reference")
    if not isinstance(session, str) or session not in state(request)["sessions"] or not isinstance(reference, str):
        return refuse(404, "This conversation has expired. Please start over.")
    st = svc.sessions.get(session) or {}
    with svc.session_factory() as db:
        call = db.get(Call, uuid.UUID(st["call_id"])) if st.get("call_id") else None
        row = db.scalar(select(Payment).where(Payment.reference == reference))
        if not call or not row or row.caller_id != call.caller_id or row.channel not in ("simulated", "paystack"):
            return refuse(404, "There is no such payment in this conversation.")
    if not await confirm(svc, reference):
        return {"paid": True, "already": True}
    return {"paid": True}


@router.post("/speak")
async def speak(request: Request, _=Depends(enabled)):
    """One spoken turn of a call made from the browser. The page sends the caller's speech as a WAV file in base64; it is heard, answered and voiced like a
    phone call, and it is not kept."""
    svc = request.app.state.svc
    body = await body_of(request)
    if isinstance(body, JSONResponse):
        return body
    session, data = body.get("session"), body.get("audio")
    if not isinstance(session, str) or not isinstance(data, str):
        return refuse(400, "Send the session and the audio.")
    if len(data) > MAX_AUDIO_BYTES * 4 // 3 + 4:
        return refuse(413, "That was too long. Please say one sentence at a time.")
    try:
        audio = base64.b64decode(data, validate=True)
    except ValueError:
        return refuse(400, "The audio could not be read.")
    if not (audio.startswith(b"RIFF") and audio[8:12] == b"WAVE") and not audio.startswith(b"MOCK["):
        return refuse(415, "Send the speech as a WAV file.")
    if body.get("stream"):     # the page shows each step as it happens, then the reply
        return StreamingResponse(live_turn(request, session, audio), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
    out = await guarded(request, session, lambda: voice.run_spoken_turn(svc, session, audio))
    if isinstance(out, JSONResponse):
        return out
    result_audio = [path_of(u) for u in (out.pop("_audio", None) or [])]
    return out | {"audio": result_audio}


async def live_turn(request: Request, session: str, audio: bytes):
    """One line of JSON for each step of the turn as it happens (sofa/progress.py), then the reply itself, or the reason there is none."""
    import json

    from .. import progress

    svc = request.app.state.svc
    queue: asyncio.Queue = asyncio.Queue()
    token = progress.listening.set(queue)
    task = asyncio.create_task(guarded(request, session, lambda: voice.run_spoken_turn(svc, session, audio)))   # the turn carries the queue with it
    progress.listening.reset(token)
    while not task.done() or not queue.empty():
        try:
            event = await asyncio.wait_for(queue.get(), timeout=0.2)
        except asyncio.TimeoutError:
            continue
        if "text" in event:
            event["text"] = ui.scrub(str(event["text"]))[:200]
        yield json.dumps(event) + "\n"
    out = task.result()
    if isinstance(out, JSONResponse):
        yield json.dumps({"error": json.loads(out.body).get("error", "Something went wrong. Please try again.")}) + "\n"
        return
    result_audio = [path_of(u) for u in (out.pop("_audio", None) or [])]
    yield json.dumps({"done": out | {"audio": result_audio}}) + "\n"
