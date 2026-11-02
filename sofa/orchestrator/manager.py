"""The front desk: Talk answers the phone, hears what the caller needs, and names the service.

One model call per turn works out what the caller meant (understanding.py); the service's adapter then takes the turn. The voice route runs it through the same
turn loop for a callback call, a streamed call and a typed conversation: logging and the trace are shared.

Every turn also keeps a trace: the steps taken inside it, in order (heard, understood, read, asked, booked, request, replied), each with the milliseconds since the
turn began. It holds what happened and never a phone number, a caller id or a secret.
"""

import asyncio
import logging
import time

from sqlalchemy.orm import Session

from ..dialogue import templates
from ..dialogue.outcome import Outcome
from ..dialogue.validator import fill
from ..services.handoff import open_handoff
from ..health import floor
from . import registry, understanding, wording
from .answers import closing, quick_answer

log = logging.getLogger("sofa.orchestrator")


class CallManager:
    def __init__(self, db: Session, svc, st: dict, call, person, turn_id=None, started: float | None = None):
        self.db, self.svc, self.st, self.call, self.person, self.turn_id = db, svc, st, call, person, turn_id
        self.raw_json: dict | None = None
        self.trace: list[dict] = []
        self.started = started if started is not None else time.perf_counter()  # when the turn began (time.perf_counter)
        self._health_read: asyncio.Task | None = None  # the health desk's reading of this turn's words, started while the understanding call runs
        self._u: understanding.Understanding | None = None  # this turn's understanding (one model call, reused)
        self._u_key = None

    # ---- the trace ---------------------------------------------------------------------------------

    def note(self, step: str, **data) -> None:
        """Add a step to this turn's trace, with the time since the turn began."""
        self.trace.append({"step": step, "at_ms": int((time.perf_counter() - self.started) * 1000), **data})

    # ---- reply construction ----------------------------------------------------------------------

    def reply(self, key: str, *, end: bool = False, action: str | None = None, **facts) -> Outcome:
        raw = templates.pick(key, self.st["turn"])
        facts = {"name": self.person.name or "", **facts}
        if "{ack}" in raw:
            options = templates.acks()
            facts["ack"] = options[self.st["ack_i"] % len(options)]
            self.st["ack_i"] += 1
        # `extra` keeps what the wording step needs: the real facts and the reference sentence
        return Outcome(fill(raw, facts), key, end, f"{action or key}|template", extra={"facts": facts, "reference": raw})

    def ask(self, key: str, pending: dict, *, action: str | None = None, **facts) -> Outcome:
        """A reply that waits for an answer: remember what was asked so the next turn is read as the answer."""
        out = self.reply(key, action=action, **facts)
        self.st["pending"] = {**pending, "question": out.text}
        return out

    # ---- entry points ------------------------------------------------------------------------

    async def not_heard(self, transcript: str) -> Outcome:
        self.st["low_conf"] += 1
        if self.st["low_conf"] >= 2:
            return await self.give_up("asr_low_confidence", transcript)
        return self.reply("repeat_prompt", action="asr_low_confidence")

    # ---- understanding: one model call per turn --------------------------------------------------

    async def emergency(self, health, transcript: str, signal) -> Outcome:
        """Someone may be in danger: the health desk answers at once, whatever else the caller was doing."""
        self.st["pending"], self.st["domain"] = None, "health"
        self.call.service_domain = "health"
        self.note("urgency", level=signal.level, source=signal.source, hits=list(signal.hits))
        return await health.emergency(self, transcript)

    async def understand(self, transcript: str) -> understanding.Understanding:
        """Service, tool, details and yes/no, all in one call. Cached for the turn. The model may only name a registered tool; anything else is dropped here,
        before anything can act on it."""
        if self._u is not None and self._u_key == transcript:
            return self._u
        orchestrator = self.svc.orchestrator
        voice = orchestrator.voice_tools()  # tool id -> its service
        started = time.perf_counter()
        u, _ = await self.svc.llm.extract(understanding.Understanding, understanding.prompt(self), transcript,
                                          json_schema=understanding.schema(list(voice), orchestrator.extra_domains()))
        u.settle(voice, orchestrator.extra_domains())  # the model may only name a registered tool or service; anything else is dropped here, before anything acts on it
        if u.domain not in orchestrator.domain_choices():
            u.domain = registry.UNCLEAR
        if self.st.get("pending") and u.answer is None and (plain := quick_answer(transcript)):
            u.answer = plain  # Talk asked and the whole reply is a plain yes or no: do not leave that to the model
        if u.answer not in ("yes", "no", "other"):
            u.answer = None
        self._u, self._u_key = u, transcript
        self.note("understood", model=getattr(self.svc.llm, "model", ""), action=u.action, domain=u.domain, tool=u.tool, answer=u.answer, language="en",
                  ms=int((time.perf_counter() - started) * 1000))
        return u

    async def route(self, transcript: str) -> str:
        return (await self.understand(transcript)).domain

    async def answer_to(self, transcript: str) -> str:
        """yes / no / other, for the question Sofa just asked (the same single understanding call)."""
        return (await self.understand(transcript)).answer or "other"

    # ---- wording: the model writes the sentence, the backend keeps the facts -----------------------

    # a service's own words (a provider's facts, a patient guide's answer) are spoken exactly as written
    NEVER_REWORDED = ("health_",)

    async def reword(self, out: Outcome) -> Outcome:
        s = self.svc.settings
        facts, reference = out.extra.get("facts"), out.extra.get("reference")
        if (facts is None or not s.reply_wording or out.key.startswith(self.NEVER_REWORDED)
                or "|template" not in out.action or "|template_fallback" in out.action
                or wording.carries_facts(reference or "")):
            return out  # (or it was already worded once, or it carries a name or a figure written by a provider: those stay exact)
        try:
            written = await wording.write(self.svc.llm, out.key, reference, (self.st.get("said") or [""])[-1], facts)
        except Exception as exc:  # the model being slow or wrong must never cost the caller a reply
            log.warning("wording failed for %s: %s", out.key, exc)
            return out
        if not written:
            out.action = out.action.replace("|template", "|template_fallback")
            return out
        _say, filled = written
        out.extra["template"] = out.text  # spoken instead if the voice is too slow for the new sentence
        out.text = filled
        out.action = out.action.replace("|template", "|generated")
        return out

    # ---- a turn ------------------------------------------------------------------------------------

    async def handle(self, transcript: str, confidence: float) -> Outcome:
        out = self.note_asked_more(await self.reword(await self._handle(transcript, confidence)))
        self.st["talk_said"] = (out.text or "")[:400]   # the model reads the caller's next words against what Sofa has just said
        if transcript.strip():   # the whole call, both sides, for the model that leads it (adapters/health_agent.py)
            self.st["log"] = ((self.st.get("log") or []) + [["caller", transcript.strip()[:300]], ["sofa", (out.text or "")[:700]]])[-24:]
        return out

    def note_asked_more(self, out: Outcome) -> Outcome:
        """Remember whether this reply ended with "is there anything else?": the next "no" then means goodbye."""
        spoken = (out.extra.get("reference") or out.text or "").lower()
        self.st["asked_more"] = "anything else i can help" in spoken and not out.end_call
        return out

    async def _handle(self, transcript: str, confidence: float) -> Outcome:
        st = self.st
        st["turn"] += 1
        st["silence"] = 0
        if not transcript.strip():
            return await self.not_heard(transcript)
        if closing(transcript, bool(st.get("asked_more")) and not st.get("pending")):  # "no, that's all": say goodbye, do not hold the line
            self.call.outcome = self.call.outcome or "completed"
            return self.reply("call_goodbye", end=True, action="goodbye")
        st["said"] = (st.get("said", []) + [transcript.strip()[:200]])[-3:]  # what the provider is told if this goes unresolved
        health = self.svc.orchestrator.adapter("health")
        in_emergency = str((st.get("pending") or {}).get("step", "")).startswith("emergency")   # the emergency help is already going: its questions are answered below
        signal = floor.read(transcript)
        if health and not in_emergency and "ambulance" in transcript.lower():   # Talk cannot send one, and says so plainly, with what it can do
            return health.ambulance(self, transcript)
        if health and not in_emergency and signal.level == floor.EMERGENCY:  # the words alone say someone may be in danger: no model is waited for
            return await self.emergency(health, transcript, signal)
        if health and self.svc.settings.dialogue_agent and not in_emergency:
            out = await self.agent_turn(health, transcript, signal)
            if out is not None:
                return out
        if health and not st.get("pending"):  # a fresh request, not an answer to a question: read it now, alongside the understanding call below
            self._health_read = asyncio.ensure_future(health.read(self, transcript))
        u = await self.understand(transcript)
        self.raw_json = {"domain": u.domain, "tool": u.tool}
        heard = floor.combine(signal, u.urgency)    # the model read urgency by meaning: it can raise what the words alone gave, never lower it
        if health and not in_emergency and heard.level == floor.EMERGENCY:
            return await self.emergency(health, transcript, heard)
        if health and not in_emergency and heard.level == floor.POSSIBLE and not st.get("danger_asked"):
            st["danger_asked"] = True    # asked once in a call: a caller who said no is not asked again for the same worry
            self.note("urgency", level=heard.level, source=heard.source, hits=list(heard.hits))
            return health.danger_check(self, transcript)
        if st.get("pending"):  # Talk asked something: this turn is probably the answer
            out = await self.resolve_pending(st["pending"], transcript)
            if out:
                st["low_conf"] = st["unknown_streak"] = st["lost_streak"] = 0
                return out
        active = self.svc.orchestrator.adapter(st.get("domain"))
        domain = u.domain
        if domain == registry.UNCLEAR and active and active.holds_session(st):
            # Already inside a service: a bare "Aguda" cannot be routed, but the service knows its own places
            st["low_conf"] = st["unknown_streak"] = 0
            return await self.run_service_turn(active, transcript, confidence)
        # Speech scores low even when heard well on a bad line, so low confidence only rejects a turn nothing was found in.
        if confidence < self.svc.settings.asr_min_confidence and domain == registry.UNCLEAR:
            return await self.not_heard(transcript)
        st["low_conf"] = 0

        if domain == registry.HUMAN:  # Talk has no staff of its own: the provider follows up. With no service known yet, find out which.
            if st.get("domain"):
                return await self.give_up("asked_for_person", transcript)
            return self.reply("call_no_human", action="asked_for_person")
        if domain == registry.CHAT:  # "Hello Sofa", "thanks": answer like a person would, and ask what they need
            st["unknown_streak"] = 0
            return self.reply("call_chat", action="chat")
        if domain == registry.UNCLEAR:
            st["unknown_streak"] += 1
            if st["unknown_streak"] >= 3:
                return await self.give_up("three_unknown_turns", transcript)
            return self.reply("call_ask_again", action="unclear")
        st["unknown_streak"] = 0
        if st.get("domain") != domain:
            st["request"] = transcript.strip()[:200]  # what they first asked this service for: the provider needs it most
        adapter = self.svc.orchestrator.adapter(domain)
        if not adapter:  # switched off on this line
            st["domain"] = None
            offered = [registry.SERVICES[d].label for d in self.svc.orchestrator.domains()]
            return self.reply("service_off", action=f"service_off_{domain}", service=registry.SERVICES[domain].label, offered=templates.join_list(offered))
        st["domain"] = self.call.service_domain = domain
        return await self.run_service_turn(adapter, transcript, confidence)

    async def agent_turn(self, health, transcript: str, signal) -> Outcome | None:
        """The model reads the whole call and decides the step; the health front desk takes it. The urgency is checked first, and the model can only raise
        what the caller's words alone gave. None when the model gave no usable decision: the rules then answer the turn."""
        st = self.st
        decided = await health.agent.decide(self, transcript)
        if decided is None:
            return None
        heard = floor.combine(signal, decided.urgency)
        if heard.level == floor.EMERGENCY:
            return await self.emergency(health, transcript, heard)
        if heard.level == floor.POSSIBLE and not st.get("danger_asked"):
            st["danger_asked"] = True    # asked once in a call: a caller who said no is not asked again for the same worry
            self.note("urgency", level=heard.level, source=heard.source, hits=list(heard.hits))
            return health.danger_check(self, transcript)
        out = await health.agent.act(self, decided, transcript)
        if out is not None:
            st["low_conf"] = st["unknown_streak"] = st["lost_streak"] = 0
            if decided.action not in ("other", "goodbye", "person"):
                st["domain"] = self.call.service_domain = health.domain
        return out

    async def run_service_turn(self, adapter, transcript: str, confidence: float) -> Outcome:
        """Let a service take the turn, and count the turns in a row that the service itself could not make sense of. Inside a service the three-unknown-turns rule above
        cannot fire, because a bare "Aguda" is a perfectly good answer there, so the service marks the replies that ask again what the caller wants. After three of them
        the caller is passed to the clinic's staff, as they would be at the front door, instead of being asked the same question for ever."""
        st = self.st
        out = await adapter.turn(self, transcript, confidence)
        if not out.extra.get("not_understood"):
            st["lost_streak"] = 0
            return out
        st["lost_streak"] = st.get("lost_streak", 0) + 1
        if st["lost_streak"] >= 3:
            return await self.give_up("three_unknown_turns", transcript)
        return out

    async def resolve_pending(self, pending: dict, transcript: str) -> Outcome | None:
        """Read this turn as the answer to the question Talk asked. None means it was not an answer: route it normally."""
        st, kind = self.st, pending["kind"]
        if kind == "health":
            adapter = self.svc.orchestrator.adapter("health")
            if not adapter:  # the service was switched off while the caller was mid-way
                st["pending"] = None
                return None
            return await adapter.resolve_pending(self, pending, transcript)
        st["pending"] = None
        return None

    # ---- silence and failure -----------------------------------------------------------------

    async def on_silence(self) -> Outcome:
        self.st["silence"] += 1
        if self.st["silence"] >= self.svc.settings.max_silences:  # an abandoned line costs minutes: the only reason Sofa ends a call
            self.call.outcome = self.call.outcome or "silence"
            return self.reply("call_goodbye_silence", end=True, action="silence_goodbye")
        return self.reply("call_still_there", action="silence_prompt")

    async def give_up(self, reason: str, transcript: str = "") -> Outcome:
        """A request Talk could not finish. Talk is a medium, not the clinic's own front desk: when the service is known, the details go to that
        service's provider to follow up (we promise no time and own no outcome). When it is not known there is nobody to pass it to. Either way the call
        record keeps why, and the call carries on: Sofa never hangs up on a caller, it asks if there is anything else."""
        st = self.st
        domain = st.get("domain")
        provider = registry.SERVICES[domain].provider_label if domain in registry.SERVICES else None
        st["unknown_streak"] = st["low_conf"] = st["lost_streak"] = 0
        st["pending"] = None
        if not provider:
            self.call.outcome = "unresolved"
            return self.reply("call_give_up", action=f"give_up_{reason}")
        said = " | ".join(st.get("said", []) + ([transcript] if transcript and transcript not in st.get("said", []) else []))
        summary = (f"Unresolved on Talk ({reason}). Service: {domain}. Caller {self.call.from_number}. "
                   f"First asked: {st.get('request') or 'unknown'}. Last words: {said}")[:500]
        await open_handoff(self.db, self.call, reason, summary)
        st["domain"] = st["request"] = None  # this case is handed over; whatever they ask next starts fresh
        return self.reply("call_handoff_provider", action=f"handoff_{reason}", provider=provider)
