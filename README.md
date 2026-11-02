# Talk: Helping you access essential services, from the phone people already have.

Healthcare, emergency help and public information increasingly assume that a person has a smartphone, a reliable internet connection and the ability to use a screen. Millions of people have none of these. Talk turns the telephone number a person already uses into a way to reach essential services. They call, they say what they need, and Talk moves the request into action, without an app, a data plan or a smartphone.

Talk was built by Connected Intelligence for the Meta Global AI Developer Hackathon, in the Indie track. Talk is the product. Sofa is the agent underneath it that understands each request, keeps the context of the call, retrieves the right information and coordinates the institutions and the people involved.

## The problem we are solving

In Nigerian community healthcare, many facilities still run on paper records and handwritten registers. Patients often travel to a hospital just to book an appointment, to ask a question or to follow up on their care, and some facilities have no computer at all. Information is scattered, patients find it hard to reach care, and health workers carry a heavy administrative load. People with disabilities, older people, people with limited literacy and patients whose condition makes screens hard to use are affected most. Having a telephone does not mean having the information, the people or the services you need at a critical moment.

## A call from start to finish

This is a typical conversation with Talk, as it runs today against the simulated providers. The waiting times and fees in it are examples, because every provider reports its own queue at the moment of the call.

> **Caller:** Please help me find the nearest clinic for antenatal care.
>
> **Talk:** Certainly. Could you please tell me which area of Lagos you are in?
>
> **Caller:** I am in Surulere.
>
> **Talk:** I found three places near Surulere for antenatal care. The first is Surulere Care Clinic, a private clinic, with about 40 minutes of waiting and a consultation fee of 8,000 naira. The second is Aguda Community Health Centre, a state primary health centre, with about 100 minutes of waiting and a consultation fee of 500 naira. The third is Yaba Mainland Health Centre, a state primary health centre, with about 65 minutes of waiting and a consultation fee of 500 naira. Would you like me to book an appointment at one of them for you?
>
> **Caller:** Yes, please book the private clinic.
>
> **Talk:** Which day and time would you like at Surulere Care Clinic, please? For example, tomorrow morning.
>
> **Caller:** Tomorrow morning, please.
>
> **Talk:** I can book you at Surulere Care Clinic tomorrow at 8 in the morning. Would you like me to book it for you?
>
> **Caller:** Yes, please go ahead.
>
> **Talk:** Your appointment is confirmed at Surulere Care Clinic tomorrow at 8 in the morning. Your booking code is R G T J. Please arrive 15 minutes early. A text message with these details is on its way to you.

Callers speak the way people do on the telephone, in several turns, and Talk asks only for what it does not yet know. Other things callers say are "Hello, do you have amoxicillin in stock, please?", "Please can you cancel my appointment for tomorrow?" and "Please, my brother is not breathing, we are in Ikeja." The last one is an emergency, so Talk gives the emergency number, 112, first.

## What Talk does in healthcare today

Talk coordinates appointments and enquiries. A caller can ask for the nearest clinic, hospital or pharmacy and hear its waiting time and fee, book or cancel a visit, and find out whether a medicine is in stock. Today this works against four simulated provider systems.

Talk gives approved information. A caller's basic question is answered only from the facility's own patient guide, and a warning sign is always answered first, exactly as the facility wrote it. At the moment the only fixed guide is a sample one for the simulated cancer centre, and every hospital that a visitor makes in the onboarding wizard brings a guide of its own.

Talk manages follow-up. It sends a reminder the day before a visit, a text when the hospital's staff confirm a visit, a thank-you to the patient who came, and an offer to rebook to the patient who did not. It also texts the care team's replies back to the caller.

Talk routes requests to the right people. A booking goes to the provider the caller chose, and a question the guide cannot answer goes to that facility's staff, who see it in the request inbox on their own front desk.

Talk escalates what needs a person. Emergency words give the caller the emergency number, 112, straight away, and the nearest emergency care is told on its front desk, marked urgent, that someone described an emergency. Talk does not dispatch an ambulance, and it does not replace a clinician. Clinical decisions stay with qualified people.

Talk speaks English today, because Meta's speech model does not yet hear Yoruba, Hausa, Igbo or Pidgin. Serving callers in those languages is the next step as soon as a model can hear them. The same design can also carry government services, public information and emergency coordination, once each of those institutions is connected the way a provider is today.

## Why we are starting with community healthcare

Two community hospitals have given us letters of intent to deploy Talk. While talking with them, we found that they lack even basic computing to organise their work, so adding AI alone would solve only part of the problem. Our deployment therefore has three parts. The first part is digital infrastructure, which means giving each facility the essential computers and internet connection it does not yet have. The second part is information organisation, which means helping the facility structure its existing information so that authorised staff and AI systems can work with it. The third part is AI-enabled coordination, which is Talk itself.

Healthcare workers and trained front-desk assistants stay at the centre of this model. Talk lightens their coordination work and shows them what patients are asking for. The code in this repository is the third part, together with the guided demonstration of how a hospital joins Talk. The first two parts are work done inside the facilities, not software. Until the hospitals are connected, this build runs against four simulated provider systems, which are state clinics, private clinics, a pharmacy chain and a cancer centre. They follow the same contract a real provider would use, but every place, queue, stock level and patient in them is made up.

## How judges can see it working

The best way to see Talk work from end to end is the hospital onboarding wizard at `/onboard`. It takes you through a hospital joining Talk in eight steps, and it ends when the first appointment has been booked by a person and confirmed by the hospital's staff. Nothing needs to be installed, and nobody needs to be called.

1. **Template.** You choose one of three ready hospitals: a community general hospital, a maternity centre or a children's clinic. Each is filled with made-up Lagos data that you may change.
2. **Profile.** You check the hospital's name, street, area, kind, owner, opening hours, fee, waiting time and services.
3. **Setup.** You tick what the hospital needs so that it can take part, which is a computer for the front desk, an internet connection and a power back-up. You then name the front desk assistant, and the wizard gives that person a desk key.
4. **Records.** You set the opening hours for each day and the number of patients in each time slot, you may add a few sample visits, and you write the entries of the hospital's patient guide and its warning signs. A preview shows exactly what Talk would be allowed to say from what you wrote.
5. **Connect.** The wizard creates a signed connection with a secret that belongs to this hospital alone, and shows the secret in a masked control. The Test button then sends two real signed requests through the code that Talk uses on every call. A correctly signed question must be answered, and a question signed with a wrong secret must be refused.
6. **Go live.** Talk starts using the hospital at once, without a restart, you see what Talk reads from it, and you may already try the first questions of a conversation. You may give your own phone number, with a tick box for consent, so that the confirmation text is really sent to you. Without a number, no text is ever sent to a real phone.
7. **First visit.** A conversation written for your hospital is shown, and you send its sentences one at a time, or type your own, to book a visit as the patient would. The hospital's own front desk is shown beside it. The visit appears there, you confirm it as the hospital's staff, and a progress line moves from the patient booking, to the visit on the desk, to your confirmation, to the patient being texted.
8. **Summary.** You see when each step happened, the appointment and its status, the confirmation text exactly as it was written, and a replay of every turn of the conversation with the steps that Talk took.

A hospital made in the wizard is a real provider system, not a picture of one. It has its own secret, its own appointment book and its own signed endpoint, built from the same parts as the four simulated providers. What is simulated is the data and the hospital itself: everything in it is made up, no personal details are accepted, and a hospital is removed 24 hours after it was made. A hospital is shown only to the visitor who made it, through a signed cookie that holds no personal data, and to the phone number that visitor gave with consent. The wizard switches off with `DEMO_ONBOARDING_ENABLED=false`, and then its pages answer 404.

There are also other ways to try Talk. The home page at `/overview` offers them.

- You can call the number and speak to Talk, as a patient would.
- You can open the Try it page at `/try` and type a sentence. The page shows, step by step, what Talk heard, what Muse Spark decided, which providers it asked, how long each answer took, and what it booked or filed. A booking made there appears on the provider's own front desk. The page has ready conversations, including the one above.
- You can open the Providers page at `/overview/providers`, or go straight to the front desk of any of the four providers at `/synthetic/state-phc/`, `/synthetic/eko-care/`, `/synthetic/everwell/` and `/synthetic/onc-centre/`.
- You can read how a call is handled on the How it works page at `/overview/technology`.
- The Live calls page at `/demo` lists recent calls with the same step-by-step trace. It is switched off unless `DEMO_PAGE_ENABLED=true` is set, because it is public, and it hides what callers said unless `DEMO_SHOW_CALLS=true` is also set.

## The hospital front desks

Every provider, and every hospital made in the wizard, has a front desk: the page its staff keep open all day. The page opens with the name of the place, its kind and four figures, which are the people waiting, the visits today (or, for a pharmacy, the medicines in stock), the open requests and the urgent requests.

The request inbox comes first, with urgent requests at the top. Each request shows what the caller said, a short reference for the caller (never a phone number), how long ago it arrived and a box to reply. Below it is the appointment book, grouped by day, with each visit's time, kind and status. A pharmacy shows a table of its medicine stock, and a provider that has one shows its patient guide and warning signs. The last section lists the places, with their hours, queue and fee.

A front desk is read only until it is opened with the desk key, either as `?key=<the key>` in the address or in the key box on the page. The key of the four simulated providers is the value of `HOSPITAL_DESK_KEY`, and the key of a hospital made in the wizard is the one shown at step 3, which also opens it for the visitor who made it. With the key, the staff can confirm a booked visit, mark a visit attended or not attended, and reply to a request. The page refreshes itself every ten seconds while its Auto refresh box is ticked.

## How it works

```
caller ── phone network ── telephony provider ─┬─ callback path: record, then reply        (sofa/routes/voice.py)
                                               └─ SIP trunk → Asterisk → streamed agent    (sofa/sip)
                                                         │
                                       Muse Voice Transcribe  (hears what was said)
                                       Muse Spark 1.3         (decides what it means, as strict JSON)
                                                         │
                                       Sofa health front desk (sofa/orchestrator/adapters/health.py)
                                                         │  signed requests, one secret per provider
                          ┌───────────────┬──────────────┼───────────────┬───────────────┐
                       state-phc       eko-care       everwell        onc-centre      hospitals made in
                     state clinics   private clinics   pharmacies   cancer centre     the onboarding wizard
                                                         │
                          each provider's front desk: appointment book, request inbox, stock and guide
```

Talk holds no hospital records. Each provider runs its own system, returns structured facts over a signed connection, and Talk composes the wording that the caller hears.

Muse Voice Transcribe hears the caller, and Talk gives it the names of Lagos areas, clinics and medicines to listen for. Muse Spark 1.3 reads each request by meaning and picks among the options when simple rules cannot, using a strict JSON format and prompt caching. The model only ever names an operation from a registered list, and a place, a time or a medicine only counts when it is made of the caller's own words. The full design is in `docs/design.md`.

A streamed call, handled in `sofa/sip`, hears the caller as they speak, replies one sentence at a time as soon as each is ready, and stops speaking when the caller interrupts. It shares its turn logic with the callback path.

The voice is a hosted Nigerian-accent English voice. Talk can also use a voice that runs on the server itself, which is set with `PIPER_MODEL`, for the times when the hosted voice cannot be reached.

## Privacy and data handling

A provider never receives a phone number. It receives a reference that is different for each provider, together with what the caller said, so that staff can answer.

Talk tells a new caller, once and right after its first answer, that calls are recorded. Recordings are deleted after 30 days, which can be changed with `RECORDING_RETENTION_DAYS`. The call record keeps what was said as text, together with the bookings and requests.

A recording is downloaded only over https and only from the telephony provider's own hosts, which can be changed with `RECORDING_ALLOWED_HOSTS`. Text messages name a place by a discreet name and never by what is treated there.

The callback secret that ships with the code is never accepted on an https address, because Talk replaces it with a random one when it starts, and the callback stays shut until you set your own. The public Live calls page is off by default, and when it is on it shows only what happened, with phone numbers masked, unless `DEMO_SHOW_CALLS=true` is set. A conversation typed on the Try it page is never texted, because it uses a number that is reserved for typed conversations.

Every hospital, pharmacy and patient in this build is simulated.

## Running it yourself

```bash
pip install -e ".[dev]"
python -m pytest
```

The tests run complete calls against the four simulated providers and the onboarding wizard, with stand-in models, so they need no key and no network.

To try Talk on your own computer without a key, put the following lines in a file called `.env` in the project folder, and start Talk with `uvicorn sofa.main:create_app --factory --port 8000`. Then open `http://localhost:8000`. The stand-in models answer by simple rules, so the conversations are simpler than with Meta's models, and the voice is silent. The four simulated providers are reached at the application's own address, so `HOSPITAL_BASE_URL` must name it.

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

The scripts in `scripts/` are run with `python -m scripts.<name>` from the project folder.

- `meta_check` tests your Meta key and models without printing the key.
- `simulate_call` places a scripted or typed call through the real `/voice` routes. It needs `DEBUG_HEADERS=true` and a running Talk at the address in `HOSPITAL_BASE_URL`, because the providers are reached there.
- `health_followups` runs one pass of the reminders and follow-up texts by hand.
- `warm_cache` prepares the audio for every fixed phrase when Talk is deployed.
- `tts_check`, `voice_local_check`, `sms_check` and `latency_report` check the hosted voice, the voice on the server, the texts that were sent and where the time goes on a call.
- `sip_selftest` is run by `deploy/setup_sip.sh` to make a test call through Asterisk.

The files in `deploy/` set up a single server, with the application in `/opt/sofa-health`. The file `sofa-health.service` is an example systemd service, and `nginx-talk.conf` is an example web server site. The script `setup_sip.sh` sets up the SIP trunk with Asterisk, and `setup_voice.sh` installs the voice that runs on the server.

## Where things are

The folder `sofa/health` holds the four simulated provider systems, their front-desk pages, the patient guide and the follow-up job. The file `sofa/orchestrator/adapters/health.py` is the health front desk that asks the providers, and the rest of `sofa/orchestrator` holds the understanding step, the tool registry and the wording checks. The folder `sofa/onboarding` and the file `sofa/routes/onboard.py` hold the hospital onboarding wizard. The folder `sofa/sip` holds the streamed-call agent. The folder `sofa/clients` holds the Meta model clients and the voices, and `sofa/routes/voice.py` holds the call routes. The website lives in `sofa/web` and `sofa/routes`. The design is described in `docs/design.md`, and `docs/model_log.md` records every model problem we met, what we changed and what it did. The tests are in `tests/`, and the stand-in models that let them run offline are in `mocks/`.
