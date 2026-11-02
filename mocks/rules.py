"""Rule-based stand-ins for the language model's answers. Deterministic test doubles, not models.

They read the same prompt shapes the backend sends to the language model: a system message that starts with the name of the step (UNDERSTAND, ANSWER, WORDING,
ARGUMENTS, CHOICE) and the caller's words in the user message (`TRANSCRIPT: ...`).

Callers are polite, so the rules first take away the filler around a request ("Hello, could you please ...") and then look at what is left. When Talk has just asked a
question, a sentence that only answers it (an area, a day and time, "the private clinic", "yes please") is read as part of the request that is in progress.
"""

import re

from sofa.textutil import clean

CONFIRM = {"yes", "yeah", "yep", "yup", "ok", "okay", "correct", "sure", "right", "alright"}
CONFIRM_PHRASES = ("thats right", "go ahead", "do it", "confirm", "that is fine", "thats fine")
DENY_WORDS = {"no", "nope", "nah", "nothing", "wrong"}
DENY_PHRASES = ("thats all", "that is all", "no thanks", "no thank you", "thats wrong", "not correct", "not that one", "nothing else")

# Words and phrases that only make a request polite: they say nothing about what is wanted.
FILLER_PHRASES = ("could you", "can you", "would you", "will you", "i would like to", "i would like", "i want to", "i need to", "i am looking for", "good morning",
                  "good afternoon", "good evening", "thank you", "very much")
FILLER_WORDS = {"please", "kindly", "hello", "hi", "hey", "sofa", "abeg", "o", "oo", "sir", "ma", "actually", "well", "um", "uh", "thanks", "thank", "you", "very", "much"}
GREETING_WORDS = {"hello", "hi", "hey", "thanks", "thank", "bye", "goodbye", "morning", "afternoon", "evening", "night", "good", "there", "how", "are", "you", "sofa",
                  "very", "much", "so", "o", "oo", "again", "nice", "fine", "well", "doing", "please"}

DOMAIN_WORDS = {
    "human": {"human", "person", "agent", "someone", "representative", "operator"},
}
DOMAIN_PHRASES = {
    "human": ("customer care", "customer service", "speak to", "talk to a"),
}
STOP = {"i", "a", "the", "to", "of", "my", "me", "for", "and", "is", "it", "in", "on", "an", "do", "can", "you", "please", "want", "need", "what", "where", "how", "with", "that",
        "hello", "could", "would", "like", "kindly", "have", "there", "any", "some", "your", "are", "am", "at", "near", "help"}

# What a request sounds like, most specific first. Each rule needs the tool to be listed in the prompt, so a build without that tool never gets it named.
CENTRE_WORDS = ("cancer", "chemotherapy", "chemo", "radiotherapy", "oncology", "patient guide")
REQUEST_RULES = (
    ("health.cancel_appointment", lambda t, w: "cancel" in w or "cancelling" in w),
    ("health.facility_status", lambda t, w: bool(w & {"queue", "busy", "crowded"}) or "how long" in t or "waiting time" in t or "how many people" in t),
    ("health.available_slots", lambda t, w: "free times" in t or "available times" in t or "what times" in t or "time slots" in t or bool(w & {"slots"})),
    ("health.ask_the_centre", lambda t, w: any(c in t for c in CENTRE_WORDS) and not (w & {"book", "booking", "find", "nearest", "nearby", "closest", "where"})),
    ("health.book_appointment", lambda t, w: bool(w & {"book", "booking", "appointment", "reserve"}) or "see a doctor" in t or "see doctor" in t),
    ("health.drug_availability", lambda t, w: bool(w & {"stock", "medicine", "medicines", "drug", "drugs", "tablets", "capsules", "syrup"})),
    ("health.find_facility", lambda t, w: bool(w & {"nearest", "nearby", "closest", "clinic", "hospital", "pharmacy", "chemist", "antenatal", "immunisation", "immunization", "vaccine",
                                                    "jabs", "malaria", "pregnant", "doctor", "sick", "fever"}) or "family planning" in t),
)


def transcript_of(user: str) -> str:
    m = re.search(r"TRANSCRIPT:\s*(.*)", user)
    return m.group(1) if m else user


def strip_filler(text: str) -> str:
    """The caller's words without the politeness around them: 'Yes, please go ahead' becomes 'yes go ahead'."""
    text = f" {clean(text)} "
    for phrase in FILLER_PHRASES:
        text = text.replace(f" {phrase} ", " ")
    return " ".join(w for w in text.split() if w not in FILLER_WORDS)


def is_greeting(text: str) -> bool:
    """Only a greeting or thanks, with nothing else asked: every word is one of the greeting words."""
    words = clean(text).split()
    return bool(words) and all(w in GREETING_WORDS for w in words)


def classify_domain(user: str) -> str:
    """The fixed choices that are not a registered service: a person, small talk, or none of them. Keyword match, first hit wins."""
    text = clean(transcript_of(user))
    words = set(text.split())
    for domain in ("human",):
        if words & DOMAIN_WORDS[domain] or any(p in text for p in DOMAIN_PHRASES[domain]):
            return domain
    if is_greeting(text):
        return "chat"  # no request in it: a greeting or thanks
    return "unclear"


def listed_tools(system: str) -> set[str]:
    """The tool ids and service names the prompt offers, as '- id: what it does' lines."""
    return {m.group(1) for m in re.finditer(r"^- ([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)?): ", system, re.M)}


def service_action(system: str, raw: str) -> str | None:
    """A registered tool the prompt lists beyond the fixed choices (the health service): what the caller asked for, by the rules above, and only then by the words
    the caller and the listing share. A tool is always preferred to the bare name of its service."""
    offered = listed_tools(system)
    text = clean(raw)
    words = set(text.split())
    for tool, rule in REQUEST_RULES:
        if tool in offered and rule(text, words):
            return tool
    best, best_score = None, 0
    for line in system.splitlines():
        m = re.match(r"^- ([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)?): (.*)$", line)
        if not m or m.group(1).startswith(("chat", "human", "unclear")):
            continue
        listed = set(clean(m.group(2) + " " + m.group(1).replace(".", " ").replace("_", " ")).split()) - STOP
        score = len(listed & words) * 2 + (1 if "." in m.group(1) else 0)
        if score > 1 and score > best_score:
            best, best_score = m.group(1), score
    return best


def classify_answer(user: str) -> str:
    """Yes / no / other for a question the assistant just asked. The politeness is taken away first, so 'Yes, please go ahead' is a yes and 'Tomorrow morning, please'
    is neither."""
    text = strip_filler(transcript_of(user))
    words = text.split()
    first = words[0] if words else ""
    if text in CONFIRM or first in CONFIRM or any(p in text for p in CONFIRM_PHRASES) or (set(words) & CONFIRM and len(words) <= 3):
        return "yes"
    if text in DENY_WORDS or first in DENY_WORDS or any(p in text for p in DENY_PHRASES) or (set(words) & DENY_WORDS and len(words) <= 3):
        return "no"
    return "other"


def in_progress(system: str) -> str | None:
    """The request Talk is helping with, when the prompt names one (IN PROGRESS: health.find_facility)."""
    m = re.search(r"^IN PROGRESS:\s*([a-z][a-z0-9_.]*)\s*$", system, re.M)
    return m.group(1) if m and m.group(1) in listed_tools(system) else None


def understand(system: str, user: str) -> dict:
    """One answer for the whole turn: the action and yes/no."""
    raw = transcript_of(user)
    asked = re.search(r"^ASKED:\s*(.*)$", system, re.M)
    nothing_asked = not asked or asked.group(1).strip() == "nothing"
    answer = None if nothing_asked else classify_answer(user)
    action = service_action(system, raw)
    if action is None and not nothing_asked and answer == "other" and not is_greeting(raw):
        action = in_progress(system)    # an area, a day and time or a choice: the answer belongs to the request Talk is helping with
    if action is None:
        action = classify_domain(user)
    return {"action": action, "answer": answer}


def wording(system: str) -> dict:
    """The wording step: say the reference sentence as it is."""
    m = re.search(r"^REFERENCE:\s*(.*)$", system, re.M)
    return {"say": m.group(1).strip() if m else ""}


def guide_answer(system: str) -> str:
    """The answer from a patient guide: say the first guide entry as it is."""
    m = re.search(r"^GUIDE ENTRY 1:\s*(.*)$", system, re.M)
    return m.group(1).strip() if m else "I could not find that."
