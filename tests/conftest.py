import httpx
import pytest
from fastapi.testclient import TestClient

from sofa import main as main_module
from sofa.audio import AudioService
from sofa.config import Settings
from sofa.orchestrator.adapters.health import HealthAdapter
from sofa.health.store import HospitalStore
from sofa.main import create_app
from tests.support import FIXED, TALK_NUMBER, SECRET, Providers


@pytest.fixture(autouse=True)
def the_voice_tag_does_not_leak_between_tests():
    """The voice's name is kept on the audio service class so that a recording made by another voice is not reused. Every app a test builds sets it, so it is cleared around each test to keep one test's voice from changing another test's cache keys."""
    AudioService.voice_tag = ""
    yield
    AudioService.voice_tag = ""


@pytest.fixture(autouse=True)
def every_database_is_closed_when_its_test_ends(monkeypatch):
    """Many tests build an app without running its start-up and shut-down, so nothing would close Talk's own database or the appointment books of the simulated providers. They are closed here instead, so that no test leaves a database open."""
    books: list[HospitalStore] = []
    engines: list = []
    original_init, original_engine = HospitalStore.__init__, main_module.make_engine

    def remember_book(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        books.append(self)

    def remember_engine(*args, **kwargs):
        engine = original_engine(*args, **kwargs)
        engines.append(engine)
        return engine

    monkeypatch.setattr(HospitalStore, "__init__", remember_book)
    monkeypatch.setattr(main_module, "make_engine", remember_engine)
    yield
    for book in books:
        book.close()
    for engine in engines:
        engine.dispose()


@pytest.fixture
def happ(tmp_path, monkeypatch):
    """Talk with the four simulated providers running beside it, reached through the stand-in internet and with the clock fixed on a Tuesday morning."""
    app = create_app(Settings(synthetic_hospital=True, hospital_base_url="https://health.example/synthetic", services_enabled="health", database_url="sqlite://",
                              storage_dir=str(tmp_path), at_callback_secret=SECRET, public_base_url="http://test", debug_headers=True, scheduler_enabled=False,
                              talk_number=TALK_NUMBER, _env_file=None))
    apps = {r.path.rsplit("/", 1)[-1]: r.app for r in app.router.routes if getattr(r, "path", "").startswith("/synthetic/")}
    for provider in apps.values():
        provider.state.store.clock = lambda: FIXED
    app.state.providers = apps
    app.state.net = Providers(apps)
    app.state.svc.provider_links.use_http(httpx.AsyncClient(transport=app.state.net, base_url="https://health.example"))
    monkeypatch.setattr(HealthAdapter, "now", lambda self: FIXED)
    return app


@pytest.fixture
def client(happ):
    with TestClient(happ) as c:
        yield c


@pytest.fixture
def hdb(happ):
    with happ.state.svc.session_factory() as session:
        yield session


@pytest.fixture
def said(happ):
    """The model's reading of the caller's words, set per test: {sentence: the fields it filled in}. 'choice:<sentence>' sets which option it picks. The rest is the stand-in model."""
    readings: dict = {}
    llm = happ.state.svc.llm
    real = llm.extract

    async def extract(model, system, transcript, alternatives=None, json_schema=None):
        if system.startswith("ARGUMENTS"):
            return model(**readings.get(transcript, {})), {}
        if system.startswith("CHOICE"):
            return model(choice=readings.get("choice:" + transcript)), {}
        return await real(model, system, transcript, alternatives, json_schema)

    llm.extract = extract
    return readings
