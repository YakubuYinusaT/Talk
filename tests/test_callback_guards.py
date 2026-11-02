"""The guards on the telephony callbacks and on what a reply carries: the secret in the address is compared in constant time, the providers' own networks
can be required as a second lock, and the reply text is not sent in a header unless the call simulator asks for it."""

from fastapi.testclient import TestClient

from sofa.config import Settings
from sofa.main import create_app
from tests.support import SECRET

CALL = {"sessionId": "guard-1", "callerNumber": "+2348055550001", "destinationNumber": "", "isActive": "1", "direction": "Inbound"}


def test_debug_headers_are_off_unless_asked_for(tmp_path):
    assert Settings(_env_file=None).debug_headers is False
    app = create_app(Settings(database_url="sqlite://", storage_dir=str(tmp_path), at_callback_secret=SECRET, public_base_url="http://test",
                              scheduler_enabled=False, _env_file=None))
    with TestClient(app) as c:
        answer = c.post(f"/voice/inbound/{SECRET}", data=CALL)
    assert answer.status_code == 200 and "X-Sofa-Reply-Text" not in answer.headers


def test_without_networks_set_a_callback_with_the_right_secret_is_accepted_from_anywhere(client):
    assert client.post(f"/voice/inbound/{SECRET}", data=CALL, headers={"X-Forwarded-For": "8.8.8.8"}).status_code == 200


def test_with_networks_set_only_the_providers_addresses_are_accepted(client, happ):
    happ.state.svc.settings.callback_allowed_networks = "102.223.37.0/24, 54.172.60.0/30"
    assert client.post(f"/voice/inbound/{SECRET}", data=CALL, headers={"X-Forwarded-For": "102.223.37.5"}).status_code == 200
    assert client.post(f"/voice/inbound/{SECRET}", data=CALL, headers={"X-Forwarded-For": "8.8.8.8"}).status_code == 404
    assert client.post(f"/voice/inbound/{SECRET}", data=CALL).status_code == 404          # no address that can be checked: refused


def test_the_last_address_the_web_server_added_is_the_one_checked(client, happ):
    happ.state.svc.settings.callback_allowed_networks = "102.223.37.0/24"
    forged = {"X-Forwarded-For": "102.223.37.5, 8.8.8.8"}                                # a caller cannot put an allowed address in front of their own
    assert client.post(f"/voice/inbound/{SECRET}", data=CALL, headers=forged).status_code == 404


def test_the_second_provider_is_guarded_the_same_way(client, happ):
    happ.state.svc.settings.callback_allowed_networks = "54.172.60.0/30"
    form = {"CallSid": "CA-guard", "From": "+14155550142", "To": "+14155550100"}
    assert client.post(f"/voice/twilio/inbound/{SECRET}", data=form, headers={"X-Forwarded-For": "54.172.60.1"}).status_code == 200
    assert client.post(f"/voice/twilio/inbound/{SECRET}", data=form, headers={"X-Forwarded-For": "8.8.8.8"}).status_code == 404
