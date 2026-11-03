# Model log: what we measured, what we changed and what it did

This log records each problem that we met with the Meta models and with the live and test calls of the health build. Every entry says what went wrong, what we changed and what the change did, and it says plainly when an effect has not been confirmed on a real phone line yet.

Muse Spark 1.3 reads each request, Muse Voice Transcribe hears the caller, and a hosted voice speaks. The first eight entries were measured on the first live and test calls of 28 October. Entries 9 to 11 record what we learned about the strict JSON answer format and the wording of replies while the front desk was being built, and entries 12 to 15 record the work of 1 and 2 November on emergencies, answers and speed.

## Entry 1. Muse Voice Transcribe returned nothing, and refused a long keyword

Muse Voice Transcribe used in push-to-talk mode returned empty text for a recording that was sent as a file. A keyword of more than 30 characters was refused with HTTP 400, which failed the whole request.

We changed to the endpointing mode, and we now keep only keywords of 30 characters or fewer. Long facility names are shortened to what a caller would say, and the rest are dropped.

Recordings are now read, and the names of places and medicines bias the recognition as intended.

## Entry 2. Muse Spark padded its answer until it ran out of tokens

Muse Spark 1.2 with minimal reasoning padded its JSON with spaces until it ran out of tokens. The token limit also counts the model's own thinking, so a limit that suited the reply alone was far too small.

We moved to Muse Spark 1.3, and we added 800 tokens of room on top of the reply's own limit. Only the tokens that are really used are billed.

Strict JSON answers now complete on every turn that we measured.

## Entry 3. The first live call failed on a locked database and a slow recording address

On the first live call a turn held a database write open through a slow voice call and a slow model call, which ended in "database is locked". Separately, a recording address that answered 404 caused 12.9 seconds of retries.

We turned on write-ahead logging with a 30-second wait, and we made a turn save its first write at once. A provider call is also saved before the next slow step begins, and the retries for a recording are shorter.

Lock errors no longer appear on calls, and a recording is now fetched in about a second.

## Entry 4. The hosted voice refused many requests at once

The hosted voice answered HTTP 429 when many requests arrived together. The first warm-up of the fixed phrases also kept 38 silent stand-in clips as the permanent audio of those phrases, so callers heard silence where a phrase should have been.

We added retries after growing pauses, we keep a stand-in clip for two minutes only, and the warm-up now goes slowly enough for the voice's rate limit.

All 138 fixed phrases are now voiced properly.

## Entry 5. The hosted voice ran out of credit and replies went silent

When the hosted voice ran out of credit it answered HTTP 402, "no credits left". Every reply that was not a stored phrase came out as silence, and only the holding messages were heard.

We added a voice that runs on the server itself, which is Piper. It speaks whenever the hosted voice fails, and after a refusal about credit or about the key, the hosted voice is left alone for ten minutes, so that no sentence waits for a failure before it is spoken.

A reply is always spoken now. Credit is still the first thing to check when replies go quiet.

## Entry 6. The first timing of a streamed call was 11 seconds

The first timing of the streamed path, a test call through Asterisk, took 2.6 seconds to read the speech and 2.9 seconds to understand and act. The voice took 5.5 seconds, because the whole reply of about 60 words was voiced before any of it played. The whole turn took 11 seconds.

We cut the reply into sentences, which are voiced side by side and spoken one after another, so that Talk starts speaking as soon as the first sentence is made.

The first sound no longer waits for the last sentence. Real calls over the trunk have not been measured yet.

## Entry 7. A trunk that goes quiet, and line noise that cuts Talk off

A trunk can stop sending audio while the caller is quiet, so the signal that speech had ended never came. Steady line noise above the speech level also read as the caller talking over Talk, which would cut every reply off at once.

We now time the end of speech by the clock as well. The noise level is learned continuously, and the bar is never raised above three times the base level. The caller can stop Talk only by starting to speak after Talk has begun to speak.

The tests cover these cases. They have still to be confirmed on a real phone line.

## Entry 8. A recording's address could point anywhere

The address of a recording arrives in the telephony callback, and it was downloaded from wherever it pointed. That could have made the server fetch an internal page.

Recordings are now fetched only over https and only from the provider's own hosts, and every redirect is checked against the same list. Recordings are also deleted after 30 days.

An address in a callback can no longer make the server fetch an internal page.

## Entry 9. The shape of the answer decides whether the model answers fully

While we built the understanding step, we found that Muse Spark skipped most of the fields that were optional in the answer format. We also found that one flat `action` choice, which names a registered tool or one of a few special values, worked far better than choosing a service first and then a tool. A dozen example sentences, written the way callers really speak, are what make the yes and no answers and the tool choices come out right. Every field also costs answer time.

We made every field required, we wrote the allowed choices into the format as a closed list, and we ask only for the fields that a situation needs. The same strict format rejects some JSON schema keywords, such as title, default and the length and size limits, so these are removed before the schema is sent.

The model can name only an operation that exists, and a sentence that is not understood is asked about again instead of being guessed at.

## Entry 10. The model answered with an empty sentence when its answer field was optional

When the `say` field of the wording step was optional in the answer format, Muse Spark answered with an empty string whenever the reference sentence contained placeholders. This is the same lesson as the understanding step: a field that may be left out is left out.

We made `say` a required field with a minimum length, so that an empty answer is refused by the format itself. We also made every field of the reading of a request required, with null as the way to say that nothing was said, and we accept a place, a time or a medicine only if it is made of the caller's own words.

A wording that does not arrive costs the caller nothing, because the stored sentence is spoken instead, and the model supplies no facts.

## Entry 11. The model invented figures when it worded a sentence that carried facts

In testing, the model invented figures and answered instead of rewording whenever the sentence it was given carried text that a provider or a patient guide had written. The checker refused every one of those sentences, but the safest rule is not to ask.

Every sentence of the health front desk is now spoken exactly from its stored phrase, so a provider's facts and a patient guide's words are never reworded. The model words only the conversation around them, and its sentence is accepted only if it keeps every placeholder, makes up no number of its own and stays short.

A caller always hears the provider's real facts, and when the model is slow or wrong, the caller hears the stored wording instead.

## Entry 12. Emergencies were found by a closed list of English phrases

Emergencies were found by a closed list of 17 English phrases, with no model. On a set of 85 sentences that callers might say, it sent only 10 of 54 true emergencies to 112 as emergencies, and it raised a false alarm on 8 of 24 sentences with no danger, such as "I accidentally missed my appointment".

Muse Spark now reads urgency on every turn, by meaning, as the first field of the one reading it already makes, so it adds no model call. A keyword floor runs first with no model, allows for the recogniser's spelling, stays quiet on negations and on things that are over, and can only raise the model's level.

The floor alone now sends 39 of the 54 true emergencies to 112 as emergencies, with no false alarm on the same 85 sentences. On the live service on 2 November, Muse Spark alone recognised "Something bit my leg in the bush and it is swelling up very fast" as an emergency, which no keyword covers. It read "My chest has been feeling tight since this morning" as a possible emergency, so Talk asked one question, and it read "I am not bleeding, I just want a check-up" as no danger.

## Entry 13. A simple answer that the rules could not read was asked for again

Asked which day and time a caller would like, the caller answered "When is the next available slot?", and Talk said that it did not catch the day and time. The rules read days and times, and nothing read what the caller meant.

When the rules cannot read an answer, Muse Spark now reads it with Talk's question in view and says what the caller meant: the thing that was asked, the earliest free time, a yes, a no, or something else. A day, a time or an area it gives counts only if it is made of the caller's own words.

On the live service on 2 November, the same sentence was understood, and Talk offered the earliest time that the caller could reach from their area, with when to leave.

## Entry 14. How long one reading takes on the live service

On the live service on 2 November, the one reading of a turn by Muse Spark 1.3 took 1.4, 4.6, 2.3 and 1.7 seconds on four typed turns of one conversation. The longest was the turn that carried the most conversation in its prompt.

Nothing was changed for this entry. It is recorded because every second matters on a telephone line, and it is why realtime transcription is the first open improvement below.

## Entry 15. An answer that does not fit the format now gets a second try

An answer that was not valid JSON, or did not fit the format, was treated at once as not understood, so one bad answer cost the caller a turn.

Talk now asks once more, saying why the first answer could not be used, and waits at most four seconds for the second answer. If that answer does not fit either, the rules carry on as before. The counts of answers, rejections, repairs and failures are shown on `/health`.

The tests cover the second try, the second failure and the time limit. How often it is needed on live calls has not been measured yet.

## Entry 16. Sofa forgot what the caller had already said

On the live service on 2 November, two callers said almost the same thing: a child has a high fever, and they want the next available slot. In one call Muse Spark read it as a possible emergency, so Talk gave the emergency number and asked whether someone was in danger. In the other call it read no urgency at all. Both readings are reasonable for a fever, but they mean a caller cannot predict which question comes next.

The same calls showed a deeper fault in Talk itself: Sofa forgot things. A caller who answered the danger question with where they were ("I dey Ikorodu") was asked for the area again. A caller who said "Yes, please book it" after Sofa had read out the free times was asked what they would like to do. A caller who gave the wrong kind of answer once had that answer counted twice, so Talk gave up after a single miss. The cause was that what the caller said was kept only inside the question Talk was asking, and was thrown away when that question closed. The model also saw only the caller's last two sentences, never what Sofa itself had just said.

Talk now keeps a memory of the whole call. Where the caller is, what they need, the clinic, the day and time, and what Sofa last offered are kept from turn to turn, whatever question was open, and every new request starts from them. A turn that only adds a detail, or only says "book it", goes on with the request already in hand. The model now also sees what Sofa said last and a short note of what the call is about. An answer that is not a place uses one try, not two, and a caller who asks for the next available slot is offered the earliest time to book. The tests replay the failed calls and others where the caller answers late, out of order, or comes back after a closed question. How often the urgency reading differs on the same sentence has not been measured yet; that is the fourth open improvement below.

## Entry 17. The model now leads the conversation

The memory of entry 16 stopped Sofa forgetting, but a test call on the live service on 2 November showed the deeper limit of the design: the rules decided each step, and the model only labelled one sentence at a time. A caller asked where to get paracetamol, then "I am at Palmgrove, how long will it take me to get there". Sofa did not know Palmgrove, lost what "there" meant, offered to book a clinic nobody asked for, and then answered "No, I just need paracetamol" with "What would you like to do next?". None of this was the model's fault: it was shown only the caller's last two sentences, and an area it named was thrown away unless it was on Talk's list of 21.

Muse Spark now reads the whole call, both sides, and decides the next step, while the code keeps the guard rails described in the README. On this computer, with the live model, the same conversation now ends with the nearest pharmacy that has paracetamol and the trip from the area nearest Palmgrove. "The cheapest one" picks the right clinic, a question about the fee in the middle of a booking is answered and the booking stays open, a caller who asks about a medicine and then goes back to their clinic is booked at it, and "the general hospital" is found by its kind in the caller's area. The decision takes 1 to 3 seconds a turn, one model call, which is faster than the two or three calls of the rules-led design.

The tests script the model's decisions and check the guard rails: a booking only after a proposal and a yes, a reply with a figure that was not said is not spoken, the emergency words are answered before the model is asked, an area outside the list and a day the caller never said are not used, and the rules answer when the model gives nothing.

## Entry 18. Medicines by meaning, and photos of prescriptions

A test on the live service on 3 November asked for "a pain reliever" and for "antimalaria drugs". Sofa asked for the name as written on the pack, although the pharmacies stock paracetamol, ibuprofen and an antimalarial. The model had never been shown what the pharmacies keep, and the code only recognised product names.

Each pharmacy system now publishes its catalogue (product, what it is for, price, prescription), Talk reads it every few minutes, and Muse Spark is shown it with the conversation and returns the exact products that fit what the caller means. With the live model on 3 November: "a pain reliever" gave paracetamol and ibuprofen with prices, "antimalaria drugs" gave artemether-lumefantrine and sulphadoxine-pyrimethamine with the prescription note, "something for catarrh" gave loratadine, and "what is the difference between paracetamol and ibuprofen?" was answered from the catalogue's own words. A reply may quote the catalogue, and a figure in it that is in neither the call nor the catalogue is still not spoken.

Muse Spark 1.3 also reads photos sent on WhatsApp, with the image attached to the message on the Meta Model API. On a printed test prescription it returned both medicines exactly as written, with the hospital and the date, in 4.5 seconds. On a handwriting-style prescription with abbreviations ("Tab Coartem 80/480 1 bd x3/7", "Tab PCM 1g tds", "Syr Vit C 5mls od"), Muse Spark 1.3 and Muse Wonder 1.0 both read all three medicines in about 8 seconds and turned Coartem into artemether-lumefantrine and PCM into paracetamol; Muse Spark 1.3 also kept the form (tablets, syrup), so it is the one Talk uses. The medicines then go into the conversation like typed words. The photo itself is not kept, and the model is told to leave out a patient's name and number. Meta's model list has no separate model for reading text in images: SAM 3.1 outlines objects and Muse Image makes pictures, so the chat model's vision is the right tool here.

## Entry 19. Sofa writes its own replies

After a step, the reply was a fixed sentence with the facts filled in, and the next question was chosen by code ("Which area are you in?", "Would you like me to set a pack aside?"). It was accurate, but it sounded scripted, and it often closed the conversation with "Is there anything else?" instead of moving it on.

On WhatsApp and in the web chat, Muse Spark 1.3 now gets Sofa's role and job as a system prompt, the whole conversation and the facts the systems returned for that step, and writes the reply and its own next question. With the live model on 3 November, after "I need a pain reliever, I am in Yaba" it wrote "I found pain relievers near you in Yaba… Which one should I set aside for you to pay and collect?", and for the grandmother's call "Sorry about the fever, I hope your grandchild feels better soon. I can book you at Ikorodu Greenfield General Hospital…".

The written reply is checked against the step's facts only. A test showed why: a made-up price of 250 naira for paracetamol passed while the check also accepted the whole medicine catalogue, because another product costs 250 naira. Writing the reply costs a second model call, so a turn on WhatsApp takes about 4.5 to 7.5 seconds instead of 2 to 4; phone calls keep the fixed wording for that reason. Booking confirmations, payment details and emergency instructions are always said word for word.

## Open improvements, starting with the most valuable

1. Realtime transcription over Meta's WebSocket while the caller speaks, at `wss://api.meta.ai/v1/asr/realtime`, so that the words are ready when the caller stops. We expect it to save about 2.5 seconds on every turn compared with reading a finished recording.
2. A measurement of the streamed path on real calls over the trunk, so that the figures of entries 6 and 7 are confirmed on a real phone line.
3. The rate of second tries from entry 15 on live calls, read from `/health`, and the share of emergencies that only the model recognised.
4. A repeat test of the urgency reading from entry 16: the same sentence sent many times, to measure how often Muse Spark reads it differently.
