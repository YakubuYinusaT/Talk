"""Payments arriving: Paystack's webhook for a real transfer, and the confirmation of a simulated one (sofa/services/payments.py). Either way the caller is texted
a receipt once, and the clinic's or pharmacy's front desk shows the visit or the order as paid."""

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from ..dialogue.service_phrases import PHRASES
from ..models import Caller
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
