# Talk: Helping you access essential services, from the phone people already have.

[![tests](https://github.com/YakubuYinusaT/Talk-for-Meta/actions/workflows/tests.yml/badge.svg)](https://github.com/YakubuYinusaT/Talk-for-Meta/actions/workflows/tests.yml)

Healthcare, emergency help and public information increasingly assume that a person has a smartphone, a reliable internet connection and the ability to use a screen. Millions of people have none of these. Talk turns the telephone number a person already uses into a way to reach essential services. They call, they say what they need, and Talk moves the request into action, without an app, a data plan or a smartphone.

Talk was built by Connected Intelligence for the Meta Global AI Developer Hackathon, in the Indie track. Talk is the product. Sofa is the agent underneath it that understands each request, keeps the context of the call, retrieves the right information and coordinates the institutions and the people involved. Sofa runs on Meta's models: Muse Voice Transcribe hears the caller, and Muse Spark 1.3 understands what they mean.

## The problem we are solving

In Nigerian community healthcare, many facilities still run on paper records and handwritten registers. Patients often travel to a hospital just to book an appointment, to ask a question or to follow up on their care, and some facilities have no computer at all. Information is scattered, patients find it hard to reach care, and health workers carry a heavy administrative load. People with disabilities, older people, people with limited literacy and patients whose condition makes screens hard to use are affected most. Having a telephone does not mean having the information, the people or the services you need at a critical moment.

## A call from start to finish

This is a typical conversation with Talk, word for word as it runs today against the simulated providers. The waiting times and fees in it are examples, because every provider reports its own queue at the moment of the call, and the trip times depend on the hour.

> **Caller:** Please help me find the nearest clinic for antenatal care.
>
> **Talk:** Certainly. Could you please tell me which area of Lagos you are in?
>
> **Caller:** I am in Surulere.
>
> **Talk:** I found three places near Surulere for antenatal care. The first is Surulere Care Clinic, a private clinic, about 10 minutes away by road with the usual traffic at this hour, with about 40 minutes of waiting and a consultation fee of 8,000 naira. The second is Aguda Community Health Centre, a state primary health centre, about 10 minutes away by road with the usual traffic at this hour, with about 100 minutes of waiting and a consultation fee of 500 naira. The third is Yaba Mainland Health Centre, a state primary health centre, about 20 minutes away by road with the usual traffic at this hour, with about 65 minutes of waiting and a consultation fee of 500 naira. Would you like me to book an appointment at one of them for you?
>
> **Caller:** Yes, please book the private clinic.
>
> **Talk:** Which day and time would you like at Surulere Care Clinic, please? For example, tomorrow morning.
>
> **Caller:** Tomorrow morning, please.
>
> **Talk:** I can book you at Surulere Care Clinic tomorrow at 8 in the morning. The trip from Surulere takes 10 to 20 minutes with the usual traffic, so please plan to leave by 7:15 in the morning. Would you like me to book it for you?
>
> **Caller:** Yes, please go ahead.
>
> **Talk:** Your appointment is confirmed at Surulere Care Clinic tomorrow at 8 in the morning. Your booking code is H 7 L E. Please arrive 15 minutes early. A text message with these details is on its way to you. Is there anything else I can help with?

Callers speak the way people do on the telephone, in several turns, and Talk asks only for what it does not yet know. When an answer does not fit a simple rule, such as "When is the next available slot?" in reply to the question about a time, Muse Spark reads it with Talk's question in view, so the caller is understood and not asked again. Other things callers say are "Hello, do you have amoxicillin in stock, please?", "Please can you cancel my appointment for tomorrow?" and "Please, my brother is not breathing, we are in Ikeja." The last one is an emergency, so Talk gives the emergency number, 112, first.

## What Talk does in healthcare today

Talk coordinates appointments and enquiries. A caller can ask for the nearest clinic, hospital or pharmacy and hear its waiting time and fee, book or cancel a visit, and find out whether a medicine is in stock. Today this works against four simulated provider systems.

Talk finds out where the caller is before it says how long anything will take. It asks for the caller's area, or takes it when the caller says "I am in Surulere" or "I will be coming from Ikorodu", and it never takes a clinic's name as the caller's place. The trip to each place is then worked out from that area with the usual Lagos traffic at that hour, said as a range, and places are ordered by that trip. A visit the caller could not reach in time is never offered, and when Talk offers a visit, it says when to leave. Until the caller has said where they are, Talk speaks no distance at all.

Talk gives approved information. A caller's basic question is answered only from the facility's own patient guide, and a warning sign is always answered first, exactly as the facility wrote it. The only fixed guide is a sample one for the simulated cancer centre, and every hospital that a visitor makes in the onboarding wizard brings a guide of its own.

Talk manages follow-up. It sends a reminder the day before a visit, a text when the hospital's staff confirm a visit, a thank-you to the patient who came, and an offer to rebook to the patient who did not. It also texts the care team's replies back to the caller.

Talk routes requests to the right people. A booking goes to the provider the caller chose, and a question the guide cannot answer goes to that facility's staff, who see it in the request inbox on their own front desk.

Talk escalates what needs a person, and above all an emergency. On every turn, Muse Spark reads whether anyone may be in danger, by meaning and in the caller's own words, about the caller or about someone else. A fast keyword reading runs beneath it with no model at all, allows for the spelling of the speech recogniser, knows common ways of saying it in Pidgin and Yoruba, stays quiet on sentences such as "I am not bleeding", and can only raise what the model says, never lower it. When it might be an emergency, Talk gives the emergency number, 112, and asks whether someone is in danger right now. When it is one, Talk gives 112 first, asks where the caller is, names the nearest hospital that has a free emergency place by travel time, tells that hospital's front desk at once, and asks whether the caller reached 112. When they could not, Talk asks that hospital to keep an emergency place for them, and texts the address and a reference. A hospital that is full is passed over, and the caller is told why. Every connected hospital says how many emergency places it keeps for exactly this. Talk does not send an ambulance, and it says so plainly when asked. It does not replace a clinician, and clinical decisions stay with qualified people.

Talk speaks English today, because Meta's speech model does not yet hear Yoruba, Hausa, Igbo or Pidgin. Serving callers in those languages is the next step as soon as a model can hear them. The same design can also carry government services, public information and emergency coordination, once each of those institutions is connected the way a provider is today.

## Why we are starting with community healthcare

Two community hospitals have given us letters of intent to deploy Talk. While talking with them, we found that they lack even basic computing to organise their work, so adding AI alone would solve only part of the problem. Our deployment therefore has three parts. The first part is digital infrastructure, which means giving each facility the essential computers and internet connection it does not yet have. The second part is information organisation, which means helping the facility structure its existing information so that authorised staff and AI systems can work with it. The third part is AI-enabled coordination, which is Talk itself.

Healthcare workers and trained front-desk assistants stay at the centre of this model. Talk lightens their coordination work and shows them what patients are asking for. The code in this repository is the third part, together with the guided demonstration of how a hospital joins Talk. The first two parts are work done inside the facilities, not software. Until the hospitals are connected, this build runs against four simulated provider systems, which are state clinics, private clinics, a pharmacy chain and a cancer centre. They follow the same contract a real provider would use, but every place, queue, stock level and patient in them is made up.

## How judges can see it working

There are four ways to try Talk, and the home page at `/overview` offers them all.

- **Call it from your browser.** The Try it page at `/try` opens on Call. Press Start call, allow the microphone and speak to Sofa as a patient would. Each sentence ends when you pause, and it goes through the same speech recognition, front desk and voice as a phone call. The Chat tab beside it lets you type instead, and it has ready conversations, including the one above. Beside the conversation, the page shows, step by step, what Talk heard, what Muse Spark decided, how urgent it judged the call, which providers it asked, the trips it worked out, how long each answer took, and what it booked, filed or held.
- **Call it by phone.** The number to call is on the home page and on the Try it page. A second number serves callers outside Nigeria and reaches the same Talk.
- **Join a hospital to it.** The onboarding wizard at `/onboard` is described below.
- **Look at the providers.** The Providers page at `/overview/providers` leads to the front desk of each of the four providers, at `/synthetic/state-phc/`, `/synthetic/eko-care/`, `/synthetic/everwell/` and `/synthetic/onc-centre/`. A booking or an emergency place held from the Try it page appears there at once.

The How it works page at `/overview/technology` explains how a call is handled. The Live calls page at `/demo` lists recent calls with the same step-by-step trace. It is switched off unless `DEMO_PAGE_ENABLED=true` is set, because it is public, and it hides what callers said unless `DEMO_SHOW_CALLS=true` is also set.

### The hospital onboarding wizard

The wizard shows Talk working from end to end. It takes you through a hospital joining Talk in eight steps, and it ends when the first appointment has been booked by a person and confirmed by the hospital's staff. Nothing needs to be installed, and nobody needs to be called.

1. **Template.** You choose one of three ready hospitals: a community general hospital, a maternity centre or a children's clinic. Each is filled with made-up Lagos data that you may change.
2. **Profile.** You check the hospital's name, street, area, kind, owner, opening hours, fee, waiting time and services, and, for a hospital with an emergency department, how many emergency places it keeps.
3. **Setup.** You tick what the hospital needs so that it can take part, which is a computer for the front desk, an internet connection and a power back-up. You then name the front desk assistant, and the wizard gives that person a desk key.
4. **Records.** You set the opening hours for each day and the number of patients in each time slot, you may add a few sample visits, and you write the entries of the hospital's patient guide and its warning signs. A preview shows exactly what Talk would be allowed to say from what you wrote.
5. **Connect.** The wizard creates a signed connection with a secret that belongs to this hospital alone, and shows the secret in a masked control. The Test button then sends two real signed requests through the code that Talk uses on every call. A correctly signed question must be answered, and a question signed with a wrong secret must be refused.
6. **Go live.** Talk starts using the hospital at once, without a restart, you see what Talk reads from it, and you may already try the first questions of a conversation. You may give your own phone number, with a tick box for consent, so that the confirmation text is really sent to you. Without a number, no text is ever sent to a real phone.
7. **First visit.** A conversation written for your hospital is shown, and you send its sentences one at a time, or type your own, to book a visit as the patient would. The hospital's own front desk is shown beside it. The visit appears there, you confirm it as the hospital's staff, and a progress line moves from the patient booking, to the visit on the desk, to your confirmation, to the patient being texted.
8. **Summary.** You see when each step happened, the appointment and its status, the confirmation text exactly as it was written, and a replay of every turn of the conversation with the steps that Talk took.

A hospital made in the wizard is a real provider system, not a picture of one. It has its own secret, its own appointment book, its own emergency places and its own signed endpoint, built from the same parts as the four simulated providers. What is simulated is the data and the hospital itself: everything in it is made up, no personal details are accepted, and a hospital is removed 24 hours after it was made. A hospital is shown only to the visitor who made it, through a signed cookie that holds no personal data, and to the phone number that visitor gave with consent. The wizard switches off with `DEMO_ONBOARDING_ENABLED=false`, and then its pages answer 404.

## The hospital front desks

Every provider, and every hospital made in the wizard, has a front desk: the page its staff keep open all day. The page opens with the name of the place, its kind and four figures, which are the people waiting, the visits today (or, for a pharmacy, the medicines in stock), the open requests and the urgent requests.

A hospital with an emergency department shows its emergency places first, with how many are free, and every place held for a caller who could not reach 112, with its reference and when the hold ends. A hold lasts an hour, and asking twice for the same caller never takes two places. The request inbox comes next, with urgent requests at the top. Each request shows what the caller said, a short reference for the caller (never a phone number), how long ago it arrived and a box to reply. Below it is the appointment book, grouped by day, with each visit's time, kind and status. A pharmacy shows a table of its medicine stock, and a provider that has one shows its patient guide and warning signs. The last section lists the places, with their hours, queue and fee.

A front desk is read only until it is opened with the desk key, either as `?key=<the key>` in the address or in the key box on the page. The key of the four simulated providers is the value of `HOSPITAL_DESK_KEY`, and the key of a hospital made in the wizard is the one shown at step 3, which also opens it for the visitor who made it. With the key, the staff can confirm a booked visit, mark a visit attended or not attended, and reply to a request. The page refreshes itself every ten seconds while its Auto refresh box is ticked.

## How it works

```
caller ── phone network ──┬─ telephony provider in Nigeria ─┬─ callback path: record, then reply     (sofa/routes/voice.py)
                          │                                 └─ SIP trunk → Asterisk → streamed agent (sofa/sip)
                          └─ second provider, for callers abroad: callback path                  (sofa/routes/twilio.py)
visitor ── browser ── Try it: a call from the browser, or a chat                                 (sofa/routes/tryit.py)
                                                         │
                                       Muse Voice Transcribe  (hears what was said)
                                       Muse Spark 1.3         (urgency, what the caller wants, yes or no, as strict JSON)
                                       keyword floor          (danger read with no model; can only raise the level)
                                                         │
                                       Sofa health front desk (sofa/orchestrator/adapters/health.py)
                                       trips with Lagos traffic (sofa/health/travel.py)
                                                         │  signed requests, one secret per provider
                          ┌───────────────┬──────────────┼───────────────┬───────────────┐
                       state-phc       eko-care       everwell        onc-centre      hospitals made in
                     state clinics   private clinics   pharmacies   cancer centre     the onboarding wizard
                                                         │
                     each provider's front desk: emergency places, request inbox, appointment book, stock and guide
```

Talk holds no hospital records. Each provider runs its own system, returns structured facts over a signed connection, and Talk composes the wording that the caller hears.

Muse Voice Transcribe hears the caller, and Talk gives it the names of Lagos areas, clinics and medicines to listen for. Muse Spark 1.3 reads each turn once, by meaning, in a strict JSON format with prompt caching. That one reading gives the urgency of the call, the operation the caller wants and whether they answered Talk's question with a yes or a no, so judging urgency adds no extra model call. An answer that does not fit the format is asked for once more, saying why, within four seconds, before Talk falls back to its rules, and the counts are shown on `/health`. When an answer does not fit a rule, a second short reading says what the caller meant: the thing that was asked, the earliest free time, a yes, a no, or something else. The model only ever names an operation from a registered list, and a place, a time or a medicine only counts when it is made of the caller's own words. The full design is in `docs/design.md`.

A trip is worked out inside Talk, with no network call and no model. The road distance comes from the straight-line distance between the caller's area and the place, with extra road for the lagoon crossings, and the speed comes from a Lagos traffic profile by hour and weekday. The figures are for planning a visit, which is why Talk says them as a range.

A streamed call, handled in `sofa/sip`, hears the caller as they speak, replies one sentence at a time as soon as each is ready, and stops speaking when the caller interrupts. It shares its turn logic with the callback path.

The voice is a hosted Nigerian-accent English voice. Talk also has a voice that runs on the server itself, which is set with `PIPER_MODEL`, and it speaks whenever the hosted voice cannot be reached. A call from the browser plays the same voice.

## What we learned about Meta's models

We built Talk on Muse Voice Transcribe and Muse Spark, and we recorded every problem that we met, what we changed and what it did, in `docs/model_log.md`. We share the main findings here because we hope they help Meta improve these models for voice work and for callers like ours. Each finding says what we saw and what would help.

**Muse Voice Transcribe**

1. **No African languages yet.** The model does not hear Yoruba, Hausa, Igbo or Pidgin, which are the languages most of our callers speak at home. This is the largest single limit on who Talk can serve in Nigeria. What would help is support for these languages, together with a published error rate on Nigerian-accented English telephone audio, so that builders can plan for it.
2. **One long keyword fails the whole request.** A keyword of more than 30 characters made the API answer HTTP 400, so the transcription was lost, not only the keyword. What would help is to skip or shorten a keyword that is too long and return a warning, and to state the limits on length and number (we keep at most 150) in the documentation.
3. **Push-to-talk mode returned nothing for an uploaded recording.** The same recording was read correctly in endpointing mode. What would help is a clear statement in the documentation of which mode suits a finished recording, or an error instead of empty text.
4. **Telephone audio.** Calls arrive at 8 kHz, and we resample them to the 16 kHz the model expects. What would help is a model or a setting tuned for narrow-band telephone audio, which is how most people in our market will reach AI.

**Muse Spark**

5. **Optional fields are skipped.** In the strict JSON format, the model left out most fields that were optional, and it answered with an empty sentence when a sentence field was optional. We now make every field required and use null for "nothing was said". What would help is for the model to fill optional fields when it has an answer for them, or for the documentation to recommend required fields.
6. **Some standard JSON Schema keywords are refused.** The strict format rejected `title`, `default` and the length and size limits, so we remove them before sending a schema. What would help is to accept these keywords, or to ignore them with a warning, so that schemas made by common tools work unchanged.
7. **Padding until the token limit.** Muse Spark 1.2 with minimal reasoning padded its JSON with spaces until it ran out of tokens, because the limit also counts the model's own thinking. Muse Spark 1.3 with 800 tokens of extra room fixed it for us. What would help is a separate limit for the reply and for the reasoning, and a guard against whitespace padding in structured output.
8. **Rewording invents figures.** Asked to reword a sentence that carried a provider's facts, the model sometimes changed or added numbers. Talk now speaks every fact exactly as the provider gave it and lets the model word only the conversation around it. What would help is a way to mark parts of a prompt that must be kept exactly, so that a voice product can let the model sound natural without risking a wrong time or fee.
9. **Speed on a telephone line.** On the live service on 2 November, the one reading of a turn took between 1.4 and 4.6 seconds across four turns. On a telephone, every second of silence is felt. What would help is a low-latency setting for short structured answers, and streaming of structured output, so that an agent can act on the first fields while the rest arrive.

**What worked well.** The strict JSON format made it possible to let a model choose real actions safely, because it can only name an operation that exists. One flat choice of action, a dozen natural example sentences and prompt caching gave us reliable readings of yes and no answers and of tool choices. Reading urgency by meaning caught an emergency on the live service that no keyword list would have caught ("Something bit my leg in the bush and it is swelling up very fast").

## Our own next steps

1. Realtime transcription over Meta's WebSocket while the caller speaks, so that the words are ready when the caller stops. We expect it to save about 2.5 seconds on every turn.
2. A measurement of the streamed path and of the second telephone number on real calls, so that the timings are confirmed on real phone lines.
3. A longer reading of where the caller is, so that a description such as "my house is close to the big market in Ikorodu" is understood without a second question.
4. Languages beyond English, as soon as a speech model hears them.

## Privacy and data handling

A provider never receives a phone number. It receives a reference that is different for each provider, together with what the caller said, so that staff can answer. A hold on an emergency place carries the same reference and nothing more.

Talk tells a new caller, once and right after its first answer, that calls are recorded. Recordings are deleted after 30 days, which can be changed with `RECORDING_RETENTION_DAYS`. The call record keeps what was said as text, together with the bookings and requests. A call from the browser is not recorded at all: the speech is heard and then discarded.

A recording is downloaded only over https and only from the telephony providers' own hosts, which can be changed with `RECORDING_ALLOWED_HOSTS`. Text messages name a place by a discreet name and never by what is treated there. Texts go only to Nigerian numbers, so a caller from abroad is never told that a text is on its way.

When `CALLBACK_ALLOWED_NETWORKS` is set, a telephony callback is accepted only from the providers' own networks, as a second lock beside the secret in its address. The callback secret that ships with the code is never accepted on an https address, because Talk replaces it with a random one when it starts, and the callback stays shut until you set your own. A callback from the second telephony provider must also carry that provider's own signature when its token is set. The public Live calls page is off by default, and when it is on it shows only what happened, with phone numbers masked, unless `DEMO_SHOW_CALLS=true` is set. A conversation on the Try it page, typed or spoken, is never texted, because it uses a number that is reserved for these conversations.

Every hospital, pharmacy and patient in this build is simulated.

## Running it yourself

```bash
pip install -e ".[dev]"
python -m pytest
```

The tests run complete calls against the four simulated providers and the onboarding wizard, with stand-in models, so they need no key and no network. There are about 700 of them, the whole set takes about six minutes, and GitHub runs them on every push.

To try Talk on your own computer without a key, put the following lines in a file called `.env` in the project folder, and start Talk with `uvicorn sofa.main:create_app --factory --port 8000`. Then open `http://localhost:8000`. The stand-in models answer by simple rules, so the conversations are simpler than with Meta's models, the stand-in never judges a call urgent by meaning, and the voice is silent. A call from the browser then uses the browser's own voice. The four simulated providers are reached at the application's own address, so `HOSPITAL_BASE_URL` must name it.

```
LLM_URL=inprocess://mock
ASR_URL=inprocess://mock
TTS_PROVIDER=standin
SYNTHETIC_HOSPITAL=true
HOSPITAL_BASE_URL=http://127.0.0.1:8000/synthetic
```

The command `docker compose up --build` starts the same thing, together with the stand-in models as a separate service.

To serve Talk to callers, copy `.env.example` to `.env`. Every setting that Talk reads is listed there, with a sentence that explains it. These are the values that you must set.

```
SYNTHETIC_HOSPITAL=true
HOSPITAL_BASE_URL=https://<your public address>/synthetic
SERVICES_ENABLED=health
TALK_NUMBER=<the number callers dial>
LLM_PROVIDER=meta            LLM_URL=https://api.meta.ai   LLM_MODEL=muse-spark-1.3   LLM_API_KEY=<Meta Model API key>
ASR_URL=https://api.meta.ai
AT_CALLBACK_SECRET=<long random text>
HOSPITAL_SIGNING_SECRET=<long random text>
HOSPITAL_DESK_KEY=<long random text>
```

Then start Talk as before, and give your telephony provider the callback address `https://<your public address>/voice/inbound/<AT_CALLBACK_SECRET>`. The provider's call events go to `https://<your public address>/voice/events/<AT_CALLBACK_SECRET>`, and its text delivery reports go to `https://<your public address>/sms/delivery/<AT_CALLBACK_SECRET>`. Talk must run as one process, because the hospitals made in the wizard and the streamed-call agent keep their state in it.

For the second number, for callers outside Nigeria, set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TEST_NUMBER_INTERNATIONAL`. Point the number's voice webhook at `https://<your public address>/voice/twilio/inbound/<AT_CALLBACK_SECRET>` and its status callback at `https://<your public address>/voice/twilio/status/<AT_CALLBACK_SECRET>`, both with POST.

The scripts in `scripts/` are run with `python -m scripts.<name>` from the project folder.

- `meta_check` tests your Meta key and models without printing the key.
- `simulate_call` places a scripted or typed call through the real `/voice` routes. It needs `DEBUG_HEADERS=true` and a running Talk at the address in `HOSPITAL_BASE_URL`, because the providers are reached there.
- `health_followups` runs one pass of the reminders and follow-up texts by hand.
- `warm_cache` prepares the audio for every fixed phrase when Talk is deployed.
- `tts_check`, `voice_local_check`, `sms_check` and `latency_report` check the hosted voice, the voice on the server, the texts that were sent and where the time goes on a call.
- `sip_selftest` is run by `deploy/setup_sip.sh` to make a test call through Asterisk.

The files in `deploy/` set up a single server, with the application in `/opt/sofa-health`. The file `sofa-health.service` is an example systemd service, and `nginx-talk.conf` is an example web server site. The script `setup_sip.sh` sets up the SIP trunk with Asterisk, and `setup_voice.sh` installs the voice that runs on the server.

## Where things are

The folder `sofa/health` holds the four simulated provider systems, their front-desk pages, the patient guide, the emergency keyword floor (`floor.py`), the trip estimate (`travel.py`) and the follow-up job. The file `sofa/orchestrator/adapters/health.py` is the health front desk that asks the providers and runs the emergency help, and the rest of `sofa/orchestrator` holds the understanding step, the tool registry and the wording checks. The folder `sofa/onboarding` and the file `sofa/routes/onboard.py` hold the hospital onboarding wizard. The folder `sofa/sip` holds the streamed-call agent. The folder `sofa/clients` holds the Meta model clients and the voices, `sofa/routes/voice.py` holds the call routes, `sofa/routes/twilio.py` holds the routes of the second telephony provider, and `sofa/routes/tryit.py` holds the Try it page, with the call from the browser. The website lives in `sofa/web` and `sofa/routes`. The design is described in `docs/design.md`, and `docs/model_log.md` records every model problem we met, what we changed and what it did. The tests are in `tests/`, and the stand-in models that let them run offline are in `mocks/`.
