"""Payments arriving: Paystack's webhook for a real transfer, and the confirmation of a simulated one (sofa/services/payments.py). Either way the caller is texted
a receipt once, and the clinic's or pharmacy's front desk shows the visit or the order as paid."""

import html
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select

from ..dialogue.service_phrases import PHRASES
from ..models import Caller, Payment
from ..services import payments
from ..services.notify import send_sms

log = logging.getLogger("sofa.payments")
router = APIRouter()


async def confirm(svc, reference: str) -> bool:
    """Mark a payment as arrived and text the caller a receipt. False when there was no such payment waiting."""
    with svc.session_factory() as db:
        row = payments.mark_paid(db, reference)
        if row is None:
            return False
        person = db.get(Caller, row.caller_id) if row.caller_id else None
        if person:
            body = PHRASES["health_sms_paid"][0].format(amount=f"{row.amount:,}", code=row.code, place=row.place)
            await send_sms(db, svc, to=person.phone, body=body, template="health_paid", caller_id=person.id)
        db.commit()
    return True


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pay · Talk</title><link rel="stylesheet" href="/static/ci.css"></head><body><main class="container" style="max-width:28rem;padding:2rem 1rem">
<h1>Pay &#8358;{amount}</h1><p>{place} · {code}</p><p class="muted small">Test checkout. No real money moves.</p>{action}</main></body></html>"""


@router.get("/pay/{reference}", include_in_schema=False)
def checkout(reference: str, request: Request):
    """The simulated checkout behind a one-time link, for a payment that has no Paystack account behind it."""
    svc = request.app.state.svc
    with svc.session_factory() as db:
        row = db.scalar(select(Payment).where(Payment.reference == reference))
        if not row or row.channel != "simulated":
            raise HTTPException(status_code=404)
        action = ('<p><b>Paid ✓</b></p>' if row.status == "paid" else
                  f'<form method="post"><button type="submit">Pay &#8358;{row.amount:,} (test)</button></form>')
        return HTMLResponse(PAGE.format(amount=f"{row.amount:,}", place=html.escape(row.place), code=html.escape(row.code), action=action),
                            headers={"Cache-Control": "no-store"})


@router.post("/pay/{reference}", include_in_schema=False)
async def checkout_paid(reference: str, request: Request):
    svc = request.app.state.svc
    with svc.session_factory() as db:
        row = db.scalar(select(Payment).where(Payment.reference == reference))
        if not row or row.channel != "simulated":
            raise HTTPException(status_code=404)
    await confirm(svc, reference)
    return RedirectResponse(f"/pay/{reference}", status_code=303)


@router.post("/payments/paystack", include_in_schema=False)
async def paystack_webhook(request: Request):
    """Paystack says what happened to a payment. Only a request signed with the secret key is believed, and only charge.success marks a payment as paid."""
    svc = request.app.state.svc
    body = await request.body()
    key = svc.settings.paystack_secret_key if svc.settings.paystack_secret_key.startswith("sk_test_") else ""
    if not payments.signature_ok(key, body, request.headers.get("x-paystack-signature", "")):
        raise HTTPException(status_code=401, detail="bad signature")
    try:
        event = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="not JSON") from None
    if event.get("event") == "charge.success":
        reference = str((event.get("data") or {}).get("reference") or "")
        if reference and not await confirm(svc, reference):
            log.info("a charge.success for an unknown or already paid reference")
    return Response("ok")
