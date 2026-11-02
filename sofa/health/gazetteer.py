"""What Talk itself knows about Lagos and about health needs, so a caller's words become a place and a need before any provider is asked.

Providers do not parse speech. Talk turns "I'm near the market in Ikorodu" into a point on the map and "my baby needs jabs" into a service, and passes
those on; each provider answers from its own records.
"""

import re
from difflib import SequenceMatcher

from . import data
from .when import words

EMERGENCY_NUMBER = "112"
# a closed list of what a caller may need: the model picks one of these by meaning, the keywords are the fallback when it cannot be asked
NEEDS = (
    (data.ONCOLOGY, ("cancer", "chemo", "chemotherapy", "radiotherapy", "oncology", "oncologist", "tumour", "tumor")),
    ("pharmacy", ("pharmacy", "chemist", "drug store", "buy medicine", "buy drugs")),
    (data.ANTENATAL, ("antenatal", "ante natal", "pregnant", "pregnancy", "prenatal", "maternity")),
    (data.IMMUNISATION, ("immunisation", "immunization", "vaccine", "vaccination", "baby jab", "child jab", "baby vaccine", "jabs")),
    (data.MALARIA, ("malaria",)),
    (data.FAMILY, ("family planning", "contraceptive", "contraception")),
    (data.LAB, ("lab test", "laboratory", "blood test", "scan", "test result")),
    (data.GENERAL, ("see a doctor", "consultation", "check up", "checkup", "sick", "not feeling well", "fever")),
)
NEED_CHOICES = [need for need, _ in NEEDS]


# What a caller says when they tell Talk where THEY are, as opposed to naming a place to look in ("a clinic in Yaba") or a place that has an area in its name.
SELF_LOCATION = re.compile(r"\b(i am|i m|im|we are|we re|i live|we live|i stay|we stay|i dey|we dey|staying|living|my house|my home|our house|"
                           r"coming from|travelling from|traveling from|leaving from|i will come from|i ll come from|i am at|right now)\b")


def caller_location(text: str) -> data.Area | None:
    """The area the caller says they are in or will travel from ("I am in Surulere", "I will be coming from Ikorodu"), or None when the caller has not said
    where they are. An area that is only part of a request ("a clinic in Yaba", "Ikeja Allen Medical Centre") is not where the caller is."""
    said = " ".join(words(text))
    if not SELF_LOCATION.search(said):
        return None
    return match_area(text)


def match_area(text: str) -> data.Area | None:
    said = " ".join(words(text))
    if not said:
        return None
    for area in sorted(data.AREAS.values(), key=lambda a: -len(a.name)):  # "Lagos Island" before "Island"
        for name in (area.name.lower(), *area.aliases):
            if re.search(rf"\b{re.escape(name)}\b", said):
                return area
    best, best_score = None, 0.0
    for token in said.split():
        if len(token) < 4:
            continue
        for area in data.AREAS.values():
            score = SequenceMatcher(None, token, area.name.lower()).ratio() if " " not in area.name else 0.0
            if score > best_score:
                best, best_score = area, score
    return best if best_score >= 0.82 else None


def detect_need(text: str) -> str | None:
    said = " ".join(words(text))
    for need, phrases in NEEDS:
        if any(p in said for p in phrases):
            return need
    return None


# an alias that is also an everyday word is never taken as a medicine on its own
AMBIGUOUS_DRUG_WORDS = {"act"}


def match_drug(text: str) -> str | None:
    """A medicine the caller named, as the caller said it, when one of the known names or brand names is in their words. The result is always made of the caller's
    own words, so it is safe to pass on; the pharmacies decide which medicine it is."""
    said = " ".join(words(text))
    names = sorted({alias for drug in data.DRUGS for alias in drug.aliases if alias not in AMBIGUOUS_DRUG_WORDS}, key=lambda a: -len(a))
    for name in names:
        if re.search(rf"\b{re.escape(name)}\b", said):
            return name
    return None


