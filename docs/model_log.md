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

## Open improvements, starting with the most valuable

1. Realtime transcription over Meta's WebSocket while the caller speaks, at `wss://api.meta.ai/v1/asr/realtime`, so that the words are ready when the caller stops. We expect it to save about 2.5 seconds on every turn compared with reading a finished recording.
2. A measurement of the streamed path on real calls over the trunk, so that the figures of entries 6 and 7 are confirmed on a real phone line.
3. The rate of second tries from entry 15 on live calls, read from `/health`, and the share of emergencies that only the model recognised.
