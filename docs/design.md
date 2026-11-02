# Talk: the design of healthcare coordination by phone call

Talk is a telephone number that gets people to care in Lagos. A person calls from any phone, says what they need, and Talk finds the right clinic, hospital or pharmacy, books or cancels a visit, checks whether a medicine is in stock, answers a basic question from the facility's own patient guide, and leaves a request for the facility's staff when a person is needed. This page explains the problem, how a call is handled, how Talk is put together, what is simulated, and what comes next. The agent that does the work is called Sofa, and Talk is the product around it.

## The problem

In many Nigerian community hospitals, records are kept on paper and in handwritten registers, and some facilities have no computer at all. A patient often has to travel to the hospital just to book a visit, to ask a question or to follow up on their care. Information is scattered, patients find it hard to reach care, and the staff carry a heavy administrative load. The people who are affected most are older people, people with disabilities, people with limited literacy and patients whose condition makes a screen hard to use. These people usually do have a telephone, but a telephone alone does not give them the information, the people or the services they need at a critical moment.

A phone call can fix that only if there is something behind the call to book into and someone to follow up. So Talk does not stop at understanding speech. It writes into the hospital's appointment book, it keeps a request queue that the staff can answer, and it follows up with the patients who were seen and with those who never came.

## The deployment has three parts

Two community hospitals have given us letters of intent to deploy Talk. While we spoke with them, we found that they lack even basic computing to organise their work, so adding artificial intelligence alone would solve only part of the problem. The deployment therefore has three parts.

1. **Digital infrastructure.** Each facility is given the essential computers and the internet connection that it does not yet have, together with a power back-up so that the front desk stays reachable.
2. **Information organisation.** The facility's existing information is structured, which means its opening hours, its services, its appointment book and its patient guide, so that authorised staff and AI systems can work with it.
3. **AI-enabled coordination.** This is Talk itself: the phone call, the understanding of the request and the coordination between the caller, the provider's system and the provider's staff.

Healthcare workers and trained front-desk assistants stay at the centre of this model, and clinical decisions stay with qualified people. This repository is the third part, together with a guided demonstration of how a hospital joins Talk. The first two parts are work done inside the facilities, and they are not software.

## The ways a conversation reaches Talk

There are three ways in, and all three share the same turn code, so a conversation behaves in the same way whichever way it arrives.

- **The callback path** (`sofa/routes/voice.py`). The caller dials the number. The telephony provider asks Talk what to play, records each thing the caller says, and posts the recording's address to Talk. Talk downloads the recording only over https and only from the provider's own hosts, converts it to 16 kHz mono sound, treats a very quiet recording as silence, and hands it to Muse Voice Transcribe. If the answer takes longer than two seconds, Talk plays a short holding message, and it plays another every six seconds, so that the caller never sits in silence. These times are the defaults, and they can be changed in the settings.
- **The streamed path** (`sofa/sip`). A SIP trunk delivers the call to Asterisk, which hands it to a streamed agent on the same machine. The agent hears the caller as they speak, decides when the caller has finished, speaks the reply one sentence at a time as soon as each sentence is ready, and stops speaking when the caller talks over it.
- **The browser path** (`sofa/routes/tryit.py`). A visitor calls Talk from the browser on the Try it page, or types to it there or in the onboarding wizard. A browser call records each sentence in the page, ends it when the visitor pauses, and sends it through the same speech recognition, front desk and voice as a phone call. A typed message leaves the speech step out. Nothing is sent to a real phone from this path.

## How one turn is handled

1. **Hearing.** Muse Voice Transcribe turns the caller's speech into text. Talk gives it the names of Lagos areas, clinics and medicines to listen for, so that a place such as Aguda or a medicine such as amoxicillin is recognised more often.
2. **Deciding.** The keyword floor reads the caller's words for danger first, with no model. Then Muse Spark 1.3 reads the whole call so far, both sides, and returns one strict JSON decision: the urgency, the one next step, and the details that step needs (where the caller is, the need, the place, the day and time, the medicine). When it gives no usable decision, the rules-based reading described under Understanding takes the turn.
3. **Acting.** The health front desk takes the step: it asks the provider systems for facts, using signed requests, and keeps the guard rails described under The model leads the call.
4. **Wording.** Every sentence comes from a stored phrase. For the conversation around the facts, such as a greeting or a polite question, Muse Spark may write a more natural sentence, but it is accepted only if it keeps every placeholder, invents no number and stays short. Every sentence of the health front desk carries a provider's own facts or a patient guide's own words, so those are always spoken exactly from their stored phrases.
5. **Speaking.** A voice speaks the sentence. The hosted voice is the first choice, and a voice on the server itself takes over when the hosted one is out of reach.
6. **Recording what happened.** Each turn keeps a trace of its steps, which are heard, understood, read, asked, booked, request filed and replied, each with the time it took. The trace holds what happened and never a phone number, a caller identifier or a secret.

## Orchestration

### The model leads the call

Each turn Muse Spark sees the whole call, both sides (the last 24 lines), the places on the table with their numbers, any booking or cancellation Talk has proposed, and the open question. It answers with a decision in a strict format whose choices are closed lists: the urgency (none, possible or emergency), one step from a fixed list (find_places, medicine, free_times, offer_booking, confirm_booking, cancel_booking, confirm_cancel, place_status, ask_care_team, reply, person, goodbye, other), an area from the areas Talk knows (a neighbourhood not on the list is mapped by the model to the nearest one), a need from the closed list, a place (an option number, a name Talk said, or the caller's words for a place), a day and time, a medicine, and a reply. The code in `sofa/orchestrator/adapters/health_agent.py` takes the step through the health front desk, so the provider calls, the wording and the follow-ups are the same as before.

The guard rails are in code. A reply the model writes is spoken only if every figure and every named place in it was already said in the call. A booking is made only from a proposal Talk made in the previous turn and the caller's yes; a model that jumps to confirming gets a proposal first. A cancellation needs the same. A day or a time counts only if it is made of the caller's own words, and an area only if it is on the list. The emergency floor runs before the model, and the model's urgency can raise the level but never lower it; once the emergency help has started, its own questions are answered by the rules. When the model's answer is missing, slow or outside the format, the rules answer the turn. `DIALOGUE_AGENT=false` gives every turn to the rules.

### Understanding (the rules-led path)

When the model gives no usable decision, or the model-led path is switched off, the turn is read as follows.

The model never supplies a fact. It only chooses what the caller wants, and its answer has two required fields: `action` and `answer`. The `action` is one of the registered tool names or one of `chat`, `human` and `unclear`. The `answer` says whether the caller answered the question that Talk had just asked with a yes or a no. Every field is required in the answer format, because a model that is allowed to skip fields skips most of them, and the choices are written into the format as a closed list, so the model cannot name an operation that does not exist. Anything that is not on the registry is treated as not understood before anything can act on it.

The prompt carries the registered tools, the question that Talk asked last, the request that is in progress and the last two things the caller said. It also carries a set of example sentences, which are written the way callers really speak, with words such as hello and please around the request. When Talk has just asked a question, a sentence such as "I am in Surulere." is read as the answer to it and not as a new request.

A second reading extracts the details of the request. A place, a time or a medicine counts only if it is made of the caller's own words, and the need must be one of a closed list. When the model does not answer, the rules and the follow-up questions carry on, and the caller loses nothing.

### The tool registry

The tool registry (`sofa/orchestrator/tools.py`) is the one list of things Talk is allowed to do for a caller. The health service registers seven tools: finding a facility, a facility's status, available slots, booking, cancelling, medicine availability and asking the centre's patient guide. A tool that is not registered cannot run, and a service that is switched off in `SERVICES_ENABLED` has no tools registered at all. This is how Talk stays a medium: the provider's system does the work and stays the source of truth.

### The health front desk

The health front desk (`sofa/orchestrator/adapters/health.py`) coordinates several independent provider systems for one caller. It asks every provider that could help at the same moment, puts the real options in front of the caller with the things that decide between them, which are distance, waiting time and fee, and asks which one the caller means. An area is not a hospital, so Talk never picks for the caller. Only then does it ask the chosen provider for a free time, read the time back, and book on a clear yes. Talk says that a visit is booked only when the provider's system has confirmed it, and if the time was taken a moment earlier, it offers the next one.

A caller who says the day or the time while answering another question, for example "Yes, please book the private clinic for tomorrow morning", is not asked for it again. A caller who is thinking, waiting or asking for more has agreed to nothing, however the model read the sentence. Each question is asked at most twice, and after that the caller is told how to try again. A caller who is not understood three times in a row is told that the clinic will follow up, and Talk records the unfinished request as a handoff so that the people who follow up can see why. Talk never hangs up because it failed to help. The one exception is a line that stays silent, which ends after two silent turns by default.

### The signed provider contract

Every provider system, simulated or made in the wizard, speaks the same contract, which is implemented on Talk's side in `sofa/health/links.py` and on the provider's side in `sofa/health/provider.py`.

- **The message.** Talk sends one signed JSON message to the provider's `/rpc` address. It names an operation, gives its arguments, and gives a context with the caller's reference, the call identifier and the service. The provider answers with a status, a sentence that Talk may use and a data object.
- **The signature.** The message carries a timestamp and the hexadecimal HMAC-SHA256 of the timestamp, a full stop and the body, made with a secret that only this provider and Talk hold. The provider refuses a signature that does not match, and it refuses a message whose timestamp is more than five minutes old, so that an old message cannot be sent again.
- **One secret for each provider.** A secret for each simulated provider is derived from `HOSPITAL_SIGNING_SECRET`, or from the callback secret when that is empty, together with the provider's name. A hospital made in the wizard gets a random secret of its own. A leaked secret therefore opens one provider and no other.
- **One reference for each provider.** The provider never receives a phone number. It receives a reference made by signing the number with that provider's own secret, so the same caller has a different reference at every provider, and the reference is no use to anyone who does not hold the secret.
- **The operations.** A provider answers eleven operations: search, slots, book, cancel, upcoming, stock, knowledge, confirm, visit status, request and request status. A provider that has no pharmacy or no guide answers with an empty result.
- **Failure.** A provider that does not answer within eight seconds is treated as unreachable, and the caller never loses the call over it. If no provider can be reached at all, Talk says so plainly, and a caller in an emergency still hears the emergency number first.

## The request queue and urgent escalation

Some things need a person. A question that the patient guide does not cover is never guessed at. Talk files it as a request with the facility's own front desk, tells the caller which care team has it, and promises a text message when the team replies. An emergency is filed as an urgent request with the nearest emergency care.

A request carries its kind, what the caller said and the caller's reference, and never a phone number. On the front desk the requests wait in an inbox, with urgent requests first and then the oldest. The staff reply in a box on the same page, and a reply can be answered only once. The follow-up job asks the provider about each open request, texts the reply to the caller once, and stops asking about a request that nobody answered after seven days.

An urgent request can also be texted to a member of staff. When `HOSPITAL_STAFF_PHONE` is set, a short message that gives the request's code and the place's name is sent to that number, and it asks the member of staff to open the front desk. Nothing about the caller or the emergency is put in that text.

## Safety limits

- **Talk does not dispatch an ambulance.** It gives the emergency number, 112, first and from any point in a call. Danger is recognised in two layers. Muse Spark reads urgency by meaning on every turn, in the same call that reads the request, so any phrasing counts, about the caller or someone else. Beneath it, a keyword floor (`sofa/health/floor.py`) runs first with no model, allows for the recogniser's spelling, and stays quiet on negations such as "I am not bleeding"; it can only raise the model's level, never lower it. A possible emergency gets 112 and one question. An emergency gets 112, a question about where the caller is, and the nearest hospital with a free emergency place by travel time, whose front desk is told at once. Talk then asks whether the caller reached 112, and when they did not, it asks that hospital to hold one of its emergency places (the signed operations `emergency` and `emergency_hold`; a hold is kept for an hour, and asking twice never takes two places) and texts the address and a reference. A hospital that is full is passed over, and the caller is told why. Every connected hospital says how many emergency places it keeps, and so does a hospital made in the onboarding wizard.
- **Talk gives no clinical advice beyond the facility's own guide.** A basic question is answered only from entries of the patient guide, never from the model's memory. A warning sign is answered first and exactly as the facility wrote it, without rewording. A question that the guide does not cover goes to the care team.
- **Talk does not diagnose or replace a clinician.** It coordinates care, and every clinical decision stays with qualified people.
- **The model supplies no facts.** Every place, time, fee, queue, stock level and booking code comes from a provider, and a sentence that the model words is accepted only if it makes up no number of its own.

## Privacy

- A provider never receives a phone number. It sees a reference that is different for each provider, together with what the caller said so that staff can answer.
- A text message names a place by a discreet name and never by what is treated there, and it says nothing about the patient's health.
- Talk tells a new caller, once and right after its first answer, that calls are recorded. A recording is deleted after `RECORDING_RETENTION_DAYS` days, which is 30 by default, and the call record keeps what was said as text, together with the bookings and requests.
- A recording is downloaded only over https from the telephony provider's own hosts, and every redirect is checked against the same list. An address in a callback can therefore not make the server fetch an internal page.
- Talk keeps the caller's number, what was said on the call and the booking details. The public Live calls page is off by default. When it is on, it shows counts and what happened with phone numbers masked, and it shows what callers said only when `DEMO_SHOW_CALLS` is switched on.
- The callback secret that is published with the code is replaced by a random one on an https address, so that nothing is guarded by a value that everyone knows.
- A conversation typed on the Try it page uses a number that is reserved for typed conversations, and no text message is ever sent to it.
- Every hospital, pharmacy and patient in this build is simulated.

## The simulated providers

Until the hospitals are connected, Talk runs against four independent simulated provider systems. Each has its own records, its own secret and its own signed connection, and they are reached in the same way that real providers will be. Every place, queue, stock level and patient in them is made up.

| Provider | What it is | What it offers |
|---|---|---|
| Lagos State Primary Health Network (`state-phc`) | A network of state health centres and general hospitals. | Low fees, longer queues and emergency departments. |
| Eko Care Private Clinics (`eko-care`) | A private clinic group. | Higher fees and shorter queues. |
| Everwell Pharmacies (`everwell`) | A pharmacy chain. | Medicines, their prices and their stock. |
| Oncology Care Centre Ikeja (`onc-centre`) | A specialist cancer centre that gives each patient a fixed time. | Cancer care, a sample patient guide, a record of who came and follow-up. |

Talk holds no hospital records. A provider answers a small set of signed requests and returns structured facts, and Talk composes the wording. A provider with no system of its own uses the appointment book that Talk keeps for it, and its front desk shows who is coming and marks who came. The boundary between Talk and a provider is the signed contract above, and a real hospital would replace a simulated one by answering the same eleven operations.

## The hospital front desks

Each provider has a front desk page at `/synthetic/<name>/`, and each hospital made in the wizard has one at its own address. It is the page that the staff keep open all day, and it is built only from the provider's own records, so it shows exactly what Talk reads when it speaks for that provider.

The page begins with four figures, which are the people waiting, the visits today (or the medicines in stock, for a pharmacy), the open requests and the urgent requests. Next comes the request inbox, with urgent requests first, then the appointment book grouped by day with each visit's time, kind and status, then a stock table for a pharmacy, the patient guide and warning signs where a provider has them, and the places with their hours, queue and fee. A visit that has passed and has not been marked is flagged as needing marking.

A front desk is read only until it is opened with the desk key, either in the address as `?key=<the key>` or in the key box on the page. With the key, the staff can confirm a booked visit, mark a visit attended or not attended, and reply to a request. Confirming a visit makes Talk text the patient, once, to say that the hospital has confirmed it. The page refreshes itself every ten seconds while its Auto refresh box is ticked, and it is never cached, because a desk that shows an old queue is worse than no desk.

## The hospital onboarding wizard

The wizard at `/onboard` is a guided demonstration of a hospital joining Talk, from the choice of a template to its first appointment, which is booked by a person and confirmed by the hospital's staff. It is described step by step in the README. In short, the eight steps are the template, the profile, the setup, the records, the connection, going live, the first visit and the summary.

A hospital made in the wizard is a real provider system running inside the process. It has its own secret, its own database file for its appointment book and its own web application that speaks the signed contract. When the visitor presses Go live, Talk is told about it at once, without a restart, and the health front desk finds it, searches it and books into it by the normal path. Nothing in Talk is written for any one hospital.

What is simulated is the data and the hospital itself. The three templates are filled with made-up Lagos data, and everything that a visitor types is cleaned and limited, and is refused if it looks like a phone number, an identity number or an e-mail address. The patient is a conversation typed in the browser. No text message goes to a real phone unless the visitor gave their own number and ticked the box that allows it.

The wizard keeps visitors apart and keeps its footprint small. A hospital is shown only to the visitor who made it, through a signed cookie that holds a random identifier and no personal data, and to the phone number that the visitor gave with consent. Its front desk page answers 404 to everyone else. At most `DEMO_ONBOARDING_MAX_ACTIVE` hospitals exist at once, and one visitor address may start `DEMO_ONBOARDING_PER_ADDRESS_PER_HOUR` in an hour. A hospital, its secret and its files are removed after `DEMO_ONBOARDING_HOURS` hours, and one that has not expired comes back after a restart with its appointment book. When `DEMO_ONBOARDING_ENABLED` is false, every page of the wizard answers 404.

## Follow-up

A job that runs inside the application (`sofa/health/followups.py`) looks after the patient before and after a visit that Talk booked. It texts the patient once when the hospital's staff confirm a visit, and it sends a reminder when the visit is less than a day away. After the visit it asks the clinic's own book what became of it, and it sends a thank-you to the patient who came or an offer to rebook to the patient who did not. The reminders and follow-up texts go out only between 7 in the morning and 8 in the evening, Lagos time, and each is sent once. The confirmation text is sent as soon as Talk learns that the staff confirmed the visit. The clinic stays the source of truth, and Talk changes its own record only to match what the clinic's system says.

## A worked example

This is the conversation from the README, with what happens at each turn. Every step named here appears in the trace that the Try it page and the wizard show.

**Turn 1.** The caller says, "Please help me find the nearest clinic for antenatal care."
- Heard: Muse Voice Transcribe returns the words, and the trace records the model and the time it took.
- Understood: Muse Spark returns the action `health.find_facility`. At the same moment, the front desk reads the details of the request.
- Read: the need is antenatal care, and there is no area.
- Replied: Talk asks politely which area of Lagos the caller is in. It remembers that the question was asked, that it belongs to a search for a facility, and which details it already has.

**Turn 2.** The caller says, "I am in Surulere."
- Understood: because a question is waiting, this sentence is the answer to it, and the request in progress goes on.
- Read: the area is Surulere, which is matched against the list of Lagos areas.
- Asked: the front desk sends a signed search to every clinic provider at the same moment, and the trace lists each provider, the operation, the time and the result.
- Replied: Talk names the three nearest places, open ones first, each with its kind, the trip from Surulere with the usual traffic at this hour, its waiting time when it is open and its fee, and asks whether the caller would like an appointment at one of them. It remembers the three options. A trip is worked out only from where the caller said they are (`sofa/health/travel.py`): the road distance from the straight line, a Lagos traffic profile by hour and weekday, and a range rather than one figure. Until the caller has said where they are, no distance is spoken at all.

**Turn 3.** The caller says, "Yes, please book the private clinic."
- Understood: the model reads the sentence as a yes, and a word-matching step reads "the private clinic" as the choice of Surulere Care Clinic. A yes that also chooses a place answers the offer and the choice together.
- Replied: no day was said, so Talk asks which day and time the caller would like at that clinic.

**Turn 4.** The caller says, "Tomorrow morning, please."
- Read: the time is understood as tomorrow morning, in Lagos time.
- Asked: the clinic's provider is asked for the first free time that fits.
- Replied: Talk reads back the real time, for example "I can book you at Surulere Care Clinic tomorrow at 8 in the morning", and asks for confirmation. Nothing is booked yet.

**Turn 5.** The caller says, "Yes, please go ahead."
- Understood: a clear yes to the question that was just asked.
- Asked and booked: Talk sends the signed booking, and the provider confirms it and returns a booking code. The trace records the booking with a link to the clinic's appointment book.
- Replied: Talk confirms the visit and reads out the code. A text message with the details goes to the caller, and Talk says so only because the message was accepted. The visit now appears in the clinic's appointment book, where the staff can confirm it, and the follow-up job takes over from there.

If the caller had said, "Please, my brother is not breathing, we are in Ikeja," at any point, the emergency help would have started at once, without waiting for a model. Talk would have given the number 112 first, named the nearest hospital with a free emergency place, told its front desk, and asked whether the caller reached 112. An answer that Talk's rules cannot read, such as "When is the next available slot?" in reply to the question about a time, is read by Muse Spark with the question in view, so it is understood and not asked again.

## What each Meta model does

| Model | Job |
|---|---|
| Muse Voice Transcribe | It hears the caller in English, with keyword hints for places, clinics and medicines, and it reads one recording at a time. |
| Muse Spark 1.3 | It understands the request as strict JSON, picks among the real options when the rules cannot, and words the conversation around the facts. It is used in Standard mode only, and never as a contributor model. |

## What is next

- **Realtime speech to text.** Muse Voice Transcribe is used today on one finished recording at a time. Moving to Meta's realtime transcription would make the words ready as the caller finishes speaking, and it is expected to save about two and a half seconds on every turn.
- **More languages.** Talk speaks English today, because Meta's speech model does not yet hear Yoruba, Hausa, Igbo or Pidgin. Serving callers in those languages is the next step as soon as a model can hear them.
- **A real hospital connection.** One of the two community hospitals can replace a simulated provider by answering the same signed operations, once it has the computers and the connection that the first two parts of the deployment give it.
- **More for the patient.** A patient could send a photo of a prescription or of a medicine label through a link in a text message, with the pharmacist approving before anything is dispensed. Repeat medicines and antenatal visits could be scheduled for a registered patient.
- **More institutions.** The same architecture can carry government services, public information and emergency coordination, once each of those institutions is connected the way a provider is today.
