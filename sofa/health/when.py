"""Days and times, the way people say them on a phone: reading them (tomorrow, 9:30 in the morning) and saying them back.

Times are Lagos time (UTC+1, no daylight saving) as plain datetimes with no zone, because that is the only clock a caller and a clinic share.
"""

import re
from datetime import date, datetime, timedelta, timezone

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WINDOWS = {"morning": (7 * 60, 12 * 60), "afternoon": (12 * 60, 16 * 60), "evening": (16 * 60, 20 * 60)}
HOUR_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}   # a time said in words
# A yes needs an affirmative word or phrase. The word "please" is deliberately not one of them: it is politeness that comes with questions, requests and refusals as
# often as with agreement, so "Please tell me more." must never be heard as consent to a booking or a cancellation.
YES_WORDS = {"yes", "yeah", "yep", "yup", "ok", "okay", "sure", "correct", "confirm", "confirmed", "absolutely", "definitely", "alright"}
YES_PHRASES = ("go ahead", "go on", "that is fine", "thats fine", "that is right", "thats right", "that is correct", "thats correct", "that is okay", "thats okay",
               "sounds good", "all right", "please book", "please do", "please confirm", "book it", "do it", "yes please")
# A clear no: a refusal, or a wish to change what was offered.
NO_WORDS = {"no", "nope", "nah", "not", "dont", "never", "wrong", "stop", "change", "another", "different", "cancel"}
# Phrases that contain a no or a yes word without being an answer, such as "no problem" or "I am not sure": they are set aside before the words are read.
SET_ASIDE_PHRASES = ("no problem", "no worries", "not sure", "do not know", "dont know", "no idea")
# A caller who is thinking, waiting or asking for more has not agreed to anything, even if a yes word is somewhere in the sentence.
HESITATION_PHRASES = ("let me think", "i will think", "i want to think", "think about it", "tell me more", "hold on", "wait", "one moment", "one second", "maybe", "perhaps",
                      "not yet", "not sure", "do not know", "dont know", "no idea")


def lagos_now() -> datetime:
    return (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None, microsecond=0)


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def spoken(text: str) -> str:
    """The caller's words in lower case with the punctuation taken out, and a space at each end so that whole words and phrases can be found by searching for them."""
    return " " + " ".join(re.findall(r"[a-z0-9]+", (text or "").lower().replace("'", "").replace("’", ""))) + " "


def hesitates(text: str) -> bool:
    """True when the caller is thinking, waiting or asking for more instead of answering, so that nothing may be booked or cancelled on the strength of this sentence."""
    said = spoken(text)
    return any(f" {phrase} " in said for phrase in HESITATION_PHRASES)


def answer_of(text: str, cancelling: bool = False) -> str | None:
    """'yes', 'no', or None when the words are neither. A yes needs an affirmative word or phrase, and politeness alone ("please", "thank you") is never one. A clear no
    wins over a yes ("no, please change it"), and a caller who hesitates ("yes, but let me think") has not said yes. When the question was whether to cancel an
    appointment, the word "cancel" is how the caller says yes, and "keep" is how they say no."""
    said = spoken(text)
    hesitating = hesitates(text)
    for phrase in SET_ASIDE_PHRASES:
        said = said.replace(f" {phrase} ", " ")
    found = set(said.split())
    no_words = NO_WORDS - {"cancel"} if cancelling else NO_WORDS
    said_no = bool(found & no_words) or (cancelling and "keep" in found)
    said_yes = bool(found & YES_WORDS) or any(f" {phrase} " in said for phrase in YES_PHRASES) or (cancelling and "cancel" in found)
    if said_no:
        return "no"
    if said_yes and not hesitating:
        return "yes"
    return None


def parse_when(text: str, now: datetime) -> dict:
    """What a caller asked for: {"day": date | None, "window": (from_minute, to_minute) | None, "at": minute | None}. Anything not said stays None."""
    t = " ".join(re.findall(r"[a-z0-9:.']+", (text or "").lower())).replace(". ", " ")  # keep the colon: 9:30 is one time
    out: dict = {"day": None, "window": None, "at": None}
    today = now.date()
    if "day after tomorrow" in t:
        out["day"] = today + timedelta(days=2)
    elif "tomorrow" in t:
        out["day"] = today + timedelta(days=1)
    elif "today" in t or "tonight" in t or "this evening" in t or "this afternoon" in t or "this morning" in t:
        out["day"] = today
    elif "next week" in t:
        out["day"] = today + timedelta(days=7 - today.weekday())  # the Monday of next week
    else:
        for index, name in enumerate(WEEKDAYS):
            if re.search(rf"\b{name}\b|\b{name[:3]}\b", t):
                out["day"] = today + timedelta(days=(index - today.weekday()) % 7 or 7)  # the next one, never today
                break
    for name, window in WINDOWS.items():
        if name in t or (name == "evening" and "tonight" in t):
            out["window"] = window
    for spoken, number in HOUR_WORDS.items():    # "at two in the afternoon" is read as "at 2 in the afternoon"
        t = re.sub(rf"\b(at|by|around)\s+{spoken}\b", rf"\1 {number}", t)
        t = re.sub(rf"\b{spoken}\s+(?=am\b|pm\b|o'clock|oclock|in the (?:morning|afternoon|evening))", f"{number} ", t)
    match = re.search(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a m|p m|o'clock|oclock)?\b", t)
    if match and (match.group(3) or match.group(2) or re.search(r"\b(at|by|around)\s+\d", t)):
        hour, minute, mark = int(match.group(1)), int(match.group(2) or 0), (match.group(3) or "").replace(" ", "")
        if 0 <= hour <= 23 and minute < 60:
            if mark == "pm" and hour < 12:
                hour += 12
            elif mark == "am" and hour == 12:
                hour = 0
            elif not mark and hour < 12 and re.search(r"\b(afternoon|evening)\b", t):
                hour += 12  # "at 2 in the afternoon"
            elif not mark and hour == 12 and "morning" in t:
                hour = 0
            elif not mark and 1 <= hour <= 6:
                hour += 12  # a clinic is not open at 3 in the morning: "at 3" means the afternoon
            out["at"] = hour * 60 + minute
    return out


def said_nothing_about_time(found: dict) -> bool:
    return not (found["day"] or found["window"] or found["at"] is not None)


def say_day(day: date, today: date) -> str:
    gap = (day - today).days
    if gap == 0:
        return "today"
    if gap == 1:
        return "tomorrow"
    return f"{WEEKDAYS[day.weekday()].capitalize()} {day.day} {day.strftime('%B')}"


def say_on_day(day: date, today: date) -> str:
    """The day as it follows a verb or a place in a sentence: "today" and "tomorrow" stand alone, and a date needs "on" in front of it ("on Friday 30 October")."""
    spoken_day = say_day(day, today)
    return spoken_day if spoken_day in ("today", "tomorrow") else f"on {spoken_day}"


def say_time(moment: datetime) -> str:
    hour, minute = moment.hour, moment.minute
    if hour == 12 and minute == 0:
        return "12 noon"
    part = "in the morning" if hour < 12 else "in the afternoon" if hour < 16 else "in the evening"
    clock = hour % 12 or 12
    return f"{clock}:{minute:02d} {part}" if minute else f"{clock} {part}"


def say_hour(hour: int) -> str:
    if hour in (0, 24):
        return "midnight"
    return say_time(datetime(2000, 1, 1, hour, 0))


def join_names(names: list[str], word: str = "or") -> str:
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + f" {word} " + names[-1]


def when_in_words(found: dict, today: date) -> str | None:
    """What parse_when found, as a short phrase ("tomorrow at 9 in the morning", "Friday in the afternoon"), or None when no time was said."""
    if said_nothing_about_time(found):
        return None
    parts = []
    if found["day"]:
        parts.append(say_day(found["day"], today))
    if found["at"] is not None:
        parts.append("at " + say_time(datetime(2000, 1, 1, found["at"] // 60, found["at"] % 60)))
    elif found["window"]:
        parts.append("in the " + next(name for name, window in WINDOWS.items() if window == found["window"]))
    return " ".join(parts)
