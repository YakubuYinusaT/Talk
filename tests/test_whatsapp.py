"""Chatting with Sofa on WhatsApp: Meta's check of the webhook, signed messages only, a text answered through the same front desk, a photo of a prescription
read and answered, a message Meta sends twice answered once, texts such as the account to pay into sent on WhatsApp, and Meta's delivery reports kept."""

import hashlib
import hmac
import json

import pytest
from sqlalchemy import select

from sofa.models import Notification, Payment
from sofa.routes import whatsapp
from sofa.routes.whatsapp import Photo

SECRET, VERIFY, WA_ID = "app-secret", "verify-me", "2348055551234"


class FakeWhatsApp:
    phone_number_id = "123"

    def __init__(self):
        self.sent, self.photos = [], {}

    async def send_text(self, to, body):
        self.sent.append((to, body))
        return "sent", f"wamid.{len(self.sent)}"

    async def media(self, media_id):
        return self.photos.get(media_id)


@pytest.fixture
def wa(happ, monkeypatch):
    s = happ.state.svc.settings
    s.whatsapp_app_secret, s.whatsapp_verify_token, s.whatsapp_phone_number_id = SECRET, VERIFY, "123"
    happ.state.svc.whatsapp = fake = FakeWhatsApp()
    monkeypatch.setattr(whatsapp, "INLINE", True)
    whatsapp._seen.clear()
    return fake


def post(client, messages=(), statuses=(), secret=SECRET):
    body = json.dumps({"entry": [{"changes": [{"value": {"messages": list(messages), "statuses": list(statuses)}}]}]}).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/whatsapp/webhook", content=body, headers={"x-hub-signature-256": sig, "content-type": "application/json"})


def text(body, mid):
    return {"from": WA_ID, "id": mid, "type": "text", "text": {"body": body}}


def test_meta_can_check_the_webhook_with_the_verify_token(client, wa):
    ok = client.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "12345"})
    assert ok.status_code == 200 and ok.text == "12345"
    assert client.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"}).status_code == 403


def test_an_unsigned_message_is_refused(client, wa):
    assert post(client, [text("Hello", "m1")], secret="not-the-secret").status_code == 401
    assert wa.sent == []


def test_a_text_is_answered_through_the_front_desk_and_a_repeat_is_answered_once(client, wa):
    assert post(client, [text("Which pharmacy in Surulere has paracetamol?", "m1")]).status_code == 200
    post(client, [text("Which pharmacy in Surulere has paracetamol?", "m1")])
    assert len(wa.sent) == 1
    to, reply = wa.sent[0]
    assert to == WA_ID and "Everwell Pharmacy Surulere" in reply


def test_a_photo_of_a_prescription_is_read_and_answered(client, happ, wa):
    wa.photos["img1"] = (b"jpeg bytes", "image/jpeg")

    async def see(model, system, image, mime, caption=""):
        assert image == b"jpeg bytes" and system.startswith("PHOTO")
        return Photo(kind="prescription", medicines=["Paracetamol 500mg"], summary="A prescription for paracetamol.")

    happ.state.svc.llm.see = see
    post(client, [{"from": WA_ID, "id": "m2", "type": "image", "image": {"id": "img1", "caption": "I am in Surulere. Do you have this?"}}])
    assert len(wa.sent) == 1 and "Paracetamol" in wa.sent[0][1]


def test_a_photo_that_is_not_a_medicine_is_politely_refused(client, happ, wa):
    wa.photos["img2"] = (b"x", "image/jpeg")

    async def see(model, system, image, mime, caption=""):
        return Photo(kind="other")

    happ.state.svc.llm.see = see
    post(client, [{"from": WA_ID, "id": "m3", "type": "image", "image": {"id": "img2"}}])
    assert "could not read that" in wa.sent[0][1]


def test_the_account_to_pay_into_comes_on_whatsapp(client, wa, hdb):
    for i, line in enumerate(["I am in Surulere. When is the next available slot at a clinic?", "The first one, please.", "Yes, please."]):
        post(client, [text(line, f"b{i}")])
    assert "account number" in wa.sent[-1][1]
    pay = hdb.scalars(select(Payment)).one()
    assert any(pay.account_number in body for _, body in wa.sent[:-1])
    assert hdb.scalars(select(Notification).where(Notification.template == "health_pay")).one().channel == "whatsapp"


def test_delivery_reports_move_forward_only(client, wa, hdb):
    hdb.add(Notification(channel="whatsapp", template="health_pay", to_number="+" + WA_ID, body="x", status="sent", provider_message_id="wamid.9"))
    hdb.commit()
    post(client, statuses=[{"id": "wamid.9", "status": "read"}])
    post(client, statuses=[{"id": "wamid.9", "status": "delivered"}])
    hdb.expire_all()
    assert hdb.scalars(select(Notification).where(Notification.provider_message_id == "wamid.9")).one().status == "read"
