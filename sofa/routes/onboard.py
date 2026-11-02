"""The hospital onboarding wizard (/onboard): what a hospital goes through, from choosing a template to its first confirmed appointment.

A visitor, usually a judge, makes a simulated hospital in eight pages, one step each. It is filled with made-up Lagos data, and Talk starts using it the moment it goes live.

  GET  /onboard                       step 1: welcome, and the choice of a template
  POST /onboard/start                 make a hospital from a template and set the visitor's signed cookie
  GET  /onboard/step/{n}              the page of step n (2 to 8), only as far as the visitor has got
  POST /onboard/step/{n}              save what step n asks (2 profile, 3 checklist and assistant, 4 information, 5 connection, 6 go live)
  POST /onboard/step/4/preview        what Talk may say from the information as it stands, as a fragment of a page
  GET  /onboard/api/journey           where the first appointment has got to (booked, shown on the desk, confirmed, texted): the page asks every few seconds
  POST /onboard/restart               give up this hospital and start another

Everything here answers 404 when DEMO_ONBOARDING_ENABLED is off, and no step can be opened without a hospital that belongs to the visitor's signed cookie.
"""

import logging
import secrets
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select

from ..health import followups
from ..models import Call, CallTurn, Notification
from ..onboarding import hospital_profile, preview
from ..onboarding import visitor as who
from ..onboarding.service import Refused, domain_of
from ..web import ui

log = logging.getLogger("sofa.onboarding")
router = APIRouter(prefix="/onboard")
templates = ui.templates

# The short name of each step, as the stepper shows it. The first page asks for a template, so its heading says that, and every other page is headed with the name of its step.
STEPS = ("Template", "Profile", "Setup", "Records", "Connect", "Go live", "First visit", "Summary")
FIRST_HEADING = "Choose a template"


def enabled(request: Request):
    onb = getattr(request.app.state.svc, "onboarding", None)
    if not onb:
        raise HTTPException(404)
    return onb


def go(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def context(request: Request, onb, row, step: int, **extra) -> dict:
    """What every page of the wizard needs: the stepper, the hospital and where the visitor has got to."""
    s = onb.settings
    template = hospital_profile.TEMPLATES.get(row.template) if row else None
    reached = row.step if row else 1
    # A finished step is a link back to its page, and a step that has not been done yet is only a name.
    steps = [(name, ("/onboard" if n == 1 else f"/onboard/step/{n}") if n <= min(reached, step - 1) else "") for n, name in enumerate(STEPS, 1)]
    return {"request": request, "row": row, "profile": row.profile if row else {}, "step": step, "total": len(STEPS), "title": FIRST_HEADING if step == 1 else STEPS[step - 1],
            "steps": steps, "accent": template["accent"] if template else "green", "tpl": template, "expires": ui._lagos(row.expires_at) if row else "",
            "errors": {}, "typed": {}, "slug": row.slug if row else "", "desk": f"/synthetic/{row.slug}/" if row else "",
            "demo_page": bool(getattr(s, "demo_page_enabled", False)), "try_page": bool(getattr(s, "try_page_enabled", True)), "max_chars": 300, "test_number": getattr(s, "test_number", ""), **extra}


def page(request: Request, onb, row, step: int, name: str, status: int = 200, **extra):
    return templates.TemplateResponse(request, f"onboard/{name}.html", context(request, onb, row, step, **extra), status_code=status, headers={"Cache-Control": "no-store"})


def typed_of(form) -> dict:
    out = {k: form.get(k) for k in form.keys()}
    out["services"] = form.getlist("services")
    return out


def values_of(profile: dict, typed: dict) -> dict:
    """What a form shows: what the visitor typed when a field was refused, otherwise what is kept."""
    shown = {k: profile.get(k) for k in ("name", "address", "area", "owner", "kind", "fee", "wait", "services", "capacity")}
    shown["hours"] = profile.get("hours_preset")
    shown.update({k: v for k, v in typed.items() if v is not None})
    return shown


# ---- step 1: welcome ----------------------------------------------------------------------------------------------------


@router.get("")
def welcome(request: Request, onb=Depends(enabled)):
    with onb.svc.session_factory() as db:
        row = onb.hospital_of(db, onb.visitor_of(request))
        return page(request, onb, row, 1, "step1", templates_list=hospital_profile.TEMPLATES)


@router.post("/start")
async def start(request: Request, onb=Depends(enabled)):
    form = await request.form()
    visitor, cookie = onb.visitor_of(request), None
    if not visitor:
        visitor, cookie = who.issue(onb.key)
    with onb.svc.session_factory() as db:
        try:
            from .tryit import client_ip

            row = onb.create(db, visitor, client_ip(request), str(form.get("template") or ""))
        except hospital_profile.Invalid as exc:
            return page(request, onb, onb.hospital_of(db, visitor), 1, "step1", 400, templates_list=hospital_profile.TEMPLATES, problem=str(exc))
        except Refused as exc:
            return page(request, onb, onb.hospital_of(db, visitor), 1, "step1", exc.status, templates_list=hospital_profile.TEMPLATES, problem=exc.message)
    response = go("/onboard/step/2")
    if cookie:
        response.set_cookie(who.COOKIE, cookie, max_age=onb.settings.demo_onboarding_hours * 3600, httponly=True, samesite="lax", secure=str(onb.settings.public_base_url).startswith("https://"), path="/")
    return response


# ---- the pages of steps 2 to 8 ----------------------------------------------------------------------------------------------


def render_2(request, onb, db, row, errors=None, typed=None, status=200):
    v = values_of(row.profile, typed or {})
    hours = [(key, choice[0]) for key, choice in hospital_profile.HOURS.items()]
    if v.get("hours") == "custom":
        hours.insert(0, ("custom", "Custom hours"))      # hours that were changed in the records step are kept until the visitor picks a preset again
    return page(request, onb, row, 2, "step2", status, errors=errors or {}, typed=typed or {}, v=v, areas=list(hospital_profile.data.AREAS), services=hospital_profile.SERVICES,
                kind_options=[(k, k.capitalize()) for k in hospital_profile.KINDS], owners=hospital_profile.OWNERS, hour_options=hours)


def render_3(request, onb, db, row, errors=None, typed=None, status=200):
    profile = row.profile
    ticks = {k: (typed or {}).get(f"check_{k}") == "on" for k, _, _ in hospital_profile.CHECKLIST} if typed else profile["checklist"]
    suggestion = profile.get("assistant") or profile.get("assistant_suggestion") or {}
    typed = typed or {}
    return page(request, onb, row, 3, "step3", status, errors=errors or {}, checklist=hospital_profile.CHECKLIST, ticks=ticks, roles=hospital_profile.ROLES,
                assistant_name=typed.get("assistant_name", suggestion.get("name", "")), assistant_role=typed.get("role", suggestion.get("role", hospital_profile.ROLES[0])),
                saved=request.query_params.get("saved") == "1", has_account=bool(profile.get("assistant") and row.desk_key), desk_key=row.desk_key or "")


def render_4(request, onb, db, row, errors=None, profile=None, status=200):
    profile = profile or row.profile
    shown = list(profile["guide"]) + [{"title": "", "answer": "", "keywords": ""}] * (hospital_profile.MAX_GUIDE_ENTRIES - len(profile["guide"]))
    return page(request, onb, row, 4, "step4", status, errors=errors or {}, profile=profile, weekdays=hospital_profile.WEEKDAYS, entries=shown, items_preview=preview.build(profile, row.template, onb.clock()),
                capacities=[(c, c) for c in hospital_profile.CAPACITIES], provider_ready=row.slug in onb.apps, samples=SAMPLE_COUNT)


SAMPLE_COUNT = 4


async def render_5(request, onb, db, row, errors=None, status=200):
    connection = row.profile.get("connection")
    return page(request, onb, row, 5, "step5", status, errors=errors or {}, signing_secret=row.secret or "", endpoint=onb.settings.provider_endpoint(row.slug), connection=connection,
                connected=bool(row.secret), domain=domain_of(row.slug), ok=bool(connection and connection.get("ok")), tried=request.query_params.get("tested") == "1")


async def render_6(request, onb, db, row, errors=None, typed=None, status=200):
    live = row.state == "live"
    glimpse = await onb.glimpse(db, row) if live else None
    script = [{"title": "Find a clinic", "lines": hospital_profile.suggested_conversation(row.profile, 2)}]
    return page(request, onb, row, 6, "step6", status, errors=errors or {}, typed=typed or {}, live=live, glimpse=glimpse, scripts=script, phone_on=bool(row.owner_phone and row.phone_consent_at),
                ok=bool((row.profile.get("connection") or {}).get("ok")))


def render_7(request, onb, db, row):
    script = [{"title": "Book a visit", "lines": hospital_profile.suggested_conversation(row.profile, 5)}]
    return page(request, onb, row, 7, "step7", scripts=script, embed=f"/synthetic/{row.slug}/?embed=1")


def render_8(request, onb, db, row):
    tag, replay = who.tag(row.visitor), []
    calls = list(db.scalars(select(Call).where(Call.provider_session_id.like(f"onb-{tag}-%")).order_by(Call.created_at)))
    for number, call in enumerate(calls, 1):
        for turn in db.scalars(select(CallTurn).where(CallTurn.call_id == call.id).order_by(CallTurn.seq)):
            replay.append({"call": number, "seq": turn.seq, "said": ui.scrub(turn.transcript), "reply": ui.scrub(turn.reply_text), "steps": ui.describe_trace(turn.trace, show_words=True)})
    appts = onb.appointments(row)
    events = row.profile.get("events", {})
    stamps = [(label, ui._lagos(_when(events[key]))) for key, label in (("created", "Hospital created"), ("connected", "Connection made"), ("live", "Went live"),
                                                                       ("booked", "Visit booked"), ("confirmed", "Visit confirmed and patient texted")) if key in events]
    return page(request, onb, row, 8, "step8", replay=replay[:60], appointments=appts, stamps=stamps, calls=len(calls), confirmation=confirmation_of(db, appts))


def _when(iso: str):
    from datetime import datetime

    return datetime.fromisoformat(iso)


def confirmation_of(db, appointments: list[dict]) -> dict | None:
    """The text that told the patient the hospital had confirmed the visit, exactly as it was sent, and what became of it."""
    for a in appointments:
        note = db.scalar(select(Notification).where(Notification.template == "health_confirmed", Notification.body.contains(a["code"])).order_by(Notification.created_at.desc()))
        if note:
            real = note.status == "sent"
            return {"code": a["code"], "text": ui.scrub(note.body), "status": note.status, "real": real, "to": ui.mask_phone(note.to_number) if real else "",
                    "words": ("Sent to the number ending " + note.to_number[-4:] + ".") if real
                    else "Simulated. No real phone was texted." if note.status == "mock_sent" else f"Not sent ({note.status})."}
    return None


@router.get("/step/{n}")
async def step_page(n: int, request: Request, onb=Depends(enabled)):
    if not 1 <= n <= len(STEPS):
        raise HTTPException(404)
    if n == 1:
        return go("/onboard")
    with onb.svc.session_factory() as db:
        row = onb.hospital_of(db, onb.visitor_of(request))
        if not row:
            return go("/onboard")
        if n == 8 and row.state == "live" and request.query_params.get("skip") == "1":   # a visitor may go on to the summary without confirming a visit
            onb.save(db, row, step=8)
        if n > row.step:
            return go(f"/onboard/step/{row.step}")
        if n == 2:
            return render_2(request, onb, db, row)
        if n == 3:
            return render_3(request, onb, db, row)
        if n == 4:
            return render_4(request, onb, db, row)
        if n == 5:
            return await render_5(request, onb, db, row)
        if n == 6:
            return await render_6(request, onb, db, row)
        if n == 7:
            if row.state != "live":
                return go("/onboard/step/6")
            return render_7(request, onb, db, row)
        return render_8(request, onb, db, row)


@router.post("/step/4/preview", response_class=HTMLResponse)
async def preview_4(request: Request, onb=Depends(enabled)):
    form = await request.form()
    with onb.svc.session_factory() as db:
        row = onb.hospital_of(db, onb.visitor_of(request))
        if not row:
            raise HTTPException(404)
        profile, problems = hospital_profile.read_information_form(form, row.profile)
        return templates.TemplateResponse(request, "onboard/_preview.html", {"request": request, "items_preview": preview.build(profile, row.template, onb.clock()), "problems": len(problems)},
                                          headers={"Cache-Control": "no-store"})


@router.post("/step/{n}")
async def step_post(n: int, request: Request, onb=Depends(enabled)):
    if n not in (2, 3, 4, 5, 6):
        raise HTTPException(404)
    form = await request.form()
    with onb.svc.session_factory() as db:
        row = onb.hospital_of(db, onb.visitor_of(request))
        if not row:
            return go("/onboard")
        if n > row.step:
            return go(f"/onboard/step/{row.step}")
        if n == 2:
            profile, problems = hospital_profile.read_profile_form(form, row.profile)
            if problems:
                return render_2(request, onb, db, row, problems, typed_of(form), 400)
            onb.save(db, row, profile, step=max(row.step, 3))
            onb.sync(row)
            return go("/onboard/step/3")
        if n == 3:
            profile, problems = hospital_profile.read_checklist_form(form, row.profile)
            if problems:
                return render_3(request, onb, db, row, problems, typed_of(form), 400)
            onb.save(db, row, profile, step=max(row.step, 4), desk_key=row.desk_key or secrets.token_urlsafe(9))
            onb.sync(row)
            return go("/onboard/step/3?saved=1#account")
        if n == 4:
            profile, problems = hospital_profile.read_information_form(form, row.profile)
            if problems:
                return render_4(request, onb, db, row, problems, profile, 400)
            onb.save(db, row, profile, step=max(row.step, 5))
            onb.sync(row)
            return go("/onboard/step/5")
        if n == 5:
            action = str(form.get("action") or "")
            if action == "connect":
                onb.connect(db, row)
                return go("/onboard/step/5")
            if not row.secret:
                return await render_5(request, onb, db, row, {"connection": "Please create the connection first."}, 400)
            if action == "test":
                await onb.test_connection(db, row)
                return go("/onboard/step/5?tested=1#test")
            if action == "continue":
                if not (row.profile.get("connection") or {}).get("ok"):
                    return await render_5(request, onb, db, row, {"connection": "Please test the connection first."}, 400)
                onb.save(db, row, step=max(row.step, 6))
                return go("/onboard/step/6")
            return go("/onboard/step/5")
        # n == 6
        if not (row.profile.get("connection") or {}).get("ok"):
            return go("/onboard/step/5")
        raw, consent = str(form.get("phone") or "").strip(), form.get("consent") == "on"
        phone = None
        if raw or consent:
            try:
                if not raw:
                    raise hospital_profile.Invalid("Please write your phone number, or clear the box.")
                if not consent:
                    raise hospital_profile.Invalid("Please tick the box, or clear the phone number.")
                phone = onb.phone_of(raw)
            except hospital_profile.Invalid as exc:
                return await render_6(request, onb, db, row, {"phone": str(exc)}, typed_of(form), 400)
        onb.go_live(db, row, phone)
        return go("/onboard/step/6")


@router.get("/api/journey")
async def journey(request: Request, onb=Depends(enabled)):
    with onb.svc.session_factory() as db:
        row = onb.hospital_of(db, onb.visitor_of(request))
        if not row or row.state != "live":
            return JSONResponse({"error": "No live hospital was found."}, status_code=404, headers={"Cache-Control": "no-store"})
        await followups.announce_confirmations(onb.svc, domain=domain_of(row.slug))     # a visit the staff have just confirmed is texted to the patient now, not at the next pass
        appts = onb.appointments(row)
        found = confirmation_of(db, appts)
        if appts:
            onb.event(db, row, "booked")
        if found:
            onb.event(db, row, "confirmed")
            onb.save(db, row, step=max(row.step, 8))
        return JSONResponse({"booked": bool(appts), "appointments": ui.scrub_data(appts), "confirmed": bool(found), "confirmation": ui.scrub_data(found), "expires": ui._lagos(row.expires_at)},
                            headers={"Cache-Control": "no-store"})


@router.post("/restart")
async def restart(request: Request, onb=Depends(enabled)):
    with onb.svc.session_factory() as db:
        row = onb.hospital_of(db, onb.visitor_of(request))
        if row:
            onb.retire(db, row)
    return go("/onboard")
