"""Paying for a visit by bank transfer: after a booking with a fee, Sofa says the amount and an account made for that one payment, texts it, and the clinic's
front desk shows it as awaiting payment until the transfer arrives, then as paid, and the caller is texted a receipt."""

import hashlib
import hmac
import json

from sqlalchemy import select

from sofa.models import Notification, Payment
from tests.support import call

BOOK = ["I am in Surulere. When is the next available slot at a clinic?", "The first one, please.", "Yes, please."]


def test_a_booking_with_a_fee_gives_an_account_number_to_pay_into(client, hdb):
    replies = call(client, BOOK)
    assert "Your appointment is confirmed at Surulere Care Clinic" in replies[3]
    assert "The consultation fee is 8,000 naira" in replies[3] and "Talk Wallet, account number 99" in replies[3]
    row = hdb.scalars(select(Payment)).one()
    assert row.amount == 8000 and row.status == "pending" and row.channel == "simulated" and row.code.startswith("APT-")
    text = hdb.scalars(select(Notification).where(Notification.template == "health_pay")).one()
    assert row.account_number in text.body and row.reference in text.body


def test_the_desk_shows_the_payment_awaited_and_then_paid(client, happ, hdb):
    call(client, BOOK)
    row = hdb.scalars(select(Payment)).one()
    assert "Awaiting ₦8,000" in client.get("/synthetic/eko-care/").text
    from sofa.routes.payments import confirm
    import asyncio

    assert asyncio.run(confirm(happ.state.svc, row.reference))
    assert "Paid ₦8,000" in client.get("/synthetic/eko-care/").text
    hdb.expire_all()
    assert hdb.scalars(select(Notification).where(Notification.template == "health_paid")).one()


def test_a_paystack_webhook_is_believed_only_with_its_signature(client, happ, hdb):
    happ.state.svc.settings.paystack_secret_key = "sk_test_x"
    body = json.dumps({"event": "charge.success", "data": {"reference": "PAY-NOSUCHONE"}}).encode()
    assert client.post("/payments/paystack", content=body, headers={"x-paystack-signature": "wrong"}).status_code == 401
    good = hmac.new(b"sk_test_x", body, hashlib.sha512).hexdigest()
    assert client.post("/payments/paystack", content=body, headers={"x-paystack-signature": good}).status_code == 200


def test_the_try_page_can_make_the_test_transfer_for_its_own_payment_only(client, hdb):
    started = client.post("/try/start", json={}).json()
    out = {}
    for line in BOOK:
        out = client.post("/try/turn", json={"session": started["session"], "text": line}).json()
    step = next(s for s in out["trace"] if s["step"] == "payment")
    other = client.post("/try/start", json={}).json()
    assert client.post("/try/pay", json={"session": other["session"], "reference": step["reference"]}).status_code == 404
    assert client.post("/try/pay", json={"session": started["session"], "reference": step["reference"]}).json()["paid"] is True
    hdb.expire_all()
    assert hdb.scalars(select(Payment)).one().status == "paid"


def test_a_live_paystack_key_is_never_used(client, happ, hdb):
    happ.state.svc.settings.paystack_secret_key = "sk_live_should_never_be_used"
    replies = call(client, BOOK)
    assert "Talk Wallet" in replies[3]
    assert hdb.scalars(select(Payment)).one().channel == "simulated"


def test_the_text_carries_a_one_time_link_and_the_checkout_takes_the_payment(client, hdb):
    replies = call(client, BOOK)
    assert "one-time link" in replies[3]
    row = hdb.scalars(select(Payment)).one()
    text = hdb.scalars(select(Notification).where(Notification.template == "health_pay")).one()
    assert f"/pay/{row.reference}" in text.body
    page = client.get(f"/pay/{row.reference}")
    assert page.status_code == 200 and "Pay &#8358;8,000" in page.text and "No real money moves" in page.text
    client.post(f"/pay/{row.reference}")
    hdb.expire_all()
    assert hdb.scalars(select(Payment)).one().status == "paid"
    assert "Paid ✓" in client.get(f"/pay/{row.reference}").text


def test_a_payment_through_the_paystack_link_is_matched_to_its_booking(client, happ, hdb):
    call(client, BOOK)
    row = hdb.scalars(select(Payment)).one()
    happ.state.svc.settings.paystack_secret_key = "sk_test_x"
    body = json.dumps({"event": "charge.success", "data": {"reference": row.reference + "-LINK"}}).encode()
    good = hmac.new(b"sk_test_x", body, hashlib.sha512).hexdigest()
    assert client.post("/payments/paystack", content=body, headers={"x-paystack-signature": good}).status_code == 200
    hdb.expire_all()
    assert hdb.scalars(select(Payment)).one().status == "paid"
