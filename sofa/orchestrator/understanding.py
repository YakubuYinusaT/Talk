"""One model call per turn that works out everything the caller meant.

Callers speak English. The model is shown the registered tools and where the conversation is, and returns one structured answer: whether anyone may be in danger
(`urgency`), what the caller wants (a single `action`) and whether they answered a question Talk had just asked. The backend then validates that answer against the tool registry and runs it. The model decides what was meant; it never supplies a fact.

What testing the models taught us (docs/model_log.md):
  * every field must be REQUIRED in the answer format, or the model skips most of them;
  * one flat `action` decision works far better than a `domain` and then a `tool`;
  * a dozen example sentences are what make yes/no answers and tool choices come out right;
  * every field costs answer time, so only the fields a situation needs are asked for.
"""

import json

from pydantic import BaseModel, model_validator

SPECIAL = ["chat", "human", "unclear"]
CORE_FIELDS = ["urgency", "action", "answer"]
URGENCY = ["none", "possible", "emergency"]


class Understanding(BaseModel):
    urgency: str = "none"     # none | possible | emergency: read by meaning, in any words, on every turn
    action: str = "unclear"   # a registered tool id (health.find_facility ...), or chat | human | unclear
    answer: str | None = None  # yes | no | other: only when Talk had just asked a question
    # worked out from `action`, never asked of the model:
    domain: str = "unclear"   # health | chat | human | unclear
    tool: str | None = None   # the registered tool id, for a health action

    @model_validator(mode="after")
    def _derive(self):
        if self.answer in ("none", ""):
            self.answer = None
        if self.urgency not in URGENCY:
            self.urgency = "none"
        self.rederive()
        return self

    def rederive(self, tools: dict[str, str] | None = None, domains=()) -> None:
        """`tools` maps a tool id to its service and `domains` lists the services beyond the fixed ones (the health service)."""
        if "." in self.action:
            self.domain, self.tool = (tools or {}).get(self.action, "unclear"), self.action
        else:
            self.domain, self.tool = (self.action if self.action in SPECIAL or self.action in domains else "unclear"), None

    def settle(self, registered, domains=()) -> None:
        """Only a registered operation may stand. An operation that is not on the registry is treated as not understood, so an invented name cannot come back
        later from the saved action. `registered` is a dict of tool id to service."""
        tools = registered if isinstance(registered, dict) else {t: "health" for t in registered}
        if "." in self.action and self.action not in tools:
            self.action = "unclear"
        self.rederive(tools, domains)


def schema(tool_ids: list[str], domains: list[str] | tuple = ()) -> dict:
    """The answer format. Every field is required, and the choices the model may use are written into it, so the output cannot name an operation or a service
    that does not exist."""
    props = Understanding.model_json_schema()["properties"]
    wire = {name: props[name] for name in CORE_FIELDS}
    wire["action"] = {"enum": [*tool_ids, *SPECIAL, *[d for d in domains if d not in SPECIAL]], "type": "string"}
    wire["answer"] = {"enum": ["yes", "no", "none"], "type": "string"}
    wire["urgency"] = {"enum": URGENCY, "type": "string"}
    return {"type": "object", "properties": wire, "required": list(wire), "additionalProperties": False}


def _example(action: str, said: str, *, answer: str = "none", asked: str | None = None, progress: str | None = None, urgency: str = "none") -> str:
    row = {"urgency": urgency, "action": action, "answer": answer}
    context = ""
    if asked:
        context = f'  (Talk had just asked: "{asked}"' + (f"; the request in progress is {progress}" if progress else "") + ")"
    return f"Caller: {said}{context}\n" + json.dumps(row, ensure_ascii=False)


_AREA = "Of course. Which area of Lagos are you in, please? For example Surulere, Yaba or Ikeja."
_LIST = ("I found three places near Surulere for antenatal care. The first is Surulere Care Clinic, a private clinic, with about 40 minutes of waiting and a consultation fee of "
         "8,000 naira. The second is Aguda Community Health Centre, a state primary health centre, with about 100 minutes of waiting and a fee of 500 naira. The third is Yaba "
         "Mainland Health Centre, a state primary health centre, with about 65 minutes of waiting and a fee of 500 naira.")
_OFFER = _LIST + " Would you like me to book an appointment at one of them for you?"
_CHOICE = _LIST + " Which one would you like, please?"
_WHEN = "Which day and time would you like at Surulere Care Clinic, please? For example, tomorrow morning."
_Q = "I can book you at Aguda Community Health Centre tomorrow at 8 in the morning. Would you like me to book it for you?"
EXAMPLES = "\n".join([
    # what they want: callers are polite, so please, hello and could you are never the request
    _example("health.find_facility", "Please help me find the nearest clinic for antenatal care."),
    _example("health.find_facility", "Hello, where is the nearest pharmacy in Ikeja, please?"),
    _example("health.find_facility", "Good afternoon. My baby needs her jabs. Where can I go in Yaba, please?"),
    _example("health.facility_status", "Could you tell me how long the queue is at Aguda health centre, please?"),
    _example("health.available_slots", "What times are free at the Ikeja care centre, please?"),
    _example("health.book_appointment", "I would like to book an appointment in Yaba, please."),
    _example("health.cancel_appointment", "Please can you cancel my appointment for tomorrow?"),
    _example("health.drug_availability", "Hello, do you have amoxicillin in stock, please?"),
    _example("health.ask_the_centre", "What should I bring to my first visit at the cancer centre, please?"),
    _example("chat", "Good morning."),
    _example("chat", "Thank you very much."),
    _example("human", "May I speak to a person, please?"),
    # urgency is read by meaning, whoever is in danger and however it is said, and a figure of speech or a danger that is over is not one
    _example("health.find_facility", "Please come quickly, my wife is lying on the floor and she will not answer me.", urgency="emergency"),
    _example("health.find_facility", "My little boy swallowed a battery a few minutes ago.", urgency="emergency"),
    _example("health.find_facility", "Something bit my leg in the bush and now it is swelling up fast.", urgency="emergency"),
    _example("health.book_appointment", "I want to see a doctor about my chest, it has been tight for some days.", urgency="possible"),
    _example("health.book_appointment", "I am not bleeding, I only want a check-up, please.", urgency="none"),
    _example("health.find_facility", "I am dying of hunger, please find me a pharmacy.", urgency="none"),
    # answering a question Talk just asked: an area, a choice or a day and time belongs to the request in progress
    _example("health.find_facility", "I am in Surulere.", asked=_AREA, progress="health.find_facility"),
    _example("health.find_facility", "Surulere, please.", asked=_AREA, progress="health.find_facility"),
    _example("health.book_appointment", "The private clinic, please.", asked=_CHOICE, progress="health.book_appointment"),
    _example("health.book_appointment", "The cheaper one, please.", asked=_CHOICE, progress="health.book_appointment"),
    _example("health.book_appointment", "Tomorrow morning, please.", asked=_WHEN, progress="health.book_appointment"),
    # a bare yes or no is the answer, not a request (a yes that also chooses a place, such as "Yes, please book the private clinic", is a yes too)
    _example("unclear", "Yes, please go ahead.", answer="yes", asked=_Q, progress="health.book_appointment"),
    _example("unclear", "Yeah, that is right.", answer="yes", asked=_Q, progress="health.book_appointment"),
    _example("unclear", "Yes, please book the private clinic.", answer="yes", asked=_OFFER, progress="health.find_facility"),
    _example("unclear", "No, thank you. That is not right.", answer="no", asked=_Q, progress="health.book_appointment"),
    _example("unclear", "No no no", answer="no", asked=_Q, progress="health.book_appointment"),
])


def prompt(gw) -> str:
    """The instructions and the state of the conversation, for the model, for a live call."""
    orchestrator = gw.svc.orchestrator
    services = [(orchestrator.service(d), orchestrator.tools.for_domain(d)) for d in orchestrator.extra_domains() if orchestrator.service(d)]
    return build(gw.st, services)


def build(st: dict, services=()) -> str:
    """The instructions and the state of the conversation, for the model."""
    more = ""
    for service, service_tools in services:  # a registered service beyond the fixed ones: named and described from the registry, never from code
        more += f"- {service.key}: {service.hint}\n"
        more += "".join(f"- {t.tool_id}: {t.description}" + (f" (needs: {', '.join(t.required)})" if t.required else "") + "\n" for t in service_tools)
    pending = st.get("pending") or {}
    history = " | ".join((st.get("said") or [])[-2:]) or "none"
    return (
        "UNDERSTAND. You are the language and intent layer of Talk, a voice assistant answering a phone call in Lagos, Nigeria. Callers speak "
        "English. Work out what the caller means and answer with JSON only, with every field present.\n"
        "Callers are polite and speak in full sentences, with words such as hello, please and could you around the request. Those words are never the request: look for "
        "what the caller actually wants.\n"
        "urgency: none, possible or emergency, judged by meaning in any words: plain English, Nigerian English, Pidgin, and words the speech recogniser may have "
        "spelled wrongly. emergency: a person, the caller or someone else, may be in danger of death or serious harm now, for example not breathing or struggling to "
        "breathe, not waking or not responding, collapsed, a fit, heavy bleeding, choking, poisoning, a bite or sting with fast swelling, chest pain with trouble "
        "breathing, a serious accident or injury, a birth that is happening now, or a person who says they want to harm themselves. possible: it might be one of "
        "those, or the caller is unsure, or asks about emergency care or the emergency number. none: everything else, including a person who says nobody is in "
        "danger, something that is over, a check-up or an appointment, and a figure of speech such as I am dying of hunger. If you are not sure between possible and "
        "emergency, say emergency. If you are not sure between none and possible, say possible.\n"
        "action: what the caller wants. Exactly one of:\n"
        + more +
        "- chat: only a greeting, thanks or small talk\n- human: asks for a person\n- unclear: none of the above, or only a yes or no\n"
        "A conversation goes on over several turns. ASKED is the question Talk has just asked and IN PROGRESS is the request Talk is helping with. When the caller "
        "answers ASKED with the thing it asked for (an area, a day and time, a medicine, or a choice such as the private clinic or the cheaper one), the action is the "
        "request IN PROGRESS. When the caller only says yes or no, the action is unclear. When the caller asks for something different, name that instead.\n"
        "TALK SAID is what Talk said last, and CALL SO FAR is what this call is about. When the caller refers back to it (book it, that one, the first one, "
        "the cheaper one, yes please book), the action is the request it refers to, even when no question is open.\n"
        "answer: yes or no if the caller is answering the question in ASKED with a yes or a no, even when more is said (for example yes, please book the private clinic), "
        "else none.\n"
        f"EXAMPLES:\n{EXAMPLES}\n"
        f"ASKED: {pending.get('question') or 'nothing'}\nIN PROGRESS: {pending.get('tool') or 'nothing'}\nRECENT: {history}\n"
        f"TALK SAID: {st.get('talk_said') or 'nothing'}\nCALL SO FAR: {st.get('call_so_far') or 'nothing'}"
    )
