"""Reply templates. Facts come from the providers; the wording of everything Talk says on its own comes from here (or, for a reply that carries no figure or name,
from the language model through placeholders and a checker: see sofa/orchestrator/wording.py).

Placeholders use {name} or {obj.field} and are filled by validator.fill(). Talk speaks English, so there is one list of phrasings per key, rotated by turn number so
the same wording is not repeated. Every phrasing is a polite, complete sentence that is short enough to be heard on a phone.
"""

from . import service_phrases
from .validator import fill

LANG = "en"  # the language Talk listens and speaks in

PHRASES: dict[str, list[str]] = {
    # openings
    "daypart_morning": ["Good morning"],
    "daypart_afternoon": ["Good afternoon"],
    "daypart_evening": ["Good evening"],
    # Sofa answers the line. Rotated at random per call so it never sounds scripted.
    "greet_caller": [
        "{greeting}, and thank you for calling Talk. My name is Sofa. How may I help you today?",
        "{greeting}! This is Sofa, your assistant at Talk. How can I help you today?",
        "{greeting}, you have reached Talk. I am Sofa. What would you like help with today?",
        "Hello, this is Sofa at Talk. How may I help you today?",
    ],
    "greet_caller_known": [
        "{greeting}, and welcome back to Talk. It is Sofa. How may I help you today?",
        "{greeting}! Welcome back. This is Sofa at Talk. How can I help you today?",
    ],
    "greet_caller_returning": [
        "{greeting}, {name}. It is Sofa. How may I help you today?",
        "{greeting}, {name}! This is Sofa at Talk. What would you like help with today?",
        "Welcome back, {name}. How may I help you today?",
    ],
    "call_ask_again": [
        "I am sorry, I did not quite understand what you need. You can ask me to find a clinic or a pharmacy, to book or cancel a visit, or to check whether a medicine is in stock.",
        "I am sorry, could you please tell me again what you need help with? For example, a clinic near you, a medicine, or a question for a care team.",
    ],
    "guide_answer": ["{ack}. {answer} Is there anything else I can help with?"],
    "guide_none": ["I am sorry, the patient guide does not answer that question. Is there anything else I can help with?"],
    "service_off": ["I am sorry, I cannot help with {service} on this line. I can help with {offered}. What would you like to do?"],
    "call_no_human": ["I am an AI assistant, so I cannot put you through to a person myself, but I can pass your request on so that the clinic follows up. Is it for a clinic, a pharmacy, or something else?"],
    "call_give_up": ["I am sorry, I could not understand that. I can help you find a clinic or a pharmacy, book or cancel a visit, or check whether a medicine is in stock. What do you need?"],
    "call_handoff_provider": ["I am sorry that I could not finish that. I will pass the details to {provider}, and they will follow up with you. Is there anything else I can help with?"],
    "call_anything_else": ["Is there anything else I can help with?"],
    "tool_blocked": ["I am sorry, I cannot do that yet. Is there anything else I can help with?"],
    "call_chat": ["I am here. What can I do for you?", "It is good to hear from you. What would you like to do?", "Of course. What can I help you with?"],
    "call_still_there": ["Are you still there? Please tell me whenever you are ready.", "I am still here if you need anything."],
    "call_goodbye_silence": ["I will let you go for now. Please call me again any time you need me."],
    "consent": ["Please note that calls are recorded, so that we can help you and improve the service."],
    "declined": ["That is no problem at all. What would you like to do next?"],
    "no_service": ["I am sorry, this number is not in service."],
    # small words and rotating acknowledgements
    "ack": ["Certainly", "Of course", "Alright", "No problem at all"],
    # keeping the line alive: a slow reply gets one holding message after the other, in this order, then an apology
    "filler": ["One moment, please."],
    "wait_1": ["Please hold on while I retrieve the information."],
    "wait_2": ["I am still with you, thank you for waiting."],
    "wait_3": ["I am still working on it. Please give me a little more time."],
    "wait_4": ["It seems that the network is slow, but I am still working on it."],
    "wait_5": ["Thank you for waiting, the answer is nearly here. A few more seconds, please."],
    "wait_giveup": ["I am sorry, this is taking longer than expected. Please ask me again in a moment."],
    "call_goodbye": ["Thank you for calling Talk. Take care, and goodbye."],
    "call_time_limit": ["We have been on the line for a while, so I will let you go now. Please call me again any time. Goodbye."],
    "repeat_prompt": ["I am sorry, I did not catch that. Could you please say it again?"],
}

# When each phrase is spoken: shown to the language model when it words a reply (sofa/orchestrator/wording.py).
CONTEXT: dict[str, str] = {
    "daypart_morning": "Greeting word used at the start of the call, before midday.",
    "daypart_afternoon": "Greeting word used from midday to 5 pm.",
    "daypart_evening": "Greeting word used after 5 pm.",
    "greet_caller": "First words when someone calls Talk, before we know what they need. Like a friendly front desk: greet, say you are Sofa, and ask how you can help. Give several different ways to say it; one is picked at random each call.",
    "greet_caller_known": "First words to a caller who has called Talk before, whose name Sofa does not know. Welcomes them back without saying anything about them.",
    "greet_caller_returning": "First words to a caller Sofa already knows by name. Same friendly tone; several variations are picked at random.",
    "call_ask_again": "Sofa did not understand what the caller needs. Asks again politely and lists a few examples: a clinic, a medicine, a question for a care team. Never blame the caller.",
    "guide_answer": "Answers the caller's question from a facility's patient guide. {answer} is the answer, already written from the guide. Then asks if there is anything else Sofa can help with.",
    "guide_none": "The patient guide has nothing that answers the question. Apologises, never blames the caller, and asks if there is anything else Sofa can help with.",
    "service_off": "The caller asked for a service that is switched off on this line. {service} is what they asked for; {offered} lists what Sofa can do here. Polite, then asks what they would like to do.",
    "call_no_human": "The caller asked for a person before Sofa knows which service they need. Sofa is an AI assistant, so it says so kindly, offers to pass the request on so that the clinic follows up, and asks what they need.",
    "call_give_up": "Said when Sofa could not understand three times in a row and does not know which service the caller needs, so there is nobody to pass the request to. Apologises, lists what it can help with (a clinic or pharmacy, a visit, a medicine) and asks what they need.",
    "call_handoff_provider": "Said when Sofa could not finish a request for a known service. {provider} is who deals with it, for example the clinic. Apologises, says the details are passed to them and they will follow up with the caller, then asks if there is anything else.",
    "call_anything_else": "Said right after a task is finished, because Sofa never ends a call itself. Asks if there is anything else it can help with.",
    "tool_blocked": "Sofa is not allowed to do what the caller asked yet. Apologises briefly and asks if there is anything else.",
    "call_chat": "The caller said a greeting, thanks or made small talk, with no request in it. Reply warmly and briefly to what they actually said (hello back, you are welcome, and so on), then ask what they need or whether there is anything else. Several wordings are rotated.",
    "call_still_there": "Said when the caller has been silent. Gentle, never impatient. Two wordings, used in turn.",
    "call_goodbye_silence": "After several silences in a row, when nobody is answering: Sofa lets the caller go and invites them to phone again.",
    "consent": "Recording notice, played once per caller after their first reply. Must be short and clear.",
    "declined": "Said when the caller does not want what was offered. Kind, no pressure. Asks what they would like to do.",
    "no_service": "Said when someone calls a number that is not set up.",
    "ack": "Short acknowledgements said before an answer. Rotated so Sofa never says the same one twice in a row. Give up to 4.",
    "filler": "Played when Sofa needs a moment to think.",
    "wait_1": "Second holding message on a slow reply, said while Sofa fetches information. Warm and calm.",
    "wait_2": "Third holding message: tells the caller Sofa has not left the call. Warm and reassuring.",
    "wait_3": "Fourth holding message: still working, asks for a little more patience.",
    "wait_4": "Fifth holding message: says the network seems slow but Sofa is still working on it.",
    "wait_5": "Sixth holding message: relief that the answer is nearly here, a few more seconds.",
    "wait_giveup": "Said when the answer is taking too long: Sofa apologises and asks the caller to ask again in a moment. Never blames the caller. Is followed by 'Is there anything else I can help with?'",
    "call_goodbye": "Said when the caller says they need nothing else, or says goodbye. A warm, short thanks and goodbye. The call ends after it.",
    "call_time_limit": "Said when a call has gone on for a long time (eight minutes) and Sofa has to end it. Polite, not abrupt: invites the caller to call again any time.",
    "repeat_prompt": "Asks the caller to repeat when Sofa did not understand. Must be polite, never blame the caller.",
}

PHRASES.update(service_phrases.PHRASES)
CONTEXT.update(service_phrases.CONTEXT)


def pick(key: str, variant: int = 0) -> str:
    """One of the key's phrasings, chosen by `variant` (the turn number, or a random number for a greeting)."""
    options = PHRASES[key]
    return options[variant % len(options)]


def render(key: str, facts: dict, variant: int = 0) -> str:
    return fill(pick(key, variant), facts)


def acks() -> list[str]:
    return PHRASES["ack"]


def join_list(parts: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    if len(parts) <= 1:
        return parts[0] if parts else ""
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f" and {parts[-1]}"


def fixed_phrases() -> dict[str, str]:
    """Phrasings with no variables, keyed "key:index": their audio is made ahead of time (scripts/warm_cache.py)."""
    out = {}
    for key, phrasings in PHRASES.items():
        for i, p in enumerate(phrasings):
            if "{" not in p:
                out[f"{key}:{i}"] = p
    return out
