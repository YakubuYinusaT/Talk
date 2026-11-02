"""The explainer pages: what Talk is, how it works, and the four simulated providers (/overview), and the front door (/) that leads to them.

Public and read-only. They hold no person data. The things that differ from one deployment to the next (who to email, the number to call, a note about
what live testing costs) come from settings, and a block with nothing set is simply left out.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..web import ui

router = APIRouter()
templates = ui.templates


def enabled(request: Request) -> None:
    if not getattr(request.app.state.svc.settings, "overview_enabled", True):
        raise HTTPException(404)


def context(request: Request, **extra) -> dict:
    s = request.app.state.svc.settings
    return {"request": request, "brand": "Talk", "s": s, "providers": ui.providers(), "test_number": getattr(s, "test_number", ""),
            "contact_email": getattr(s, "contact_email", ""), "cost_note": getattr(s, "cost_note", ""),
            "try_enabled": getattr(s, "try_page_enabled", True), "onboard_enabled": bool(getattr(request.app.state.svc, "onboarding", None)), "retention_days": getattr(s, "recording_retention_days", 30), **extra}


@router.get("/", include_in_schema=False)
def front_door():
    return RedirectResponse("/overview", status_code=307)


@router.get("/overview")
def overview(request: Request, _=Depends(enabled)):
    return templates.TemplateResponse(request, "overview.html", context(request))


@router.get("/overview/technology")
def technology(request: Request, _=Depends(enabled)):
    return templates.TemplateResponse(request, "how_it_works.html", context(request))


@router.get("/overview/providers")
def providers(request: Request, _=Depends(enabled)):
    """The four simulated providers, with a link to each one's own front-desk page."""
    return templates.TemplateResponse(request, "providers.html", context(request))
