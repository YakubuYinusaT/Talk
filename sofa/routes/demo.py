"""The live calls page (/demo): what Talk is doing on real and typed calls, for anyone who wants to see it working.

PRIVACY: it is public and read-only when switched on, so it is OFF unless DEMO_PAGE_ENABLED=true. It always shows counts, and for each recent call when it
happened, the number masked down to its last four digits, how it ended, and the steps Talk took on each turn. What the caller said and what Talk replied
(and what was read from the words) is shown only when DEMO_SHOW_CALLS=true, a demonstration where every caller knows it is shown. Any run of six or more
digits is hidden either way. Use it for the hackathon deployment only, never with real patients' calls.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from ..models import Call, CallTurn, HealthAppointment, HealthRequest, Notification
from ..web import ui
from ..web.ui import mask_phone, scrub

router = APIRouter(prefix="/demo")
templates = ui.templates

TYPED_PREFIX = "+2349990"   # the reserved numbers of conversations typed on the Try it page


def db_dep(request: Request):
    with request.app.state.svc.session_factory() as db:
        yield db


def enabled(request: Request) -> None:
    if not getattr(request.app.state.svc.settings, "demo_page_enabled", False):
        raise HTTPException(404)


def action_of(value: str | None) -> str:
    return (value or "").split("|")[0]


@router.get("")
def demo(request: Request, _=Depends(enabled), db=Depends(db_dep)):
    s = request.app.state.svc.settings
    show = bool(getattr(s, "demo_show_calls", False))
    since = datetime.now(timezone.utc) - timedelta(days=1)

    def count(q) -> int:
        return db.scalar(q) or 0

    texts = count(select(func.count(Notification.id)).where(Notification.template.in_(("health_reminder", "health_thanks", "health_missed", "health_request_reply"))))
    stats = [("Calls, last 24 hours", count(select(func.count(Call.id)).where(Call.created_at >= since))),
             ("Visits booked", count(select(func.count(HealthAppointment.id)))),
             ("Staff requests", count(select(func.count(HealthRequest.id)))),
             ("Texts sent", texts)]
    calls = []
    for c in db.scalars(select(Call).order_by(Call.created_at.desc()).limit(6)):
        turns = []
        for t in db.scalars(select(CallTurn).where(CallTurn.call_id == c.id).order_by(CallTurn.seq)):
            turns.append({"seq": t.seq, "said": scrub(t.transcript), "reply": scrub(t.reply_text), "action": action_of(t.action_taken),
                          "ms": (t.latency_ms or {}).get("total"), "steps": ui.describe_trace(getattr(t, "trace", None), show_words=show)})
        calls.append({"when": c.created_at, "from": mask_phone(c.from_number), "typed": (c.from_number or "").startswith(TYPED_PREFIX), "onboarding": (c.provider_session_id or "").startswith("onb-"), "outcome": (c.outcome or "").replace("_", " ").capitalize(), "turns": turns})
    return templates.TemplateResponse(request, "demo.html", {
        "request": request, "brand": "Talk", "stats": stats, "calls": calls, "show_calls": show, "test_number": getattr(s, "test_number", ""),
        "try_enabled": getattr(s, "try_page_enabled", True), "providers": ui.providers(),
    })
