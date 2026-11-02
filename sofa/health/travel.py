"""How long it takes to get from the caller's area to a place, with the usual Lagos traffic at that hour.

Talk asks where the caller is before it says any time. The estimate then runs inside Talk, with no network call and no model:

1. The road distance is worked out from the straight-line distance. Short trips wind more than long ones, and a few crossings (the lagoon between Ikorodu
   and Lekki, the bridges to the Island) add more road than the map suggests. The factors were fitted to 990 pairs of Lagos places on public road data.
2. The speed comes from a traffic profile by hour and weekday: slow in the morning and evening rush, slower on Friday evening, freer on Sunday morning.
3. The answer is a range, for example "an hour to an hour and a half", because one figure would claim more than any estimate of Lagos traffic can know.

These figures are for planning a visit. In an emergency Talk always says the emergency number first, and it never tells a caller how to travel.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import data

ROAD_BASE, ROAD_EXTRA, ROAD_OFFSET = 1.20, 2.6, 0.5
# Some parts of Lagos are further apart by road than by air: the zones are the mainland (M), the north (N), the Island (I), Lekki (L), Ikorodu (K),
# Epe (E) and the west (W).
ZONES = {"Surulere": "M", "Yaba": "M", "Ikeja": "N", "Maryland": "M", "Gbagada": "M", "Ojota": "M", "Mushin": "M", "Oshodi": "M", "Agege": "N",
         "Alimosho": "N", "Apapa": "M", "Festac": "W", "Ebute Metta": "M", "Lagos Island": "I", "Victoria Island": "I", "Ikoyi": "I", "Lekki": "L",
         "Ajah": "L", "Ikorodu": "K", "Badagry": "W", "Epe": "E"}
ZONE_BUMP = {("K", "L"): 2.1, ("I", "K"): 1.3, ("E", "K"): 1.2}
ACCESS = {"car": 4, "bus": 6, "bike": 3}        # minutes to find a ride before the trip starts
BUS_WAIT = 10
SPEED_FACTOR = {"car": 1.0, "bus": 0.85, "bike": 1.0}
LOW, HIGH_BASE, HIGH_EXTRA = 0.15, 0.30, 0.15
# The usual speed on Lagos roads, in kilometres an hour, for each hour of the day. These are planning figures, not measurements.
WEEKDAY = [38] * 5 + [30, 20, 13, 12, 15, 19, 20, 20, 20, 19, 16, 12, 10, 10, 12, 17, 24, 30, 35]
FRIDAY = WEEKDAY[:12] + [18, 17, 16, 13, 10, 9, 9, 10, 14, 20, 26, 32]
SATURDAY = [38] * 6 + [28, 24, 22, 20, 20, 20, 18, 18, 18, 18, 18, 16, 16, 16, 20, 26, 32, 32]
SUNDAY = [38] * 6 + [30, 24, 24, 24, 26, 26, 26, 26, 26, 26, 26, 26, 20, 20, 24, 32, 32, 32]
PROFILES = {"weekday": WEEKDAY, "friday": FRIDAY, "saturday": SATURDAY, "sunday": SUNDAY}
EARLY = 15             # minutes before a visit that a patient is asked to arrive
SAFETY = 10            # minutes added to the slow end of the trip when Talk says when to leave
PREP = 5               # a caller needs at least this long to get ready before leaving
EARLIEST_LEAVE = 5 * 60   # nobody is asked to leave home before five in the morning


@dataclass(frozen=True)
class Trip:
    low: float
    middle: float
    high: float
    road_km: float


def _straight_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(x))


def _profile(t: datetime) -> list[int]:
    return PROFILES["friday" if t.weekday() == 4 else "saturday" if t.weekday() == 5 else "sunday" if t.weekday() == 6 else "weekday"]


def _speed(t: datetime) -> float:
    table, part = _profile(t), t.minute / 60
    following = table[t.hour + 1] if t.hour < 23 else _profile(t + timedelta(hours=1))[0]
    return table[t.hour] * (1 - part) + following * part


def _length_factor(road: float) -> float:
    return 0.80 if road < 3 else 0.85 if road < 6 else 0.93 if road < 10 else 1.0 if road < 20 else 1.1 if road < 40 else 1.2


def zone_of(area: str | None) -> str:
    return ZONES.get(area or "", "M")


def trip(area: str, lat: float, lon: float, place_area: str | None, depart: datetime, mode: str = "car") -> Trip | None:
    """The trip from the middle of the caller's area to a place, leaving at `depart`. None when the area is not one Talk knows."""
    origin = data.AREAS.get(area)
    if origin is None or lat is None or lon is None:
        return None
    straight = _straight_km((origin.lat, origin.lon), (lat, lon))
    road = straight * (ROAD_BASE + ROAD_EXTRA / (straight + ROAD_OFFSET)) * ZONE_BUMP.get(tuple(sorted((zone_of(area), zone_of(place_area)))), 1.0)

    def speed(t: datetime) -> float:
        v = _speed(t) * _length_factor(road) * SPEED_FACTOR.get(mode, 1.0)
        return v * (1.5 if _speed(t) < 20 else 1.25) if mode == "bike" else v

    first = road / speed(depart) * 60
    v = speed(depart + timedelta(minutes=first / 2))        # the traffic half way through the trip, which is what most of it meets
    driving = road / v * 60
    wait = BUS_WAIT if mode == "bus" else 0
    high = HIGH_BASE + HIGH_EXTRA * min(1, max(0, (20 - v) / 10))
    middle = ACCESS.get(mode, 4) + wait + driving
    return Trip(max(0.5 * middle, ACCESS.get(mode, 4) + wait + driving * (1 - LOW)), middle, ACCESS.get(mode, 4) + wait + driving * (1 + high), road)


# ---- saying it -----------------------------------------------------------------------------------------------------

WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def say_duration(m: int) -> str:
    """25 minutes, an hour, an hour and a quarter, an hour and a half, an hour and 45 minutes, two hours."""
    if m < 60:
        return f"{m} minutes"
    h, rest = divmod(m, 60)
    unit = "an hour" if h == 1 else f"{WORDS.get(h, h)} hours"
    if rest == 0:
        return unit
    if rest == 30:
        return "an hour and a half" if h == 1 else f"{WORDS.get(h, h)} and a half hours"
    if rest == 15:
        return f"{unit} and a quarter"
    return f"{unit} and {rest} minutes"


def _step(high: float) -> int:
    return 5 if high <= 30 else 10 if high <= 60 else 15 if high <= 180 else 30


def _round(x: float, step: int) -> int:
    return int(math.floor(x / step + 0.5) * step)


def say_span(t: Trip) -> str:
    """The trip as it is spoken: "about 20 minutes", "30 to 40 minutes" or "an hour to an hour and a half". A narrow range is said as one figure."""
    step = _step(t.high)
    low, high = max(step, _round(t.low, step)), max(step, _round(t.high, step))
    if high - low <= max(step, 0.3 * t.middle):
        return "about " + say_duration(max(step, _round(t.middle, step)))
    if low < 60 <= high:
        return f"{low} minutes to {say_duration(high)}"
    if high < 60:
        return f"{low} to {high} minutes"
    return f"{say_duration(low)} to {say_duration(high)}"


def away_phrase(t: Trip) -> str:
    """The words that follow a place's name: "about 20 minutes away by road with the usual traffic at this hour"."""
    return f"{say_span(t)} away by road with the usual traffic at this hour"


# ---- planning a visit ----------------------------------------------------------------------------------------------

def leave_by(area: str, lat: float, lon: float, place_area: str | None, slot: datetime, now: datetime) -> tuple[datetime, Trip, bool] | None:
    """When the caller should leave to arrive EARLY minutes before `slot`, allowing for the slow end of the trip and a margin. The flag says whether that time
    is still ahead of the caller (with time to get ready) and not in the middle of the night. None when the trip cannot be worked out."""
    arrive_by = slot - timedelta(minutes=EARLY)
    depart, found = arrive_by - timedelta(minutes=30), None
    for _ in range(3):      # the traffic depends on when the caller leaves, and when they leave depends on the traffic: three rounds settle it
        found = trip(area, lat, lon, place_area, depart)
        if found is None:
            return None
        depart = arrive_by - timedelta(minutes=found.high + SAFETY)
    depart = depart.replace(second=0, microsecond=0)
    depart -= timedelta(minutes=depart.minute % 5)
    return depart, found, depart >= now + timedelta(minutes=PREP) and depart.hour * 60 + depart.minute >= EARLIEST_LEAVE
