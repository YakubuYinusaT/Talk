"""Letting the model word Sofa's replies, in the way the caller speaks, without letting it touch a fact.

The backend decides WHAT is said (the reply key and the real facts, from the providers). The model only writes the sentence around them,
using placeholders such as {provider} and {offered}. The sentence is accepted only if it keeps every placeholder, makes up no number of its
own, asks the same number of questions as the reference, and stays short. Anything else, or any failure, and the caller hears the
reference wording instead.
"""

from pydantic import BaseModel

from ..dialogue import templates
from ..dialogue.validator import PLACEHOLDER, check_say


# A sentence that carries text written by a provider or by a search is never model-worded: in testing the model invented figures and
# answered instead of rewording. The checker refused every one, but the safest rule is not to ask: those sentences stay exact, and the
# model words only the conversation around them.
SENSITIVE = {"answer", "options"}


def carries_facts(reference: str) -> bool:
    return bool({m.group(1) for m in PLACEHOLDER.finditer(reference)} & SENSITIVE)


class Wording(BaseModel):
    say: str = ""


# The answer format makes `say` required and non-trivial. Left optional, the real model answered with an empty string whenever the
# reference sentence contained placeholders; it is the same lesson as the understanding call.
SCHEMA = {"type": "object", "properties": {"say": {"type": "string", "minLength": 10}}, "required": ["say"], "additionalProperties": False}

EXAMPLES = (
    "EXAMPLES (the placeholders stay exactly as written):\n"
    "REFERENCE: I am sorry that I could not finish that. I will pass the details to {provider}, and they will follow up with you. Is there anything else I can help with?\n"
    '{"say": "I am sorry that I could not finish that. I will pass the details to {provider}, and they will follow up with you. Is there anything else I can help with?"}\n'
    "REFERENCE: Certainly. What would you like me to look up, please?\n"
    '{"say": "Of course. What would you like me to look up for you, please?"}\n'
    "REFERENCE: Welcome back, {name}. How may I help you today?\n"
    '{"say": "Welcome back, {name}. How can I help you today?"}\n'
)


def prompt(key: str, reference: str, placeholders: list[str], questions: int, max_sentences: int, caller_said: str = "") -> str:
    return (
        f"WORDING. You are Sofa, a warm, polite voice assistant on a phone call in Nigeria. Say the MEANING below in English. "
        "Sound like a helpful person, not a script, and always use complete, courteous sentences.\n"
        f"MEANING: {templates.CONTEXT.get(key, '')}\n"
        f"REFERENCE: {reference}\n"
        f"RULES: keep every placeholder exactly as written, {', '.join('{' + p + '}' for p in placeholders) or 'none needed'}: the system fills "
        f"them with real facts and names. Write no digits and no amounts yourself. Ask exactly {questions} question(s). "
        f"At most {max_sentences} sentences. Say nothing the REFERENCE does not say. Do NOT answer the caller and do NOT invent any "
        "figure: you are only putting the REFERENCE into natural words.\n"
        + (f'THE CALLER JUST SAID (for tone only): "{caller_said[:200]}"\n' if caller_said else "")
        + EXAMPLES
    )


def accept(say: str, reference: str, facts: dict) -> tuple[str, str] | None:
    """(raw say, filled say) if it is safe to speak, else None."""
    say = (say or "").strip()
    required = {m.group(1) for m in PLACEHOLDER.finditer(reference)}
    if not say or not required <= {m.group(1) for m in PLACEHOLDER.finditer(say)}:
        return None  # a fact the backend meant to say would be missing
    questions = reference.count("?")
    if questions > 1:
        return None
    sentences = len([s for s in PLACEHOLDER.sub("x", reference).replace("?", ".").replace("!", ".").split(".") if s.strip()])
    filled = check_say(say, facts, expect_question=questions == 1, max_words=max(25, len(reference.split()) + 12),
                       max_sentences=max(2, sentences))
    return (say, filled) if filled else None


async def write(llm, key: str, reference: str, caller_said: str, facts: dict) -> tuple[str, str] | None:
    placeholders = sorted({m.group(1) for m in PLACEHOLDER.finditer(reference)})
    questions = reference.count("?")
    sentences = max(2, len([s for s in PLACEHOLDER.sub("x", reference).replace("?", ".").replace("!", ".").split(".") if s.strip()]))
    # The caller's words go inside the instructions, not in the message the model treats as the conversation: put there, the model
    # answered the caller ("I'm sorry, I didn't catch that") instead of rewording the sentence.
    obj, _ = await llm.extract(Wording, prompt(key, reference, placeholders, questions, sentences, caller_said or ""),
                               "Write the reply now.", json_schema=SCHEMA)
    return accept(obj.say, reference, facts)
