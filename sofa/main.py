import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, get_settings
from .container import build_services
from .db import init_db, make_engine, make_session_factory
from .hardening import replace_known_defaults
from .routes import demo, onboard, overview, payments, tryit, twilio, voice, whatsapp


def voice_in_use(settings: Settings) -> str:
    """The voice callers hear, in words, for /health."""
    if settings.tts_provider == "spitch" and settings.spitch_api_key:
        return "spitch, " + ("with a voice on this machine as back-up" if settings.piper_model else "no back-up voice")
    if settings.tts_provider == "azure" and settings.azure_speech_key and settings.azure_speech_region:
        return f"azure {settings.azure_voice}, " + ("with a voice on this machine as back-up" if settings.piper_model else "no back-up voice")
    if settings.tts_provider != "standin" and settings.piper_model:
        return "a voice on this machine"
    return "stand-in (silent)"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO)
    replace_known_defaults(settings)  # on an https address no secret may still be the one published with the code
    engine = make_engine(settings.database_url)
    init_db(engine)
    svc = build_services(settings, make_session_factory(engine))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.synthetic_hospital:  # the provider systems behind the health front desk, named by the settings
            from .health.links import specs_from_settings

            health = svc.orchestrator.adapter("health")
            if health:
                health.set_providers(specs_from_settings(settings))

        from .services import scheduler

        task = asyncio.create_task(scheduler.loop(svc)) if settings.scheduler_enabled else None
        sip = None
        if settings.sip_enabled:  # streamed calls from the SIP trunk, through Asterisk on this machine (sofa/sip)
            from .sip.agent import SipServer

            sip = SipServer(svc)
            await sip.start()
        yield
        if sip:
            sip.stop()
        if task:
            task.cancel()
        for route in app.router.routes:      # the provider systems mounted beside Talk each keep their records open, so they are closed with it
            store = getattr(getattr(getattr(route, "app", None), "state", None), "store", None)
            if store is not None:
                store.close()
        engine.dispose()

    # The generated API reference is not published: it would list every route, the signed provider endpoints included.
    app = FastAPI(title="Talk", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.svc = svc
    app.state.engine = engine
    app.include_router(voice.router)
    app.include_router(twilio.router)
    app.include_router(overview.router)
    app.include_router(demo.router)
    app.include_router(tryit.router)
    app.include_router(payments.router)
    app.include_router(whatsapp.router)
    app.include_router(onboard.router)
    if settings.synthetic_hospital:  # made-up provider systems beside Talk, each reached only through its own signed connection (see sofa/health)
        from .health import register as health_register

        from .services.notify import texts_about

        from .services.payments import of_codes

        apps = health_register.create_apps(settings, texts=lambda codes: texts_about(svc.session_factory, codes), payments=lambda codes: of_codes(svc.session_factory, codes))
        for slug, provider_app in apps.items():
            app.mount(f"/synthetic/{slug}", provider_app)

    health_adapter = svc.orchestrator.adapter("health")
    if settings.demo_onboarding_enabled and health_adapter:   # hospitals that visitors make in the onboarding wizard, each shown only to the visitor who made it (sofa/onboarding)
        from .onboarding.service import Onboarding

        svc.onboarding = Onboarding(app, svc)
        health_adapter.demo = svc.onboarding
        svc.onboarding.restore()   # the hospitals that have not expired come back after a restart, with their appointment books

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return RedirectResponse("/static/ci-mark-red.png", status_code=307)

    app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "web" / "static")), name="static")

    @app.get("/health")
    def health():
        return {"ok": True, "sms": "mock" if settings.sms_is_mock else "live",
                "asr": settings.asr_url, "llm": settings.llm_url, "tts": voice_in_use(settings), "streamed_calls": settings.sip_enabled,
                "model_answers": getattr(getattr(app.state, "svc", None), "llm", None) and app.state.svc.llm.stats}

    @app.get("/audio/{name}")
    def audio(name: str):
        path = Path(settings.storage_dir) / "audio_out" / Path(name).name
        if not path.exists():
            raise HTTPException(status_code=404)
        return FileResponse(path, media_type="audio/wav")

    return app
