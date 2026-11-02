"""Spoken answers from a facility's own patient guide.

The health service finds the guide entries that match the caller's question, and the model writes a short spoken answer from those entries only.
The answer is spoken only if every number in it comes from an entry. If the model fails or adds a figure of its own, Sofa reads the best entry as
it is written, so that Talk never answers a health question from memory.
"""

import re

from pydantic import BaseModel

from ...dialogue.outcome import Outcome

NUMBER = re.compile(r"\d[\d,.]*")


class GuideAnswer(BaseModel):
    say: str = ""


SCHEMA = {"type": "object", "properties": {"say": {"type": "string", "minLength": 10}}, "required": ["say"], "additionalProperties": False}


def prompt(question: str, entries: list[str]) -> str:
    return (
        "ANSWER. You are Sofa, a warm voice assistant on a phone call in Lagos. Answer the QUESTION in one or two short, plain "
        "sentences that sound natural when spoken aloud. Use ONLY the GUIDE ENTRIES below, which a health facility wrote for its patients. If they do not "
        "answer the question, say that you could not find it. Do not add any fact, figure or name that is not in the GUIDE ENTRIES, and give no medical advice "
        "of your own. No lists and no web addresses.\n"
        f"QUESTION: {question}\n" + "\n".join(f"GUIDE ENTRY {i}: {e}" for i, e in enumerate(entries, 1))
    )


def grounded(say: str, entries: list[str]) -> bool:
    """True when the answer says something and every figure in it was written in one of the guide entries."""
    source = " ".join(entries)
    return bool(say.strip()) and all(n.strip(",.") in source for n in NUMBER.findall(say))


def sentence_of(entry: str, limit: int = 220) -> str:
    """A guide entry shortened at a word boundary, so that it can be read aloud as it is."""
    entry = " ".join(entry.split())
    return entry if len(entry) <= limit else entry[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "."


async def spoken_answer(gw, question: str, entries: list[str]) -> Outcome:
    """Turns the matching guide entries into a short spoken answer. The model writes it from the entries only, and it is spoken only if every figure came from them."""
    if not entries:
        return gw.reply("guide_none", action="guide_none")
    say = ""
    try:
        obj, _ = await gw.svc.llm.extract(GuideAnswer, prompt(question, entries), "Write the answer now.", json_schema=SCHEMA)
        say = " ".join(obj.say.split())
    except Exception:
        say = ""
    source = "model"
    if not grounded(say, entries):  # nothing the model added is spoken: the best entry is read as it was written
        say, source = sentence_of(entries[0]), "entry"
    return gw.reply("guide_answer", action=f"guide_{source}", answer=say)
