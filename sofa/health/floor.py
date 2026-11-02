"""The emergency floor: a fast reading of the caller's words for danger, with no model, which runs before anything else on every turn.

The language model reads every turn for urgency by meaning, in any words. This floor is the safety net beneath it: it can only raise the level the model
gives, never lower it, so an emergency is still recognised when the model is slow, down or wrong. It knows the plain ways people describe danger (not
breathing, collapsed, a fit, heavy bleeding, chest pain, choking, poison), allows for spelling mistakes from the speech recogniser ("colapsed",
"bleding"), and stays quiet on the common ways those words appear without danger ("I am not bleeding", "a seizure years ago", "dying of hunger").

Levels: none (nobody seems to be in danger), possible (it might be an emergency: Talk gives the emergency number and asks), emergency (someone may be in
danger now: Talk gives the emergency number and starts the emergency help at once).
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

NONE, POSSIBLE, EMERGENCY = "none", "possible", "emergency"
LEVELS = (NONE, POSSIBLE, EMERGENCY)
RANK = {NONE: 0, POSSIBLE: 1, EMERGENCY: 2}

NEGATORS = {"not", "no", "never", "without", "nothing", "stopped", "isnt", "wasnt", "didnt", "dont", "doesnt", "hasnt", "havent", "nobody", "none", "neither", "nor"}
PAST = re.compile(r"\b(years? ago|months? ago|weeks? ago|days? ago|long ago|used to|history of|when i was|last (week|month|year)|yesterday)\b")
FIGURE = re.compile(r"\b(giving|give|gave|gives|will give) (me|him|her|us)\b")   # "you are giving me a heart attack"
FUZZY = 0.80

BREATH = ("breath*", "breathing", "breathe")
WAKE = ("wake", "waking", "respond*", "responsive", "moving", "move", "breathing")
PERSON = ("he", "she", "mother", "father", "baby", "child", "brother", "sister", "husband", "wife", "neighbour", "man", "woman", "boy", "girl")

# (level, name, kind, slots, window). Every slot must be found within `window` words of the first. A pattern of the kind "absent" is itself a negation
# ("not breathing"), so its first slot must come first and it is never cancelled; a pattern of the kind "present" is cancelled by a negator just before
# it, by a past marker or by a figure of speech.
PATTERNS = [
    (EMERGENCY, "not breathing", "absent", [("not", "no", "stopped", "cannot", "cant", "wont", "never", "hardly", "struggling", "hard", "difficulty", "trouble", "unable"), BREATH], 3),
    (EMERGENCY, "doubt about breathing", "absent", [("know", "sure", "tell", "think"), BREATH], 6),
    (EMERGENCY, "not waking or responding", "absent", [("not", "no", "cannot", "cant", "wont", "never", "unable", "gree", "refuses", "stopped"), WAKE], 3),
    (EMERGENCY, "unconscious", "present", [("unconscious", "unresponsive", "slumped", "slump*", "collaps*", "collapsed", "collapse")], 1),
    (POSSIBLE, "eyes rolling", "present", [("eyes", "eye"), ("rolling", "rolled", "turn", "turned", "white")], 3),
    (POSSIBLE, "fainted", "present", [("faint*", "fainted")], 1),
    (POSSIBLE, "passed out", "present", [("passed", "passing"), ("out",)], 2),
    (EMERGENCY, "seizure", "present", [("seizure*", "seizing", "convuls*", "foaming", "epileptic")], 1),
    (EMERGENCY, "shaking the body", "present", [("shake", "shaking", "shaken"), ("body",)], 3),
    (POSSIBLE, "shaking badly", "present", [("shaking", "shivering"), ("badly", "fever", "uncontrollably")], 4),
    (EMERGENCY, "choking", "present", [("choking", "choke*", "chok*")], 1),
    (EMERGENCY, "poison", "present", [("poison*", "overdose", "overdosed")], 1),
    (POSSIBLE, "swallowed something", "present", [("swallowed", "swallow", "drank", "ate"), ("battery", "bleach", "kerosene", "tablets", "something", "poison")], 3),
    (EMERGENCY, "heavy bleeding", "present", [("bleed*", "bleding", "bleeding"), ("heavily", "heavy", "lot", "badly", "out", "nonstop", "plenty", "everywhere", "seriously", "much", "stop")], 4),
    (EMERGENCY, "blood everywhere", "present", [("blood",), ("plenty", "everywhere", "much", "lot", "comot", "pouring", "flowing", "gushing")], 4),
    (EMERGENCY, "vomiting blood", "present", [("vomit*", "vomiting"), ("blood",)], 3),
    (POSSIBLE, "bleeding", "present", [("bleed*", "bleding")], 1),
    (EMERGENCY, "chest pain", "present", [("chest",), ("pain", "crushing", "pressure", "hurting")], 4),
    (POSSIBLE, "tight chest", "present", [("chest",), ("tight", "heavy")], 4),
    (EMERGENCY, "heart attack", "present", [("heart",), ("attack", "atack")], 1),
    (EMERGENCY, "gasping", "present", [("gasping", "gasp")], 1),
    (EMERGENCY, "blue lips", "present", [("blue",), ("lips", "face", "body", "turning", "turned")], 3),
    (EMERGENCY, "dying", "present", [("dying",)], 1),
    (POSSIBLE, "died or dead", "present", [("died", "dead"), PERSON], 4),
    (EMERGENCY, "wounded", "present", [("stabbed", "shot", "gunshot", "drowning", "electrocuted")], 1),
    (EMERGENCY, "hit by a vehicle", "present", [("knocked", "hit", "run"), ("car", "bus", "okada", "motorbike", "lorry", "vehicle", "over")], 4),
    (POSSIBLE, "fell down", "present", [("fell", "fallen", "collapse"), ("down", "over")], 2),
    (POSSIBLE, "not talking any more", "absent", [("not", "no", "cannot", "cant", "stopped", "doesnt", "wont"), ("talking", "talk", "speaking", "speak"),
                                                ("again", "anymore", "more")], 3),
    (POSSIBLE, "fell from a height", "present", [("fell", "fall", "falling"), ("floor", "roof", "storey", "tree", "ladder", "stairs", "height")], 4),
    (EMERGENCY, "serious accident", "present", [("accident", "accidents", "crash"), ("hurt", "injured", "bleeding", "victim", "victims", "badly", "serious", "bad")], 5),
    (POSSIBLE, "an accident", "present", [("accident", "accidents", "crash"), ("road", "car", "motor", "okada", "bike", "had", "just", "there")], 4),
    (POSSIBLE, "labour", "present", [("labour", "labor"), ("coming", "pain", "now", "waters", "started", "broke")], 5),
    (EMERGENCY, "emergency said", "present", [("emergency",), ("this", "its", "is", "an")], 2),
    (POSSIBLE, "emergency word", "present", [("emergency", "emergencies")], 1),
    (EMERGENCY, "baby stopped moving", "absent", [("stopped", "not"), ("moving", "kicking")], 3),
    (EMERGENCY, "harm to self", "present", [("suicide", "suicidal")], 1),
    (EMERGENCY, "kill myself", "present", [("kill", "end"), ("myself", "life")], 3),
    (POSSIBLE, "wish to die", "present", [("want", "wan", "wish"), ("die", "dead")], 2),
    (POSSIBLE, "not wanting to live", "absent", [("not", "dont", "no"), ("want", "wish"), ("live", "living")], 4),
    (POSSIBLE, "lying on the floor", "present", [("lying", "laying", "lies"), ("floor", "ground")], 4),
    (POSSIBLE, "come quickly", "present", [("come",), ("quickly", "quick", "fast")], 3),
    (POSSIBLE, "112", "present", [("112",)], 1),
]


@dataclass(frozen=True)
class Signal:
    level: str = NONE
    source: str = "none"            # floor | model | both | none
    hits: tuple[str, ...] = ()      # the names of the patterns that matched, never the caller's words


def normal(text: str) -> list[str]:
    """Lower case, apostrophes removed (can't becomes cant), everything except letters and digits dropped."""
    return re.findall(r"[a-z0-9]+", (text or "").lower().replace("'", "").replace("’", ""))


def is_form(token: str, form: str) -> bool:
    """A word is a form of a pattern word when it is the same word, starts with a stem that ends in *, or is a close spelling of a word of six letters or more."""
    if form.endswith("*"):
        return token.startswith(form[:-1])
    if token == form:
        return True
    return len(form) >= 6 and len(token) >= 5 and SequenceMatcher(None, token, form).ratio() >= FUZZY


def _positions(tokens: list[str], forms: tuple[str, ...]) -> list[int]:
    return [i for i, t in enumerate(tokens) if any(is_form(t, f) for f in forms)]


def _find(tokens: list[str], slots: list[tuple[str, ...]], window: int, ordered: bool) -> tuple[int, int] | None:
    """The first place where every slot is found within `window` words, as (first position, last position)."""
    lists = [_positions(tokens, s) for s in slots]
    if not all(lists):
        return None
    for start in lists[0]:
        spots = [start]
        for rest in lists[1:]:
            near = [p for p in rest if p != start and ((0 < p - start <= window) if ordered else abs(p - start) <= window)]
            if not near:
                break
            spots.append(min(near, key=lambda p: abs(p - start)))
        else:
            return min(spots), max(spots)
    return None


def _quiet(name: str, tokens: list[str], first: int, last: int) -> bool:
    """True when a pattern of the kind "present" is not about danger now: negated just before it, in the past, or a figure of speech."""
    if any(t in NEGATORS for t in tokens[max(0, first - 3):last + 1]):
        return True
    if PAST.search(" ".join(tokens[max(0, first - 6):last + 7])) or FIGURE.search(" ".join(tokens[max(0, first - 4):first + 1])):
        return True
    after = tokens[last + 1:last + 4]
    if name == "dying" and after[:1] and after[0] in ("of", "for", "to", "laughing", "from"):
        return True
    if name == "unconscious" and any(w in after for w in ("laughter", "laughing")):
        return True
    if name == "bleeding" and any(w in after for w in ("little", "slightly", "bit")):
        return True
    if name == "passed out" and any(w in tokens for w in ("university", "school", "nysc", "parade", "camp", "graduated", "from")):
        return True     # in Nigerian English, passing out can mean graduating
    if name == "died or dead" and any(w in tokens for w in ("phone", "battery", "laptop", "network")):
        return True
    return False


def read(text: str) -> Signal:
    """The level the words alone give, and the patterns that gave it."""
    tokens = normal(text)
    level, hits = NONE, []
    for lvl, name, kind, slots, window in PATTERNS:
        found = _find(tokens, slots, window, ordered=kind == "absent" and len(slots) > 1)
        if not found:
            continue
        first, last = found
        if kind == "present" and _quiet(name, tokens, first, last):
            continue
        if name == "emergency said" and not any(w in tokens[max(0, first - 2):last + 1] for w in ("this", "an")):
            continue
        if name == "not wanting to live" and tokens[last + 1:last + 2] and tokens[last + 1] in ("in", "at", "near", "here", "there", "with", "on", "anywhere"):
            continue    # "I do not want to live in Ikeja" is about a place, not about harm
        hits.append(name)
        if RANK[lvl] > RANK[level]:
            level = lvl
    return Signal(level, "floor" if level != NONE else "none", tuple(hits))


def combine(floor: Signal, model_level: str | None) -> Signal:
    """The stronger of the floor and the model. The model's answer counts only if it is one of the three levels, and nothing here can lower the floor."""
    m = model_level if model_level in RANK else NONE
    level = floor.level if RANK[floor.level] >= RANK[m] else m
    source = "both" if floor.level != NONE and m != NONE else "floor" if floor.level != NONE else "model" if m != NONE else "none"
    return Signal(level, source, floor.hits)
