"""The text message client: a message counts as sent only when the text message provider accepted it for that number, and a refusal says why."""

import asyncio
import logging

import httpx
from sqlalchemy import select

from sofa.clients import sms as sms_module
from sofa.clients.sms import SMSClient
from sofa.config import Settings
from sofa.models import Notification
from tests.support import SECRET

REAL_CLIENT = httpx.AsyncClient          # kept here: the patch below replaces httpx.AsyncClient for the whole module

NUMBER = "+2348012345678"
CONFIRMATION = "Your appointment at Yaba Lakeview Clinic is confirmed for tomorrow at nine in the morning."


def client_with(monkeypatch, handler, **settings):
    """An SMSClient whose HTTP calls go to `handler` instead of the internet. Returns (client, the requests it received)."""
    seen = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(sms_module.httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(respond), **kw))
    base = dict(_env_file=None, at_api_key="a-key", at_username="test-account", at_sandbox=False)
    return SMSClient(Settings(**{**base, **settings})), seen


def answer(code, status, **extra):
    recipient = {"statusCode": code, "number": NUMBER, "status": status, "cost": "NGN 4.0000", "messageId": "ATXid_1", **extra}
    return httpx.Response(201, json={"SMSMessageData": {"Message": "Sent to 1/1 Total Cost: NGN 4.0000", "Recipients": [recipient]}})


def run(coro):
    return asyncio.run(coro)


def test_a_message_the_provider_accepted_is_sent_and_goes_to_the_live_address(monkeypatch):
    client, seen = client_with(monkeypatch, lambda r: answer(101, "Success"), sms_sender_id="Talk")
    assert run(client.send(NUMBER, CONFIRMATION)) == ("sent", "ATXid_1")
    request = seen[0]
    assert request.url.host == "api.africastalking.com" and request.url.path == "/version1/messaging" and request.headers["apiKey"] == "a-key"
    body = request.content.decode()
    assert "username=test-account" in body and "from=Talk" in body and "to=%2B2348012345678" in body and "Yaba+Lakeview+Clinic" in body


def test_the_sandbox_address_is_used_only_when_asked_for(monkeypatch):
    client, seen = client_with(monkeypatch, lambda r: answer(101, "Success"), at_sandbox=True)
    run(client.send(NUMBER, "hello"))
    assert seen[0].url.host == "api.sandbox.africastalking.com"
    client, seen = client_with(monkeypatch, lambda r: answer(101, "Success"))
    run(client.send(NUMBER, "hello"))
    assert seen[0].url.host == "api.africastalking.com"
    assert "from=" not in seen[0].content.decode()           # no sender id set: none is sent, and the default is used


def test_a_message_refused_inside_an_ok_answer_is_a_failure_with_its_reason(monkeypatch, caplog):
    for code, status in ((402, "InvalidSenderId"), (401, "RiskHold"), (406, "UserInBlacklist"), (403, "InvalidPhoneNumber"), (407, "CouldNotRoute")):
        client, _ = client_with(monkeypatch, lambda r, c=code, s=status: answer(c, s))
        with caplog.at_level(logging.ERROR, logger="sofa.sms"):
            caplog.clear()
            status_out, message_id, reason = run(client.deliver(NUMBER, "hello"))
        assert (status_out, message_id) == ("failed", None) and status in reason and str(code) in reason
        assert status in caplog.text                         # and the server's log says why: it is never silent


def test_a_missing_recipient_or_an_http_error_is_a_failure(monkeypatch):
    client, _ = client_with(monkeypatch, lambda r: httpx.Response(201, json={"SMSMessageData": {"Message": "nothing", "Recipients": []}}))
    assert run(client.send(NUMBER, "hello")) == ("failed", None)
    client, _ = client_with(monkeypatch, lambda r: httpx.Response(401, text="The supplied authentication is invalid"))
    status, message_id, reason = run(client.deliver(NUMBER, "hello"))
    assert (status, message_id) == ("failed", None) and "401" in reason and "authentication" in reason
    client, _ = client_with(monkeypatch, lambda r: httpx.Response(200, text="not json"))
    assert run(client.send(NUMBER, "hello")) == ("failed", None)


def test_queued_and_processed_count_as_accepted(monkeypatch):
    for code, status in ((100, "Processed"), (102, "Queued")):
        client, _ = client_with(monkeypatch, lambda r, c=code, s=status: answer(c, s))
        assert run(client.send(NUMBER, "hello")) == ("sent", "ATXid_1")


def test_an_acceptance_says_what_it_cost(monkeypatch):
    client, _ = client_with(monkeypatch, lambda r: answer(101, "Success"))
    status, message_id, reason = run(client.deliver(NUMBER, "hello"))
    assert (status, message_id) == ("sent", "ATXid_1") and "NGN 4.0000" in reason and "101" in reason


def test_with_no_key_nothing_is_sent_and_the_message_is_only_logged(monkeypatch, caplog):
    client, seen = client_with(monkeypatch, lambda r: answer(101, "Success"), at_api_key="")
    with caplog.at_level(logging.INFO, logger="sofa.sms"):
        assert run(client.send(NUMBER, CONFIRMATION)) == ("mock_sent", None)
    assert not seen and "Yaba Lakeview Clinic" in caplog.text


# ---- delivery reports -------------------------------------------------------------------------------------------------


def sent_text(happ, message_id="ATXid_1"):
    """Records a text as sent, the way the front desk does after the provider accepted it."""
    with happ.state.svc.session_factory() as db:
        db.add(Notification(channel="sms", template="appointment_confirmation", to_number=NUMBER, body=CONFIRMATION, status="sent", provider_message_id=message_id))
        db.commit()


def status_of(happ, message_id="ATXid_1"):
    with happ.state.svc.session_factory() as db:
        return db.scalar(select(Notification).where(Notification.provider_message_id == message_id)).status


def test_the_delivery_address_answers_a_visit_only_with_the_right_secret(client):
    assert client.get(f"/sms/delivery/{SECRET}").text == "ok" and client.head(f"/sms/delivery/{SECRET}").status_code == 200
    assert client.get("/sms/delivery/wrong").status_code == 404
    assert client.post("/sms/delivery/wrong", data={"id": "ATXid_1", "status": "Success"}).status_code == 404


def test_a_delivery_report_updates_the_text_it_belongs_to(client, happ):
    sent_text(happ)
    client.post(f"/sms/delivery/{SECRET}", data={"id": "ATXid_1", "status": "Buffered", "phoneNumber": NUMBER, "networkCode": "62130"})
    assert status_of(happ) == "buffered"
    client.post(f"/sms/delivery/{SECRET}", data={"id": "ATXid_1", "status": "Success", "phoneNumber": NUMBER})
    assert status_of(happ) == "delivered"
    client.post(f"/sms/delivery/{SECRET}", data={"id": "ATXid_1", "status": "Sent"})         # a late, older report does not undo it
    assert status_of(happ) == "delivered"


def test_a_failed_delivery_is_recorded_and_the_reason_is_logged(client, happ, caplog):
    sent_text(happ)
    with caplog.at_level(logging.ERROR, logger="sofa.voice"):
        res = client.post(f"/sms/delivery/{SECRET}", data={"id": "ATXid_1", "status": "Failed", "phoneNumber": NUMBER, "failureReason": "AbsentSubscriber"})
    assert res.status_code == 200 and status_of(happ) == "failed"
    assert "AbsentSubscriber" in caplog.text and "2348012345678" not in caplog.text         # the reason, never the whole number


def test_a_report_for_an_unknown_text_or_an_unknown_status_is_ignored(client, happ):
    sent_text(happ)
    assert client.post(f"/sms/delivery/{SECRET}", data={"id": "nobody", "status": "Success"}).status_code == 200
    assert client.post(f"/sms/delivery/{SECRET}", data={"id": "ATXid_1", "status": "Strange"}).status_code == 200
    assert client.post(f"/sms/delivery/{SECRET}", data={}).status_code == 200
    assert status_of(happ) == "sent"
