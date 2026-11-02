"""Fixes that followed an outside review: an honest /health, no secret that is published with the code guarding anything on a public address, a demo page that hides
what callers said unless it is asked to show it, recordings downloaded only from the hosts of the telephony provider, and recordings deleted after their time."""

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from sofa.audio import check_recording_address, fetch_recording
from sofa.config import Settings
from sofa.hardening import KNOWN_DEFAULTS, replace_known_defaults
from sofa.main import create_app
from sofa.models import Call, CallTurn
from sofa.services import retention
from tests.support import CALLER, call


def settings(tmp_path, **more):
    return Settings(database_url="sqlite://", storage_dir=str(tmp_path), at_callback_secret="a-real-secret", public_base_url="http://test", scheduler_enabled=False,
                    _env_file=None, **more)


# ---- /health says which voice callers hear ---------------------------------------------------------------------------------------------


def test_health_names_the_hosted_voice_and_whether_it_has_a_back_up_voice_on_the_machine(tmp_path):
    bare = TestClient(create_app(settings(tmp_path, tts_provider="spitch", spitch_api_key="k"))).get("/health").json()
    assert bare["tts"] == "spitch, no back-up voice" and "mock" not in bare["tts"]
    backed = TestClient(create_app(settings(tmp_path, tts_provider="spitch", spitch_api_key="k", piper_model="/voices/x.onnx"))).get("/health").json()
    assert backed["tts"] == "spitch, with a voice on this machine as back-up"
    assert TestClient(create_app(settings(tmp_path, piper_model="/voices/x.onnx"))).get("/health").json()["tts"] == "a voice on this machine"
    assert TestClient(create_app(settings(tmp_path))).get("/health").json()["tts"] == "stand-in (silent)"      # With no key and no voice file the silent stand-in is named.
    assert "streamed_calls" in bare


# ---- no secret that is published with the code guards anything on a public address ----------------------------------------------------------


def test_on_an_https_address_every_secret_left_at_its_published_value_is_replaced():
    s = Settings(_env_file=None, public_base_url="https://talk.example")
    assert all(getattr(s, name) == default for name, default in KNOWN_DEFAULTS.items())
    replaced = replace_known_defaults(s)
    assert set(replaced) == {n.upper() for n in KNOWN_DEFAULTS}
    assert all(getattr(s, name) != default and not getattr(s, name).startswith("dev-") and len(getattr(s, name)) >= 24 for name, default in KNOWN_DEFAULTS.items())
    assert len({getattr(s, name) for name in KNOWN_DEFAULTS}) == len(KNOWN_DEFAULTS)      # Each replacement is different from the others.


def test_a_secret_somebody_chose_is_left_alone_and_a_local_address_is_not_touched():
    chosen = Settings(_env_file=None, public_base_url="https://talk.example", at_callback_secret="chosen-by-the-owner")
    assert replace_known_defaults(chosen) == [] and chosen.at_callback_secret == "chosen-by-the-owner"
    local = Settings(_env_file=None, public_base_url="http://localhost:8000")
    assert replace_known_defaults(local) == [] and local.at_callback_secret == "dev-secret"


def test_the_application_replaces_a_published_secret_when_it_starts(tmp_path):
    app = create_app(Settings(database_url="sqlite://", storage_dir=str(tmp_path), public_base_url="https://talk.example", scheduler_enabled=False, _env_file=None))
    assert app.state.svc.settings.at_callback_secret != "dev-secret"
    published = TestClient(app).post("/voice/inbound/dev-secret", data={"sessionId": "s", "callerNumber": CALLER})
    assert published.status_code == 404      # The secret that is published with the code opens nothing.


def test_each_provider_has_its_own_secret_and_all_of_them_follow_the_callback_secret():
    s = Settings(_env_file=None, at_callback_secret="one-secret")
    assert s.provider_secret("state-phc") != s.provider_secret("eko-care")
    assert s.provider_secret("state-phc") != Settings(_env_file=None, at_callback_secret="another-secret").provider_secret("state-phc")


# ---- the demo page hides what callers said unless it is told to show it ------------------------------------------------------------------


def test_the_demo_page_does_not_exist_unless_it_is_switched_on(client):
    assert client.get("/demo").status_code == 404


def test_the_demo_page_shows_what_happened_but_not_what_was_said_unless_it_is_told_to(client, happ):
    happ.state.svc.settings.demo_page_enabled = True
    call(client, ["Hello, do you have amoxicillin in stock, please?", "Amoxicillin five hundred milligram capsules, please."])
    html = client.get("/demo").text
    assert 'data-words="hidden"' in html
    assert "do you have amoxicillin in stock" not in html and CALLER not in html and CALLER[-4:] in html      # Only the last four digits of the number are shown.
    happ.state.svc.settings.demo_show_calls = True
    shown = client.get("/demo").text
    assert "do you have amoxicillin in stock" in shown and 'data-words="shown"' in shown and CALLER not in shown


# ---- recordings come only from the telephony provider ----------------------------------------------------------------------------------


def test_only_https_and_the_listed_hosts_and_their_subdomains_are_allowed():
    allowed = ("africastalking.com",)
    check_recording_address("https://voice.africastalking.com/rec/1.mp3", allowed)
    check_recording_address("https://africastalking.com/rec/1.mp3", allowed)
    for bad in ("http://voice.africastalking.com/1.mp3", "https://evil.example/1.mp3", "https://africastalking.com.evil.example/1.mp3", "https://notafricastalking.com/1.mp3",
                "https://169.254.169.254/latest/meta-data", "https://localhost/x", "file:///etc/passwd", "ftp://voice.africastalking.com/x"):
        with pytest.raises(ValueError):
            check_recording_address(bad, allowed)
    check_recording_address("https://anything.example/x", ())      # An empty list means that there is no restriction.


def test_a_blocked_address_is_refused_before_any_request_is_sent():
    async def attempt():
        seen = []
        http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200, content=b"AUDIO")))
        with pytest.raises(ValueError):
            await fetch_recording("http://169.254.169.254/latest/meta-data", http=http, allowed=("africastalking.com",))
        assert seen == []
        assert await fetch_recording("https://voice.africastalking.com/1.mp3", wait=0, http=http, allowed=("africastalking.com",)) == b"AUDIO" and len(seen) == 1

    asyncio.run(attempt())


def test_a_redirect_off_the_listed_hosts_is_not_followed_and_one_within_them_is():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.host == "voice.africastalking.com" and request.url.path == "/away":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})
        if request.url.host == "voice.africastalking.com" and request.url.path == "/moved":
            return httpx.Response(302, headers={"location": "https://cdn.africastalking.com/final.mp3"})
        return httpx.Response(200, content=b"AUDIO")

    async def attempt():
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with pytest.raises(ValueError):
            await fetch_recording("https://voice.africastalking.com/away", wait=0, http=http, allowed=("africastalking.com",))
        assert all("169.254" not in u for u in seen)
        assert await fetch_recording("https://voice.africastalking.com/moved", wait=0, http=http, allowed=("africastalking.com",)) == b"AUDIO"

    asyncio.run(attempt())


def test_recordings_are_limited_to_the_hosts_of_the_telephony_provider_by_default(happ):
    hosts = happ.state.svc.settings.recording_hosts
    assert hosts == ("africastalking.com", "at-internal.com")
    # A real recording on the live number came from the internal host of the provider, so the sub-domains of that host are allowed too.
    check_recording_address("https://gigantic.keller-shockley.at-internal.com/rec.mp3", hosts)
    assert Settings(_env_file=None, recording_allowed_hosts=" A.example , .b.example ").recording_hosts == ("a.example", "b.example")


# ---- recordings are deleted after their time -------------------------------------------------------------------------------------------


def make_turn(svc, tmp_path, days_old, name):
    path = tmp_path / "audio_in" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b"RIFF")
    with svc.session_factory() as db:
        phone_call = Call(provider_session_id=name, from_number="+2348055550101", to_number="+2348000009999")
        db.add(phone_call)
        db.flush()
        db.add(CallTurn(call_id=phone_call.id, seq=1, audio_path=str(path), created_at=datetime.now(timezone.utc) - timedelta(days=days_old)))
        db.commit()
    return path


def test_old_recordings_are_deleted_and_recent_ones_are_kept(happ, tmp_path):
    svc = happ.state.svc
    svc.settings.storage_dir, svc.settings.recording_retention_days = str(tmp_path), 30
    old, recent = make_turn(svc, tmp_path, 45, "old.wav"), make_turn(svc, tmp_path, 3, "recent.wav")
    assert retention.purge_recordings(svc) == 1
    assert not old.exists() and recent.exists()
    with svc.session_factory() as db:
        paths = {t.audio_path for t in db.scalars(select(CallTurn))}
    assert str(recent) in paths and str(old) not in paths and None in paths      # The record of the call stays, but without the sound.
    assert retention.purge_recordings(svc) == 0                                  # There is nothing more to delete the second time.


def test_a_recording_that_no_turn_points_to_is_swept_by_its_age(happ, tmp_path):
    svc = happ.state.svc
    svc.settings.storage_dir, svc.settings.recording_retention_days = str(tmp_path), 30
    (tmp_path / "audio_in").mkdir(exist_ok=True)
    orphan = tmp_path / "audio_in" / "orphan.wav"
    orphan.write_bytes(b"RIFF")
    long_ago = time.time() - 45 * 86400
    os.utime(orphan, (long_ago, long_ago))
    assert retention.purge_recordings(svc) == 1 and not orphan.exists()


def test_with_a_retention_of_zero_days_nothing_is_deleted(happ, tmp_path):
    svc = happ.state.svc
    svc.settings.storage_dir, svc.settings.recording_retention_days = str(tmp_path), 0
    old = make_turn(svc, tmp_path, 400, "kept.wav")
    assert retention.purge_recordings(svc) == 0 and old.exists()
