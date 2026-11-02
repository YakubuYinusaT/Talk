"""Every setting Talk reads, with the value it has when nobody sets it. A value in the environment or in .env wins (DATABASE_URL, LLM_API_KEY, ...).

With no keys set, every outside service has a stand-in that runs inside this process (the url settings default to inprocess://mock, the voice to a silent
stand-in), so a fresh checkout and the tests run with nothing else installed.
"""

import hashlib
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/sofa.db"
    redis_url: str = ""
    public_base_url: str = "http://localhost:8000"
    storage_dir: str = "./data"

    # The telephony and SMS provider: the callback address carries AT_CALLBACK_SECRET, and texts go out with AT_API_KEY (no key = texts are only logged).
    at_username: str = "sandbox"
    at_api_key: str = ""
    at_sandbox: bool = True
    at_callback_secret: str = "dev-secret"
    sms_sender_id: str = ""

    # Speech to text. "meta": Meta's Muse Voice Transcribe (ASR_URL=https://api.meta.ai; the key is LLM_API_KEY unless ASR_API_KEY is set).
    # inprocess://mock is the stand-in that reads the simulator's text "recordings".
    asr_url: str = "inprocess://mock"
    asr_api_key: str = ""
    asr_model: str = "muse-voice-transcribe-1.0"
    asr_keywords: str = ""          # extra words for the recogniser to listen for, comma separated (place, clinic and medicine names are added by themselves)

    # The language model. "meta": the Meta Model API (LLM_URL=https://api.meta.ai, LLM_MODEL=muse-spark-1.3, LLM_API_KEY=<its key>). "openai": any OpenAI-style
    # chat API (LLM_URL, LLM_MODEL and LLM_API_KEY of that service).
    llm_url: str = "inprocess://mock"
    llm_provider: str = "meta"
    llm_model: str = "muse-spark-1.3"
    llm_reasoning_effort: str = "minimal"  # Meta models only: minimal, low, medium or high. Lower is faster
    llm_api_key: str = ""

    # The voice callers hear. "spitch": the hosted voice (needs SPITCH_API_KEY). With a Piper voice file (PIPER_MODEL) a voice on this machine speaks when the
    # hosted one cannot, or all the time when there is no key. With neither, a silent stand-in is used.
    tts_provider: str = "spitch"
    tts_hosted_speed: float = 0.95
    spitch_api_key: str = ""
    spitch_voice_en: str = "jude"
    piper_model: str = ""  # path to a Piper voice (.onnx); empty = none
    piper_speed: float = 1.0

    # The one number callers dial to reach Talk. Empty = the front desk answers every number it is called on.
    talk_number: str = ""
    # Let the model word Talk's replies (placeholders keep every fact the provider's, and the wording is checked before it is spoken). Off = fixed wording only.
    reply_wording: bool = True
    # Talk never hangs up because it failed to help: the caller decides. The one exception is a line left silent, which still costs inbound minutes:
    # after this many silent turns in a row (a gentle prompt each time) Talk lets go.
    max_silences: int = 2
    max_call_seconds: int = 480    # no call runs longer than this: Talk says goodbye at the next turn after it

    # Which services a caller can reach (SERVICES_ENABLED=health). A service that is switched off is politely declined, and its tools are not even registered.
    services_enabled: str = "health"
    # The synthetic health network: made-up provider systems (a state health network, a private clinic group, a pharmacy chain) run beside Talk, each reached
    # through its own signed connection the way real providers would be (docs/design.md).
    synthetic_hospital: bool = False           # run them at /synthetic/<name> and register each as a provider behind the "health" service
    hospital_base_url: str = ""                # where Talk reaches them; empty = <PUBLIC_BASE_URL>/synthetic. Each is <base>/<name>/rpc and must be a public https address
    hospital_signing_secret: str = ""          # from this, each provider's own secret is derived; empty = derived from AT_CALLBACK_SECRET, so a demo needs no extra setting
    hospital_db_dir: str = ""                  # where each provider keeps its own database file; empty = the storage folder
    hospital_staff_phone: str = ""             # a number that is texted when an urgent request reaches a provider's front desk (an emergency); empty = no text
    hospital_desk_key: str = ""                # lets a provider's front-desk page mark visits attended or missed (open the page with ?key=...); empty = read only

    # The public pages. /demo: counts and what happened in recent calls. /overview: the story, the technology and the use cases. /try: type to Talk in the browser.
    demo_page_enabled: bool = False
    demo_show_calls: bool = False    # also show what callers said and what Talk replied (only for a demo where every caller knows it is shown)
    overview_enabled: bool = True
    contact_email: str = ""      # The email address that the home page shows to people who would like to ask us a question.
    test_number: str = ""        # The number that a visitor may call to try Talk on the telephone.
    cost_note: str = ""          # A short note, shown on the home page, about what a test call costs.
    try_page_enabled: bool = True
    try_max_turns: int = 20          # a visitor's typed conversation ends after this many turns
    try_turns_per_hour: int = 60     # turns one visitor address may send in an hour
    try_session_minutes: int = 30    # a typed conversation is forgotten after this long

    # The hospital onboarding wizard (/onboard): a visitor makes a simulated hospital of their own, connects it to Talk and receives its first appointment. Each hospital is
    # seen only by the visitor who made it, is removed after DEMO_ONBOARDING_HOURS, and holds made-up data only. Off: the pages answer 404.
    demo_onboarding_enabled: bool = True
    demo_onboarding_hours: int = 24                 # a hospital made in the wizard is removed this long after it was made
    demo_onboarding_max_active: int = 40            # hospitals alive at once, across all visitors; one more is turned away politely
    demo_onboarding_per_address_per_hour: int = 6   # hospitals one visitor address may start in an hour

    test_caller_numbers: str = "+2348000000001"
    scheduler_enabled: bool = True  # background jobs: recording clean-up and the follow-ups after a visit
    scheduler_interval_seconds: int = 60
    recording_allowed_hosts: str = "africastalking.com,at-internal.com"  # a recording is downloaded only from these hosts (and their sub-domains), over https; empty = any (not safe)
    recording_retention_days: int = 30   # a caller's recording is deleted this long after the call; 0 keeps recordings
    debug_headers: bool = True  # X-Sofa-* headers used by the call simulator

    # Dialogue tuning
    asr_min_confidence: float = -1.3  # avg log-prob; below this the transcript is treated as unheard
    filler_after_seconds: float = 2.0
    tts_budget_seconds: float = 4.0  # a model-worded sentence that is not spoken within this long is replaced by its stored wording
    filler_every_seconds: float = 6.0  # a slow reply: another holding message every this many seconds, so the caller never sits in silence
    record_timeout_seconds: int = 2
    record_max_seconds: int = 15
    silence_rms: float = 150.0  # a recording quieter than this (0 to 32767) is treated as silence: on a quiet line the recogniser invents sentences
    max_calls_per_hour: int = 20

    # Streamed calls (SIP trunk -> Asterisk -> AudioSocket): the agent listens on this local port; Asterisk is the only thing that connects to it
    sip_enabled: bool = False
    sip_host: str = "127.0.0.1"
    sip_port: int = 4574
    sip_max_calls: int = 8                  # calls at once; one more is turned away
    sip_voice_rms: float = 300.0            # a 20 ms slice of the line louder than this (0 to 32767) is speech; the line's own noise level raises it
    sip_end_silence_ms: int = 800           # speech has ended after this much quiet
    sip_min_speech_ms: int = 240            # less speech than this is a click or a cough, not a turn
    sip_max_speech_seconds: int = 15        # a turn this long is cut and read
    sip_silence_seconds: float = 8.0        # nobody speaks for this long after Talk has finished: the silence reply
    sip_filler_after_seconds: float = 3.5   # a reply slower than this gets a short holding message
    sip_barge_in: bool = True               # the caller talking over Talk stops Talk
    sip_barge_ms: int = 400                 # ... after this much continuous speech, so a cough or an echo does not cut Talk off

    @property
    def test_numbers(self) -> set[str]:
        return {n.strip() for n in self.test_caller_numbers.split(",") if n.strip()}

    @property
    def sms_is_mock(self) -> bool:
        return not self.at_api_key

    def provider_secret(self, slug: str) -> str:
        """The secret one synthetic provider shares with Talk: derived, so each provider has its own and a demo needs no extra setting."""
        return hashlib.sha256(f"provider|{slug}|{self.hospital_signing_secret or self.at_callback_secret}".encode()).hexdigest()

    def provider_endpoint(self, slug: str) -> str:
        base = self.hospital_base_url or f"{self.public_base_url.rstrip('/').replace('http://', 'https://', 1)}/synthetic"
        return f"{base.rstrip('/')}/{slug}/rpc"

    @property
    def recording_hosts(self) -> tuple[str, ...]:
        return tuple(h.strip().lower().lstrip(".") for h in self.recording_allowed_hosts.split(",") if h.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
