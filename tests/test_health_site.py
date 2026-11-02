"""The website as a whole: every public page loads in the same shell, the menu lists the pages that exist, and each provider's front desk shows the appointment book, the queue and the requests."""

import re

import pytest
from fastapi.testclient import TestClient

from sofa.config import Settings
from sofa.main import create_app

PAGES = ["/overview", "/overview/technology", "/overview/providers", "/try", "/demo", "/onboard"]
SLUGS = ("state-phc", "eko-care", "everwell", "onc-centre")
DESK_KEY = "a-desk-key-that-must-stay-private"


@pytest.fixture
def site(tmp_path):
    app = create_app(Settings(synthetic_hospital=True, services_enabled="health", demo_page_enabled=True, database_url="sqlite://", storage_dir=str(tmp_path),
                              at_callback_secret="x", public_base_url="http://test", scheduler_enabled=False, talk_number="+2348000009999", test_number="+234 805 555 0100",
                              llm_provider="meta", llm_model="muse-spark-1.3", _env_file=None))
    with TestClient(app) as client:
        yield client


def test_every_page_loads_with_one_title_in_the_shared_shell(site):
    for path in PAGES:
        r = site.get(path)
        assert r.status_code == 200, path
        assert r.text.count("<h1") == 1, path
        assert 'class="site-header"' in r.text and 'class="site-footer"' in r.text and "Simulated demonstration" in r.text, path


def test_the_menu_lists_the_pages_that_exist_and_marks_the_current_one(site):
    page = site.get("/overview/providers").text
    nav = re.search(r'<nav class="nav".*?</nav>', page, re.S).group(0)
    for label in ("Home", "Try it", "Live calls", "Providers", "Onboard a hospital"):
        assert f">{label}</a>" in nav, label
    assert 'aria-current="page">Providers</a>' in nav


def test_the_footer_says_who_made_it_and_that_the_data_is_simulated(site):
    footer = site.get("/overview").text.split('<footer class="site-footer">')[1]
    assert "Talk by Connected Intelligence" in footer and "Simulated demonstration" in footer


def test_an_address_that_the_site_does_not_have_is_not_found(site):
    for path in ("/overview/nothing-here", "/nothing-here", "/synthetic/no-such-provider/"):
        assert site.get(path).status_code == 404, path


def test_each_front_desk_is_reached_from_the_providers_page(site):
    page = site.get("/overview/providers").text
    for slug in SLUGS:
        assert f'href="/synthetic/{slug}/"' in page and site.get(f"/synthetic/{slug}/").status_code == 200


def test_a_front_desk_is_its_own_app_with_a_menu_of_sections_and_a_way_back_to_talk(site):
    for slug in SLUGS:
        page = site.get(f"/synthetic/{slug}/").text
        assert page.count("<h1") == 1 and 'class="app-side"' in page and 'class="site-header"' not in page, slug      # the hospital's own system, not a page of the site
        menu = re.search(r'<nav class="app-nav" id="desk-nav".*?</nav>', page, re.S).group(0)
        assert 'href="#overview"' in menu and 'href="#requests"' in menu and 'href="#activity"' in menu and 'href="#places"' in menu, slug
        assert '<a class="app-brand" href="/"' in page and "Simulated demonstration" in page, slug


def test_every_front_desk_shows_the_queue_place_by_place_and_the_requests_for_the_care_team(site):
    for slug in SLUGS:
        page = site.get(f"/synthetic/{slug}/").text
        for section in ("requests", "places"):
            assert f'id="{section}"' in page, (slug, section)
        assert "Requests" in page and "Places" in page and "People waiting" in page and "Open requests" in page, slug
        for column in ("Place", "Status", "Waiting", "Wait", "Fee", "Hours"):
            assert f">{column}</th>" in page, (slug, column)
        assert "No requests waiting" in page, slug      # nobody has asked for anything yet, and the desk says so plainly


def test_the_providers_that_take_bookings_show_an_appointment_book_and_the_others_show_what_they_hold(site):
    for slug in ("state-phc", "eko-care", "onc-centre"):
        page = site.get(f"/synthetic/{slug}/").text
        assert 'id="appointments"' in page and "Appointments" in page, slug
    pharmacy = site.get("/synthetic/everwell/").text
    assert 'id="stock"' in pharmacy and "Medicine stock" in pharmacy and 'id="appointments"' not in pharmacy
    centre = site.get("/synthetic/onc-centre/").text
    assert 'id="guide"' in centre and "Patient guide" in centre


def test_a_front_desk_without_the_key_is_read_only_and_offers_no_staff_buttons(site):
    for slug in SLUGS:
        page = site.get(f"/synthetic/{slug}/").text
        assert "Read only" in page and "Staff access" not in page and "Send reply" not in page, slug


def test_a_front_desk_refuses_staff_actions_that_come_without_the_key(site):
    for action in ("reply", "mark", "confirm"):
        refused = site.post(f"/synthetic/state-phc/desk/{action}", data={"code": "REQ-AAAA", "reply": "Thank you.", "outcome": "attended"}, follow_redirects=False)
        assert refused.status_code == 403, action


def test_a_front_desk_is_never_kept_by_a_browser_so_that_the_queue_is_never_old(site):
    assert "no-store" in site.get("/synthetic/eko-care/").headers["cache-control"]


def test_the_desk_key_is_never_written_into_any_page(tmp_path):
    app = create_app(Settings(synthetic_hospital=True, services_enabled="health", demo_page_enabled=True, database_url="sqlite://", storage_dir=str(tmp_path),
                              at_callback_secret="x", public_base_url="http://test", scheduler_enabled=False, hospital_desk_key=DESK_KEY, _env_file=None))
    with TestClient(app) as client:
        for path in PAGES + [f"/synthetic/{slug}/" for slug in SLUGS]:
            assert DESK_KEY not in client.get(path).text, path
        wrong = client.get("/synthetic/state-phc/", params={"key": "not-the-key"}).text
        assert "That key was not accepted." in wrong and DESK_KEY not in wrong
        right = client.get("/synthetic/state-phc/", params={"key": DESK_KEY}).text
        assert "Staff access" in right
