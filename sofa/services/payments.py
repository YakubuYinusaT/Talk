"""Paying for a visit or a medicine by bank transfer: Talk gets an account number tied to one payment and sends it to the caller by text.

With a Paystack test key (sk_test_...) in PAYSTACK_SECRET_KEY, the account comes from Paystack's Pay with Transfer in test mode: a temporary account for this one
payment, valid for up to eight hours, and Paystack's charge.success webhook says when the money arrived. A live key is refused, so this build never takes real
money. Without a test key, the account is simulated, like the hospitals and pharmacies of this build: the bank is named as a test bank, and the transfer is
confirmed from the Try it page. Either way the caller hears the amount and the account, gets them by text, and the clinic or pharmacy front desk shows whether
the payment has arrived.
"""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Payment

log = logging.getLogger("sofa.payments")

PAYSTACK = "https://api.paystack.co"
SIMULATED_BANK = "Talk Test Bank"
LINK_SUFFIX = "-LINK"     # the same payment, paid through its one-time link: Paystack needs a reference of its own for it


def new_reference() -> str:
    """Letters only, so that no run of digits in it is ever taken for a phone number and hidden on a page."""
    return "PAY-" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(8))


def simulated_account(reference: str, secret: str) -> str:
    """A ten-digit account number for a simulated payment: steady for the reference, and never a real bank's."""
    digits = int(hmac.new(secret.encode(), reference.encode(), hashlib.sha256).hexdigest(), 16) % 10**8
    return f"99{digits:08d}"


async def request_transfer(db: Session, settings, *, amount: int, purpose: str, code: str, place: str, caller_id=None) -> Payment | None:
    """An account number for the caller to pay `amount` naira into, for one visit or one order. None when no account could be had (the caller then pays at
    the counter, as before)."""
    reference = new_reference()
    expires = datetime.now(timezone.utc) + timedelta(hours=max(1, min(8, settings.payment_hours)))
    row = Payment(reference=reference, purpose=purpose, code=code, place=place[:160], amount=int(amount), caller_id=caller_id, expires_at=expires)
    key = settings.paystack_secret_key if settings.paystack_secret_key.startswith("sk_test_") else ""
    if settings.paystack_secret_key and not key:     # this build takes no real money: a live key is never used, and the account is simulated instead
        log.error("PAYSTACK_SECRET_KEY is not a test key (sk_test_...): it is ignored and the payment is simulated")
    if key:
        try:
            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.post(f"{PAYSTACK}/charge", headers={"Authorization": f"Bearer {key}"},
                                       json={"email": f"{reference.lower()}@pay.talk", "amount": int(amount) * 100, "reference": reference,
                                             "bank_transfer": {"account_expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ")}})
            data = resp.json().get("data") or {}
            if resp.status_code >= 300 or not data.get("account_number"):
                log.error("Paystack gave no transfer account for %s: HTTP %s %s", reference, resp.status_code, (resp.json().get("message") if resp.content else ""))
                return None
            row.channel, row.account_number = "paystack", str(data["account_number"])
            row.bank = settings.payment_account_label or str((data.get("bank") or {}).get("name") or "the bank")
            given = str(data.get("account_name") or "")
            row.account_name = given if given and "PAYSTACK" not in given.upper() else f"Talk for {place}"[:160]     # not Paystack's generic checkout name
        except (httpx.HTTPError, ValueError) as exc:
            log.error("Paystack could not be reached for %s: %s", reference, type(exc).__name__)
            return None
    else:
        row.channel, row.bank = "simulated", settings.payment_account_label or SIMULATED_BANK
        row.account_number = simulated_account(reference, settings.at_callback_secret)
        row.account_name = f"Talk for {place}"[:160]
    db.add(row)
    db.flush()
    row.link = await one_time_link(settings, key, row)
    return row


async def one_time_link(settings, key: str, row: Payment) -> str:
    """A link the caller can open to pay the same amount by card, transfer or USSD, good for this one payment: Paystack's own checkout in test mode, or the
    simulated checkout page on this site. Empty when Paystack gave none (the account number still works)."""
    if not key:
        return f"{str(settings.public_base_url).rstrip('/')}/pay/{row.reference}"
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(f"{PAYSTACK}/transaction/initialize", headers={"Authorization": f"Bearer {key}"},
                                   json={"email": f"{row.reference.lower()}@pay.talk", "amount": row.amount * 100, "reference": row.reference + LINK_SUFFIX})
        return str((resp.json().get("data") or {}).get("authorization_url") or "") if resp.status_code < 300 else ""
    except (httpx.HTTPError, ValueError) as exc:
        log.error("Paystack gave no payment link for %s: %s", row.reference, type(exc).__name__)
        return ""


def spaced(number: str) -> str:
    """An account number read out in pairs and threes, the way a person says it on the phone."""
    return " ".join(number[i:i + 2] for i in range(0, len(number), 2))


def mark_paid(db: Session, reference: str) -> Payment | None:
    """The money arrived, by transfer to the account or through the one-time link. Returns the payment when it was waiting for it, so that the caller is
    texted a receipt once."""
    reference = reference.removesuffix(LINK_SUFFIX)
    row = db.scalar(select(Payment).where(Payment.reference == reference))
    if not row or row.status == "paid":
        return None
    row.status, row.paid_at = "paid", datetime.now(timezone.utc)
    return row


def of_codes(session_factory, codes: set[str]) -> dict[str, dict]:
    """The latest payment for each booking or order code, for a front desk: how much, and whether it has arrived."""
    if not codes:
        return {}
    found: dict[str, dict] = {}
    with session_factory() as db:
        for row in db.scalars(select(Payment).where(Payment.code.in_(list(codes))).order_by(Payment.created_at)):
            found[row.code] = {"amount": row.amount, "status": row.status, "channel": row.channel}
    return found


def signature_ok(secret: str, body: bytes, given: str) -> bool:
    """Paystack signs each webhook with HMAC-SHA512 of the raw body, keyed with the secret key."""
    return bool(secret) and hmac.compare_digest(hmac.new(secret.encode(), body, hashlib.sha512).hexdigest(), given or "")
