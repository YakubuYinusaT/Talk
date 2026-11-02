"""The public pages (home, how it works, providers): they open for anyone without a login, hold very little text, follow the shared shell, show only what the deployment has set, and hold no secrets."""

import re

import pytest
from fastapi.testclient import TestClient

from sofa.config import Settings
from sofa.main import create_app

HEADLINE = "Talk: Helping you access essential services, from the phone people already have."
PAGES = ["/overview", "/overview/technology", "/overview/providers"]
SLUGS = ("state-phc", "eko-care", "everwell", "onc-centre")


def make(tmp_path, **more):
    settings = dict(synthetic_hospital=True, services_enabled="health", database_url="sqlite://", storage_dir=str(tmp_path), at_callback_secret="x",
                    public_base_url="http://test", scheduler_enabled=False, _env_file=None)
    settings.update(more)
    return TestClient(create_app(Settings(**settings)))


@pytest.fixture
def site(tmp_path):
    with make(tmp_path, demo_page_enabled=True, test_number="+234 805 555 0100") as client:
        yield client


def main_of(page: str) -> str:
    """The main area of a page, as plain text with the scripts, styles and pictures taken out."""
    body = re.search(r"<main.*?</main>", page, re.S).group(0)
    body = re.sub(r"<(script|style|svg|noscript)\b.*?</\1>", " ", body, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()


def test_the_pages_open_without_a_login_and_carry_the_shared_shell(site):
    for path in PAGES:
        page = site.get(path)
        assert page.status_code == 200, path
        assert page.text.count("<h1") == 1, path
        assert 'class="site-header"' in page.text and 'class="site-footer"' in page.text
        assert page.text.count("Simulated demonstration") == 1, path       # the one chip in the footer, never repeated on the page


def test_the_front_door_goes_to_the_home_page(site):
    r = site.get("/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/overview"
    assert site.get("/").status_code == 200       # a visitor who follows the redirect arrives on the home page


def test_the_home_page_has_exactly_the_agreed_headline(site):
    page = site.get("/overview").text
    heading = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S).group(1)
    assert re.sub(r"\s+", " ", heading).strip() == HEADLINE


def test_the_home_page_offers_the_ways_to_try_talk_and_the_front_desks_are_one_click_away(site):
    page = site.get("/overview").text
    assert 'href="tel:+2348055550100"' in page and "+234 805 555 0100" in page            # the first way: to call
    body = page.split("<main")[1]      # the menu in the header carries the same links, so the page itself is looked at on its own
    assert 'href="/try"' in body                                                          # the second way: to type to Talk in the browser
    assert 'href="/onboard"' in body and "Onboard a hospital" in body
    nav = re.search(r'<nav class="nav".*?</nav>', page, re.S).group(0)
    assert 'href="/overview/providers"' in nav                                            # the third way: to look at the front desk of each provider
    assert "Emergency: 112 first" in body


def test_the_home_page_is_the_only_page_with_that_headline_and_does_not_promise_what_talk_never_does(site):
    for path in ("/overview/technology", "/overview/providers"):
        assert HEADLINE not in site.get(path).text, path
    text = main_of(site.get("/overview").text).lower()
    assert "dispatch" not in text and "diagnos" not in text


def test_the_pages_are_short_cues_and_not_explanations(site):
    limits = {"/overview": 70, "/overview/providers": 60, "/overview/technology": 330}      # the reference page also holds its tables
    for path, limit in limits.items():
        page = site.get(path).text
        for old in ('class="eyebrow"', 'class="lede"', 'class="hero', 'class="flash"', 'class="section-rule"'):
            assert old not in page, (path, old)
        words = len(main_of(page).split())
        assert words <= limit, (path, words)


def test_the_current_page_is_marked_in_the_menu(site):
    for path, label in (("/overview", "Home"), ("/try", "Try it"), ("/demo", "Live calls"), ("/overview/providers", "Providers")):
        nav = re.search(r'<nav class="nav".*?</nav>', site.get(path).text, re.S).group(0)
        assert re.search(rf'<a href="[^"]+" aria-current="page">{label}</a>', nav), path


def test_the_contact_email_and_cost_note_show_only_when_they_are_set(tmp_path):
    with make(tmp_path) as bare:
        page = bare.get("/overview").text
        assert "mailto:" not in page and "tel:" not in page
        assert 'href="/try"' in page      # without a number to call, Try it is the way in
    with make(tmp_path, contact_email="hello@example.com", cost_note="A live test costs us a little.") as full:
        page = full.get("/overview").text
        assert 'href="mailto:hello@example.com"' in page and "A live test costs us a little." in page


def test_the_providers_page_lists_all_four_with_a_working_front_desk_each(site):
    page = site.get("/overview/providers").text
    for name in ("Lagos State Primary Health Network", "Eko Care Private Clinics", "Everwell Pharmacies", "Oncology Care Centre Ikeja"):
        assert name in page
    for slug in SLUGS:
        assert f'href="/synthetic/{slug}/"' in page and site.get(f"/synthetic/{slug}/").status_code == 200


def test_how_it_works_names_the_models_and_the_steps_of_a_call(site):
    page = site.get("/overview/technology").text
    for name in ("Muse Voice Transcribe", "Muse Spark", "Providers", "Privacy and limits"):
        assert name in page
    assert page.count("<tr>") >= 20           # the steps, the models, the provider requests and the rules are tables
    assert "Deleted after 30 days" in page


def test_a_page_that_is_switched_off_is_gone_and_its_menu_item_with_it(tmp_path):
    with make(tmp_path, try_page_enabled=False, demo_onboarding_enabled=False) as c:
        page = c.get("/overview").text
        assert 'href="/try"' not in page and 'href="/demo"' not in page and 'href="/onboard"' not in page
        assert c.get("/try").status_code == 404 and c.get("/demo").status_code == 404
    with make(tmp_path, overview_enabled=False) as c:
        assert c.get("/overview").status_code == 404 and c.get("/overview/providers").status_code == 404 and c.get("/overview/technology").status_code == 404


def test_the_pages_hold_no_secrets(tmp_path):
    secrets = {"at_callback_secret": "a-secret-callback-token", "llm_api_key": "a-secret-language-model-key", "asr_api_key": "a-secret-speech-key",
               "hospital_signing_secret": "a-secret-signing-phrase", "hospital_desk_key": "a-secret-desk-key"}
    with make(tmp_path, demo_page_enabled=True, **secrets) as c:
        pages = PAGES + ["/try", "/demo"] + [f"/synthetic/{slug}/" for slug in SLUGS]
        for path in pages:
            text = c.get(path).text
            for name, value in secrets.items():
                assert value not in text, (path, name)
        derived = c.app.state.svc.settings.provider_secret("state-phc")
        assert all(derived not in c.get(path).text for path in pages)       # the secret that each provider shares with Talk is never written out either
