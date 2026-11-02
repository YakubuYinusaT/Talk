"""The second telephony provider, Twilio: a visitor outside Nigeria rings a local number and reaches the same Talk, through the same turns as a call on the
first provider. Twilio's webhook points at Talk, so the call is answered as it happens. Only the voice XML and the form fields differ."""

from sqlalchemy import select

from sofa import twiml
from sofa.audio import mock_recording_url
from sofa.config import Settings
from sofa.models import Call, Notification
from sofa.routes.twilio import signature
from tests.support import SECRET

ABROAD = "+14155550142"
TWILIO_NUMBER = "+14155550100"


def ring(client, sid="CA-test-1", **headers):
    return client.post(f"/voice/twilio/inbound/{SECRET}", data={"CallSid": sid, "From": ABROAD, "To": TWILIO_NUMBER, "CallStatus": "ringing"}, headers=headers)


def say(client, text, sid="CA-test-1"):
    return client.post(f"/voice/twilio/turn/{SECRET}", data={"CallSid": sid, "RecordingUrl": mock_recording_url(text), "RecordingDuration": "3"})


def test_a_call_from_abroad_is_greeted_and_listened_to_in_twilio_voice_xml(client):
    answer = ring(client)
    assert answer.status_code == 200 and "<Play>" in answer.text
    assert f'<Record action="http://test/voice/twilio/turn/{SECRET}" method="POST"' in answer.text and 'playBeep="false"' in answer.text


def test_what_the_caller_says_goes_through_the_same_front_desk(client):
    ring(client)
    answer = say(client, "Please help me find the nearest clinic for antenatal care.")
    assert answer.status_code == 200 and "which area of Lagos" in answer.headers.get("X-Sofa-Reply-Text", "")
    assert "<Record action=" in answer.text and "/voice/twilio/turn/" in answer.text


def test_a_silent_turn_is_treated_as_silence(client):
    ring(client)
    answer = client.post(f"/voice/twilio/turn/{SECRET}", data={"CallSid": "CA-test-1", "RecordingUrl": "", "RecordingDuration": "0"})
    assert answer.status_code == 200 and "<Record" in answer.text


def test_the_end_of_the_call_closes_it(client, hdb):
    ring(client)
    client.post(f"/voice/twilio/status/{SECRET}", data={"CallSid": "CA-test-1", "CallStatus": "completed", "CallDuration": "42"})
    call = hdb.scalar(select(Call))
    assert call.from_number == ABROAD and call.duration_s == 42 and call.ended_at is not None


def test_a_wrong_secret_is_refused_without_saying_why(client):
    assert client.post("/voice/twilio/inbound/not-the-secret", data={"CallSid": "x", "From": ABROAD, "To": TWILIO_NUMBER}).status_code == 404


def test_with_a_token_set_only_a_request_signed_by_twilio_is_accepted(client, happ):
    happ.state.svc.settings.twilio_auth_token = "twilio-token"
    form = {"CallSid": "CA-signed", "From": ABROAD, "To": TWILIO_NUMBER, "CallStatus": "ringing"}
    url = f"http://test/voice/twilio/inbound/{SECRET}"
    assert client.post(f"/voice/twilio/inbound/{SECRET}", data=form, headers={"X-Twilio-Signature": "forged"}).status_code == 404
    assert client.post(f"/voice/twilio/inbound/{SECRET}", data=form, headers={"X-Twilio-Signature": signature("twilio-token", url, form)}).status_code == 200


def test_the_signature_is_the_one_twilio_documents():
    # The example from Twilio's security guide, with the value Twilio's own validator library computes for it.
    form = {"CallSid": "CA1234567890ABCDE", "Caller": "+12349013030", "Digits": "1234", "From": "+12349013030", "To": "+18005551212"}
    assert signature("12345", "https://mycompany.com/myapp.php?foo=1&bar=2", form) == "0/KCTR6DLpKmkAf8muzZqo1nDgQ="


def test_a_caller_from_abroad_is_never_told_a_text_is_on_its_way(client, hdb):
    ring(client)
    for line in ["Please help me find the nearest clinic for antenatal care.", "I am in Surulere.", "Yes, please book the private clinic.", "Tomorrow morning, please.",
                 "Yes, please go ahead."]:
        last = say(client, line)
    reply = last.headers.get("X-Sofa-Reply-Text", "")
    assert "Your appointment is confirmed" in reply and "text message" not in reply.lower()
    assert hdb.scalar(select(Notification).where(Notification.template == "health_notice")).status == "not_sent_abroad"


def test_twilio_recordings_may_be_downloaded_only_once_the_account_is_set():
    assert "api.twilio.com" not in Settings(_env_file=None).recording_hosts
    assert "api.twilio.com" in Settings(_env_file=None, twilio_account_sid="AC123").recording_hosts


def test_the_twilio_voice_xml_plays_then_records_and_can_hang_up():
    body = twiml.record(["https://x/a.wav"], "https://x/turn", 3, 20)
    assert body.index("<Play>https://x/a.wav</Play>") < body.index("<Record") and 'timeout="3"' in body and 'maxLength="20"' in body
    assert twiml.play_and_hangup(["https://x/b.wav"]).endswith("<Hangup/></Response>")
    assert '<Redirect method="POST">https://x/next</Redirect>' in twiml.redirect("https://x/next", ["https://x/c.wav"])
