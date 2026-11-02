"""What the onboarding wizard offers a visitor, and how a visitor's choices are checked and turned into a hospital.

A visitor starts from one of three ready templates, each filled in with made-up but realistic Lagos data, and may change every part of it. Everything a visitor types is
checked here before it is kept: free text is cleaned and limited in length, a number must be a number in a sensible range, and anything that looks like a phone number or
an e-mail address is refused, because the hospitals in this demonstration hold made-up data only. The checked choices are then turned into the same Network and Facility
objects as the four simulated providers, so the new hospital is built from exactly the same parts.
"""

import re
from datetime import datetime

from ..health import data, knowledge
from ..health.store import QUEUE_SCALE

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MINUTES_PER_PATIENT = 6            # how long the made-up hospital takes for one patient: it turns a typical waiting time into the length of its queue
BUSY_HOUR = 1.3                   # how much longer the queue is at a busy hour of the morning than at an average one (store.HOUR_FACTOR): the typical waiting time a visitor gives is for such an hour
OFFSET = (0.0007, -0.0005)         # the hospital stands this close to the middle of its area, so that it is the nearest place to a caller who says they are in that area

# the services a hospital may offer, each by the exact name the providers and the model use, with the way a visitor would read it
SERVICES = (
    (data.GENERAL, "General consultation", "A doctor sees a patient who feels unwell."),
    (data.ANTENATAL, "Antenatal care", "Check-ups for a woman during her pregnancy."),
    (data.IMMUNISATION, "Child immunisation", "Vaccinations for babies and young children."),
    (data.MALARIA, "Malaria test", "A quick test for malaria, with the result the same day."),
    (data.FAMILY, "Family planning", "Advice and methods for planning a family."),
    (data.LAB, "Laboratory tests", "Blood and other tests, with results the next working day."),
    (data.EMERGENCY, "Emergency care", "An emergency department that receives people at any hour."),
)
SERVICE_NAMES = tuple(name for name, _, _ in SERVICES)
KINDS = ("general hospital", "clinic", "primary health centre", "maternity centre")
OWNERS = (("state", "A state hospital"), ("private", "A private hospital"))
ROLES = ("Front desk assistant", "Records officer", "Nurse in charge")
CHECKLIST = (
    ("computer", "A computer for the front desk", "The front desk needs one computer, or a tablet, to open the appointment book and the requests from callers. It does not need to be new or fast."),
    ("internet", "An internet connection", "Talk reaches the hospital over the internet, and the front desk page is opened in an ordinary web browser. A mobile data connection is enough."),
    ("power", "A power back-up", "Electricity can fail for hours in Lagos. A battery, an inverter or a generator keeps the computer and the router on, so that callers are never told that the hospital cannot be reached."),
)
HOURS = {
    "always": ("Every day, all day and night", {d: (0, 24) for d in range(7)}),
    "daytime": ("Every day, from 7 in the morning until 9 in the evening", {d: (7, 21) for d in range(7)}),
    "weekdays": ("Weekdays from 8 in the morning until 6 in the evening, and Saturday from 9 until 3", dict(data.CLINIC_HOURS)),
    "public": ("Weekdays from 8 in the morning until 4 in the afternoon, and Saturday from 9 until 1", dict(data.PHC_HOURS)),
}
CAPACITIES = (1, 2, 3, 4)
MAX_GUIDE_ENTRIES = 6
FIELD_LIMITS = {"name": 70, "address": 70, "assistant": 50, "title": 80, "answer": 420, "warning": 420}

ID_PATTERN = re.compile(r"\d{6,}|\b\d[\d\s\-]{7,}\d\b")             # a run of digits long enough to be a phone number or an identity number
MAIL_PATTERN = re.compile(r"[^\s@]+@[^\s@]+")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,'&()\-]*$")


class Invalid(ValueError):
    """What a visitor entered cannot be used. The message is a full, polite sentence that is shown beside the field."""


def clean(value, label: str, limit: int, minimum: int = 0, plain: bool = False) -> str:
    """Text from a form, made safe to keep and to show. Control characters are dropped, white space is made single, the length is limited, and nothing that looks like a phone
    number, an identity number or an e-mail address is accepted. `plain` also limits the characters to those a name needs."""
    text = " ".join(CONTROL.sub(" ", str(value or "")).split())
    if len(text) > limit:
        raise Invalid(f"Please keep {label} to {limit} characters or fewer. It is {len(text)} characters now.")
    if len(text) < minimum:
        raise Invalid(f"Please write {label}. It needs at least {minimum} characters." if minimum > 1 else f"Please write {label}.")
    if text and (ID_PATTERN.search(text) or MAIL_PATTERN.search(text)):
        raise Invalid(f"Please do not put a phone number, an identity number or an e-mail address in {label}. Everything in this demonstration is made up, and no personal details are kept.")
    if plain and text and not NAME_PATTERN.match(text):
        raise Invalid(f"Please use only letters, numbers, spaces and the marks . , ' & ( ) - in {label}.")
    return text


def number(value, label: str, low: int, high: int) -> int:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        raise Invalid(f"Please write {label} as a whole number, for example {low if low else 10}.") from None
    if not low <= n <= high:
        raise Invalid(f"Please write {label} as a number from {low} to {high}.")
    return n


# ---- the three ready templates ------------------------------------------------------------------------------------------

URGENT_KEYWORDS = "urgent emergency warning danger bleeding fever breathing fit collapsed sign signs"


def entry(title: str, answer: str, keywords: str = "") -> dict:
    return {"title": title, "answer": answer, "keywords": keywords}


TEMPLATES = {
    "general": {
        "title": "Community general hospital",
        "blurb": "A busy state hospital with an outpatient clinic, an antenatal clinic and an emergency department that never closes. The fee is low and the waiting time is long, as in many public hospitals.",
        "accent": "green", "profile": "state-phc",
        "name": "Olive Branch Community General Hospital", "area": "Surulere", "owner": "state", "kind": "general hospital", "address": "Olive Branch Road",
        "fee": 1500, "wait": 55, "hours": "always", "capacity": 3,
        "services": [data.GENERAL, data.ANTENATAL, data.IMMUNISATION, data.MALARIA, data.LAB, data.EMERGENCY],
        "assistant": {"name": "Ngozi Adeyemi", "role": "Front desk assistant"},
        "guide": [
            entry("What to bring to your first visit", "Please bring a photo identity card if you have one, any earlier test results, and the medicines you are taking. If you already have a hospital card from us, please bring it as well. Please arrive 15 minutes before your appointment so that the records desk can register you.", "first visit new patient bring documents card register"),
            entry("How appointments work", "Appointments are given in half-hour slots, and the clinic sees a few patients in each slot. Please arrive on time. If you cannot come, please call to cancel, so that someone else can use your slot.", "appointment time slot queue wait book booking arrive late cancel"),
            entry("Where to pay", "Consultation fees are paid at the cashier's desk next to the records desk, before you see the doctor. The cashier can also explain what the laboratory and the pharmacy charge.", "pay payment fee fees cost price cashier money"),
            entry("Visiting a patient on the ward", "Visitors are welcome on the wards between 4 and 6 in the evening. Please wash your hands at the entrance and keep your visit short, so that patients can rest.", "visit visiting visitor ward admitted relative"),
            entry("Collecting your test results", "Laboratory results are ready the next working day. Please bring your hospital card to the laboratory desk to collect them, or ask the doctor to explain them at your next visit.", "results test laboratory lab collect report"),
        ],
        "warning": "Please come to our emergency department straight away, or call 112, if you have trouble breathing, chest pain, heavy bleeding or a fit, or if someone has collapsed. The emergency department is open day and night.",
    },
    "maternity": {
        "title": "Maternity centre",
        "blurb": "A private centre for pregnant women and new mothers, with antenatal clinics, baby immunisation and a short waiting time. The fee is higher, and every woman is seen by a midwife.",
        "accent": "purple", "profile": "onc-centre",
        "name": "Bright Beginnings Maternity Centre", "area": "Yaba", "owner": "private", "kind": "maternity centre", "address": "Magnolia Close",
        "fee": 6000, "wait": 20, "hours": "always", "capacity": 2,
        "services": [data.ANTENATAL, data.IMMUNISATION, data.FAMILY, data.LAB, data.GENERAL],
        "assistant": {"name": "Folake Ogunleye", "role": "Nurse in charge"},
        "guide": [
            entry("What to bring to your first antenatal visit", "Please bring your hospital card if you have one, any scan or test results from this pregnancy, and a list of the medicines you are taking. The first visit takes about an hour, because the midwife will ask about your health and your earlier pregnancies.", "first visit antenatal bring card scan results history"),
            entry("How often you will be seen", "Most women are seen every four weeks at first, and more often towards the end of the pregnancy. Your midwife will tell you when to come back, and the front desk will book that visit before you leave.", "often schedule visits weeks how many times come back"),
            entry("Baby immunisation days", "Babies are vaccinated at the centre on Tuesdays and Thursdays. Please bring your baby's immunisation card to every visit, so that the nurse can update it.", "baby immunisation vaccine vaccination jabs card days"),
            entry("Bringing someone with you", "You are welcome to bring your husband, a relative or a friend to your visits. They can wait with you and help you remember what the midwife says.", "bring someone husband family friend relative company accompany"),
            entry("Paying for your care", "You pay the consultation fee at the front desk. The desk can explain the cost of a scan and of the delivery packages before you decide on anything.", "pay payment fee fees cost price scan delivery package"),
        ],
        "warning": "Please come to the centre straight away, or call 112, if you have heavy bleeding, a severe headache with blurred sight, a fit, early leaking of your waters, or if your baby moves much less than usual.",
    },
    "children": {
        "title": "Children's clinic",
        "blurb": "A private clinic for babies and children, with vaccinations, malaria tests and general consultations. The waiting time is short, and a nurse sees every child first.",
        "accent": "blue", "profile": "eko-care",
        "name": "Little Stars Children's Clinic", "area": "Ikeja", "owner": "private", "kind": "clinic", "address": "Sunrise Avenue",
        "fee": 7000, "wait": 15, "hours": "always", "capacity": 2,
        "services": [data.GENERAL, data.IMMUNISATION, data.MALARIA, data.LAB],
        "assistant": {"name": "Tunde Okafor", "role": "Front desk assistant"},
        "guide": [
            entry("What to bring when your child is unwell", "Please bring your child's immunisation card and, if you have them, any medicines or test results from another clinic. The nurse will weigh your child and take a temperature before you see the doctor.", "bring unwell sick child card medicines results nurse weigh"),
            entry("Vaccination visits", "Vaccination visits are quick. The nurse will update your child's card, so please bring it to every visit so that no vaccine is missed.", "vaccination vaccine immunisation jabs card visit"),
            entry("How long you will wait", "A nurse sees every child first, and the doctor sees the most unwell children before the others. On most days the wait is about 15 minutes.", "wait waiting queue long time how long"),
            entry("Fees and payment", "The consultation fee is paid at the front desk. A vaccine, a malaria test or a laboratory test is charged separately, and the desk will tell you the price before anything is done.", "fee fees pay payment cost price money vaccine test"),
            entry("Bringing other children", "You may bring your other children, but please bring another adult to look after them while you are with the doctor.", "bring other children brother sister siblings adult"),
        ],
        "warning": "Please bring your child to us straight away, or call 112, if your child is struggling to breathe, has a fit, cannot be woken, or has a very high temperature that does not come down.",
    },
}


def new_profile(template: str) -> dict:
    """The made-up starting point for a hospital: everything in the template, ready to be edited step by step."""
    t = TEMPLATES[template]
    return {
        "name": t["name"], "area": t["area"], "owner": t["owner"], "kind": t["kind"], "address": t["address"], "fee": t["fee"], "wait": t["wait"],
        "hours_preset": t["hours"], "services": list(t["services"]), "capacity": t["capacity"],
        "schedule": [list(span) if span else None for span in (HOURS[t["hours"]][1].get(d) for d in range(7))],
        "checklist": {key: False for key, _, _ in CHECKLIST},
        "assistant": None, "assistant_suggestion": dict(t["assistant"]),
        "samples": True, "guide": [dict(e) for e in t["guide"]], "warning": t["warning"],
        "connection": None, "events": {},
    }


# ---- checking what a visitor entered ------------------------------------------------------------------------------------


def read_profile_form(form, profile: dict) -> tuple[dict, dict]:
    """Step 2. Returns the profile with the new values, and the problems found as {field: sentence}. A problem leaves that field as it was."""
    problems: dict[str, str] = {}
    out = dict(profile)

    def take(field, check):
        try:
            out[field] = check()
        except Invalid as exc:
            problems[field] = str(exc)

    take("name", lambda: clean(form.get("name"), "the name of the hospital", FIELD_LIMITS["name"], 3, plain=True))
    take("address", lambda: clean(form.get("address"), "the street", FIELD_LIMITS["address"], 3, plain=True))
    area = str(form.get("area") or "")
    if area in data.AREAS:
        out["area"] = area
    else:
        problems["area"] = "Please choose the area of Lagos where the hospital stands, from the list."
    owner = str(form.get("owner") or "")
    if owner in dict(OWNERS):
        out["owner"] = owner
    else:
        problems["owner"] = "Please say whether the hospital is a state hospital or a private hospital."
    kind = str(form.get("kind") or "")
    if kind in KINDS:
        out["kind"] = kind
    else:
        problems["kind"] = "Please choose what kind of place the hospital is, from the list."
    take("fee", lambda: number(form.get("fee"), "the consultation fee in naira", 0, 100000))
    take("wait", lambda: number(form.get("wait"), "the typical waiting time in minutes", 0, 240))
    chosen = [s for s in form.getlist("services") if s in SERVICE_NAMES]
    if chosen:
        out["services"] = [s for s in SERVICE_NAMES if s in chosen]
    else:
        problems["services"] = "Please tick at least one service, so that Talk knows what the hospital can be asked for."
    preset = str(form.get("hours") or "")
    if preset in HOURS:
        if preset != profile.get("hours_preset"):
            out["hours_preset"] = preset
            out["schedule"] = [list(span) if span else None for span in (HOURS[preset][1].get(d) for d in range(7))]
    elif preset != "custom":
        problems["hours"] = "Please choose when the hospital is open, from the list."
    return out, problems


def read_checklist_form(form, profile: dict) -> tuple[dict, dict]:
    """Step 3. Every item must be ticked, as it would have to be before a real hospital could go live; the assistant needs a name and a role."""
    problems: dict[str, str] = {}
    out = dict(profile)
    out["checklist"] = {key: form.get(f"check_{key}") == "on" for key, _, _ in CHECKLIST}
    if not all(out["checklist"].values()):
        problems["checklist"] = "Please tick all three items. A real hospital needs each of them before it can take calls from Talk."
    role = str(form.get("role") or "")
    try:
        name = clean(form.get("assistant_name"), "the assistant's name", FIELD_LIMITS["assistant"], 2, plain=True)
    except Invalid as exc:
        name = ""
        problems["assistant_name"] = str(exc)
    if role not in ROLES:
        problems["role"] = "Please choose the assistant's role, from the list."
    if not problems:
        out["assistant"] = {"name": name, "role": role}
    return out, problems


def read_information_form(form, profile: dict) -> tuple[dict, dict]:
    """Step 4. The weekly schedule, the number of patients in a slot, the patient guide and its warning signs."""
    problems: dict[str, str] = {}
    out = dict(profile)
    schedule = []
    for day in range(7):
        if form.get(f"closed_{day}") == "on":
            schedule.append(None)
            continue
        try:
            opens, closes = number(form.get(f"open_{day}"), f"the opening hour on {WEEKDAYS[day]}", 0, 23), number(form.get(f"close_{day}"), f"the closing hour on {WEEKDAYS[day]}", 1, 24)
        except Invalid as exc:
            problems["schedule"] = str(exc)
            schedule.append(profile["schedule"][day])
            continue
        if closes <= opens:
            problems["schedule"] = f"On {WEEKDAYS[day]} the hospital must close after it opens. Please check the hours."
        schedule.append([opens, closes])
    if not any(schedule):
        problems["schedule"] = "Please leave at least one day open, otherwise nobody can be given an appointment."
    out["schedule"] = schedule
    if schedule != [list(span) if span else None for span in (HOURS.get(profile.get("hours_preset"), ("", {}))[1].get(d) for d in range(7))]:
        out["hours_preset"] = "custom"
    try:
        out["capacity"] = number(form.get("capacity"), "the number of patients in a slot", 1, 4)
    except Invalid as exc:
        problems["capacity"] = str(exc)
    out["samples"] = form.get("samples") == "on"
    entries = []
    for i in range(MAX_GUIDE_ENTRIES):
        title, answer = " ".join(str(form.get(f"title_{i}") or "").split()), " ".join(str(form.get(f"answer_{i}") or "").split())
        if not title and not answer:
            continue
        try:
            entries.append({"title": clean(title, "the title of the entry", FIELD_LIMITS["title"], 3), "answer": clean(answer, "the answer of the entry", FIELD_LIMITS["answer"], 10),
                            "keywords": clean(form.get(f"keywords_{i}"), "the keywords", 300)})
        except Invalid as exc:
            problems[f"guide_{i}"] = str(exc)
            entries.append({"title": title[:FIELD_LIMITS["title"]], "answer": answer[:FIELD_LIMITS["answer"]], "keywords": ""})
    if not entries:
        problems["guide"] = "Please write at least one entry in the patient guide, so that Talk has something to answer from."
    out["guide"] = entries
    try:
        out["warning"] = clean(form.get("warning"), "the warning signs", FIELD_LIMITS["warning"], 10)
    except Invalid as exc:
        problems["warning"] = str(exc)
    return out, problems


# ---- turning the choices into a hospital ----------------------------------------------------------------------------------


def facility_of(profile: dict, slug: str) -> data.Facility:
    hours = {day: (span[0], span[1]) for day, span in enumerate(profile["schedule"]) if span}
    services = tuple(profile["services"])
    return data.Facility(
        id=slug, name=profile["name"], kind=profile["kind"], area=profile["area"], address=profile["address"], offset=OFFSET, services=services, hours=hours,
        emergency=data.EMERGENCY in services, booking=True, base_queue=max(1, round(profile["wait"] / (MINUTES_PER_PATIENT * QUEUE_SCALE * BUSY_HOUR))) if profile["wait"] else 0,
        minutes=MINUTES_PER_PATIENT, fee=profile["fee"], capacity=profile["capacity"], specialist=False, sms_name=profile["name"])


def guide_of(profile: dict) -> tuple:
    """The hospital's patient guide as the provider holds it: the visitor's entries, then the warning signs under the id that Talk always speaks exactly as written."""
    entries = []
    for i, e in enumerate(profile["guide"]):
        entries.append(knowledge.Entry(f"entry-{i + 1}", e["title"], f"{e['title']} {e.get('keywords') or ''}".strip(), e["answer"]))
    entries.append(knowledge.Entry(knowledge.URGENT_ENTRY, "When to contact the hospital urgently", URGENT_KEYWORDS, profile["warning"]))
    return tuple(entries)


def network_of(profile: dict, slug: str, template: str) -> data.Network:
    return data.Network(slug=slug, name=profile["name"], owner=profile["owner"], facilities=(facility_of(profile, slug),), guide=guide_of(profile),
                        guide_source="Patient guide (written in the onboarding demo)", profile=TEMPLATES[template]["profile"], demo=True)


# ---- what Talk will be allowed to say, worked out by the same code that Talk uses ---------------------------------------------------------


def question_from(title: str) -> str:
    """A caller's question that a guide entry answers, made from the entry's title: "How appointments work" becomes "Could you tell me about how appointments work, please?"."""
    t = title.strip().rstrip(".?!")
    return f"Could you tell me about {t[:1].lower() + t[1:]}, please?" if t else ""


def suggested_conversation(profile: dict, lines: int = 5) -> list[str]:
    """What a patient might say to find this hospital and book a visit, in the way people speak on the telephone. The first sentence matches one of the services the
    hospital offers, the second gives its area, and the last three choose the hospital by name, ask for a time and confirm."""
    services = profile["services"]
    opening = next((sentence for service, sentence in OPENINGS if service in services), OPENINGS[-1][1])
    short = profile["name"]
    script = [opening, f"I am in {profile['area']}.", f"Yes, please book {short}.", "Tomorrow morning, please.", "Yes, please go ahead."]
    return script[:lines]


OPENINGS = (
    (data.ANTENATAL, "Please help me find a clinic near me for antenatal care."),
    (data.IMMUNISATION, "Please help me find a clinic near me for my baby's vaccination."),
    (data.MALARIA, "Please help me find a clinic near me where I can have a malaria test."),
    (data.FAMILY, "Please help me find a clinic near me for family planning."),
    (data.LAB, "Please help me find a clinic near me for a blood test."),
    (data.GENERAL, "Please help me find a clinic near me, because I would like to see a doctor."),
    (data.EMERGENCY, "Please help me find a clinic near me where I can see a doctor."),
)


def clock_text(moment: datetime) -> str:
    return f"{moment:%A} {moment.day} {moment:%B}, {moment:%H:%M}"
