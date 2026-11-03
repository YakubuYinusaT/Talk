from dataclasses import dataclass, field

from .audio import AudioService
from .clients.asr import MetaASRClient
from .clients.llm import LLMClient
from .clients.sms import SMSClient
from .clients.whatsapp import WhatsAppClient
from .clients.tts import build_tts
from .config import Settings
from .orchestrator.wiring import Orchestrator, build_orchestrator
from .health.links import ProviderLinks
from .session import make_store


@dataclass
class Services:
    settings: Settings
    session_factory: object
    sessions: object
    asr: MetaASRClient    # Muse Voice Transcribe, or the stand-in that reads the simulator's text recordings
    llm: LLMClient
    tts: object
    sms: SMSClient
    audio: AudioService
    turn_tasks: dict = field(default_factory=dict)  # turn_id -> asyncio.Task (single-process; use Redis for multi-worker)
    orchestrator: Orchestrator = field(default_factory=build_orchestrator)  # registered service adapters and the tool registry
    provider_links: object = None  # reaches the provider systems behind the health front desk (sofa/health/links.py)
    onboarding: object = None      # the hospitals visitors made in the onboarding wizard (sofa/onboarding), when that is switched on
    whatsapp: object = None        # people who chat with Sofa on WhatsApp (sofa/routes/whatsapp.py), when it is set up


def build_asr(settings: Settings) -> MetaASRClient:
    """Meta's Muse Voice Transcribe. With the health network on, the recogniser is also given its place, clinic and medicine names."""
    words = [w.strip() for w in settings.asr_keywords.split(",") if w.strip()]
    if settings.synthetic_hospital or "health" in {x.strip() for x in settings.services_enabled.split(",")}:
        from .health import data

        plain = {"clinic", "hospital", "centre", "health", "general", "medical", "community", "pharmacy", "everwell"}
        shortened = [" ".join(w for w in f.name.split() if w.lower() not in plain) for f in data.FACILITIES]     # "Aguda", "Yaba Lakeview": what a caller would say
        words += [a.name for a in data.AREAS.values()] + [d.aliases[0] if d.aliases else d.name for d in data.DRUGS] + [f.name for f in data.FACILITIES if f.kind != "pharmacy"] + shortened
    return MetaASRClient(settings.asr_url, settings.asr_api_key or settings.llm_api_key, settings.asr_model, tuple(dict.fromkeys(words)))


def build_services(settings: Settings, session_factory) -> Services:
    tts = build_tts(settings)
    return Services(
        settings=settings,
        session_factory=session_factory,
        sessions=make_store(settings.redis_url),
        asr=build_asr(settings),
        llm=LLMClient(settings.llm_url, settings.llm_model, settings.llm_api_key, settings.llm_provider, settings.llm_reasoning_effort),
        tts=tts,
        sms=SMSClient(settings),
        audio=AudioService(settings, tts),
        orchestrator=build_orchestrator(settings),
        provider_links=ProviderLinks(settings),
        whatsapp=WhatsAppClient(settings.whatsapp_phone_number_id, settings.whatsapp_access_token) if settings.whatsapp_phone_number_id else None,
    )
