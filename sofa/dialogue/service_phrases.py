"""The phrases of the health front desk: what it asks, what it answers, and what it texts.

Merged into templates.PHRASES and CONTEXT when templates loads, so they are spoken and rotated like every other phrase. Every one is a polite, complete sentence that
is short enough to be heard on a phone. The facts inside them (a place, a time, a price, a code) are filled in from what the providers confirmed.
"""

PHRASES: dict[str, list[str]] = {
    # what the desk says when it has not yet understood what the caller wants
    "health_ask_what": ["Certainly, I can help with {service}. What would you like to do? For example, I can find a clinic or a pharmacy near you, book or cancel an appointment, "
                        "or check whether a medicine is in stock."],
    "health_say": ["{answer}"],
    "health_answer": ["{answer} Is there anything else I can help with?"],
    "health_unavailable": ["I am sorry, {service} is not available right now. Please try again in a little while. Is there anything else I can help with?"],

    # questions that ask for one missing detail
    "health_ask_area": ["Of course. Which area of Lagos are you in, please? For example Surulere, Yaba or Ikeja.",
                        "Certainly. Could you please tell me which area of Lagos you are in?"],
    "health_ask_area_again": ["I am sorry, I did not recognise that area. Could you please tell me a well known place near you, such as a market or a junction?"],
    "health_ask_emergency_area": ["If this is an emergency, please call {number} now. Which area of Lagos are you in, please, so that I can find the nearest emergency care?"],
    "health_ask_emergency_area_again": ["If this is an emergency, please call {number} now. I am sorry, I did not recognise that area. Could you please tell me a well known place "
                                        "near you, such as a market or a junction, so that I can find the nearest emergency care?"],
    "health_ask_place": ["Certainly. Which clinic or hospital do you mean, please?"],
    "health_ask_place_again": ["I am sorry, I could not find that place. Which clinic or hospital do you mean, or which area of Lagos are you in?"],
    "health_ask_clinic": ["Certainly. Which clinic would you like, or which area of Lagos are you in?"],
    "health_ask_clinic_again": ["I am sorry, I could not find a clinic like that. Which clinic would you like, or which area of Lagos are you in?"],
    "health_ask_drug": ["Of course. Which medicine are you looking for, please? You can say the name as it is written on the pack."],
    "health_ask_drug_again": ["I am sorry, I did not catch the name of the medicine. Could you please say it as it is written on the pack?"],
    "health_ask_when": ["Which day and time would you like at {place}, please? For example, tomorrow morning."],
    "health_ask_when_again": ["I am sorry, I did not catch the day and time. Could you please tell me, for example, tomorrow morning or Friday at two in the afternoon?"],
    "health_ask_when_other": ["That is no problem. Which day and time would suit you better?"],

    # when a question was asked twice and still not understood
    "health_giveup_area": ["I am sorry, I could not place that area. When you call again, please tell me a well known place near you, such as a market or a junction."],
    "health_giveup_drug": ["I am sorry, I could not tell which medicine you mean. When you call again, please say the name as it is written on the pack."],
    "health_giveup_emergency": ["If this is an emergency, please call {number} now. I am sorry, I could not place that area, so I could not find the nearest emergency care."],
    "health_giveup_place": ["I am sorry, I could not find that place. When you call again, please tell me the name of a clinic, or a well known place near you."],

    # finding a place
    "health_find_none": ["I am sorry, I could not find a place offering that near you."],
    "health_emergency_call": ["If this is an emergency, please call {number} now."],
    "health_emergency_unreachable": ["If this is an emergency, please call {number} now. I am sorry, I could not reach the clinics just now, so I cannot tell you which emergency care is nearest."],
    "health_emergency_none": ["If this is an emergency, please call {number} now. I am sorry, I could not find emergency care near you in the clinics I can see."],
    "health_find_nearest": ["The nearest {what} is {place}"],
    "health_find_others": ["The other options are {others}."],
    "health_find_told": ["I have also informed {name}, so that the team there can follow up."],
    "health_find_offer_one": ["Would you like me to book an appointment there for you?"],
    "health_find_offer_many": ["Would you like me to book an appointment at one of them for you?"],
    "health_options_intro": ["{lead}I found {count} places{where}."],
    "health_options_item": ["The {ordinal} is {line}."],
    "health_options_ask": ["Which one would you like, please?"],
    "health_options_short": ["Of course. Which one would you like, please: {names}?"],
    "health_options_short_item": ["the {ordinal}, {name}"],
    "health_options_again": ["I am sorry, I did not catch which one you mean. "],

    # a named place
    "health_status_offers": ["It also offers {offers}."],
    "health_slots": ["The next free appointment times at {place} are {times}."],
    "health_slots_none": ["I am sorry, {place} has no free appointment times in the next two weeks."],

    # booking
    "health_offer_slot": ["{note}I can book you at {place} {day} at {time}. Would you like me to book it for you?"],
    "health_note_nothing_free": ["I am sorry, there is nothing free {day} at {place}. "],
    "health_note_taken": ["I am sorry, that time has just been taken. "],
    "health_booked": ["Your appointment is confirmed at {place} {day} at {time}. Your booking code is {code}. Please arrive 15 minutes early."],
    "health_text_sent": ["A text message with these details is on its way to you."],
    "health_text_sent_cancel": ["A text message to confirm this is on its way to you."],
    "health_sms_booked": ["Your appointment at {place} is confirmed for {day} at {time}. Your booking code is {code}. Please arrive 15 minutes early."],

    # cancelling
    "health_question_passed": ["I am sorry, the patient guide does not cover that question. I have passed it to the care team at {name}, and when they reply you will receive a text message."],
    "health_cancel_none": ["I am sorry, I could not find an appointment booked for you."],
    "health_cancel_none_day": ["I am sorry, I could not find an appointment booked for you {day}."],    # {day} is "today", "tomorrow" or a date that already begins with "on"
    "health_cancel_ask": ["Your appointment is at {place} {day} at {time}. Would you like me to cancel it?"],
    "health_cancelled": ["Your appointment has been cancelled."],
    "health_cancel_failed": ["I am sorry, I could not cancel that appointment. Please call the clinic directly."],
    "health_cancel_kept": ["Of course. I have kept your appointment as it is."],
    "health_sms_cancelled": ["Your appointment {code} has been cancelled. Please call this number whenever you would like to book a new one."],

    # medicines
    "health_drug_found": ["You can find {drug} at {where}. A pack costs about {price} naira."],
    "health_drug_prescription": ["Please note that this medicine needs a prescription from a doctor."],
    "health_drug_night": ["{pharmacy} is open all night."],
    "health_drug_none": ["I am sorry, none of the pharmacies I can see have {drug} in stock right now."],

    # a message to a provider's staff
    "health_sms_staff": ["Please note that an urgent request, {code}, has arrived for {place}. Please open the front desk to read it and reply."],
    "health_staff_emergency": ["The caller described an emergency{where}. Their words were: {said}"],
}

CONTEXT: dict[str, str] = {
    "health_ask_what": "The caller asked for health help but not what they want. {service} is the service. Asks kindly what they would like to do and gives a few examples.",
    "health_say": "Something the health service asks the caller. {answer} is the question, already written. Say it as it is.",
    "health_answer": "What the health service told the caller, then asks if there is anything else. {answer} is the service's own sentence: keep it exactly.",
    "health_unavailable": "The health service cannot be reached right now. {service} is its name. Apologises, says to try again in a little while, and asks if there is anything else.",
    "health_ask_area": "A caller wants a clinic, hospital or pharmacy but has not said where they are. Politely asks which area of Lagos they are in and gives a few examples.",
    "health_ask_area_again": "The area the caller gave was not recognised. Apologises politely and asks for a well known place nearby, such as a market or a junction.",
    "health_ask_emergency_area": "The caller described an emergency and has not said where they are. {number} is the emergency number: give it first, then politely ask which area of Lagos they are in.",
    "health_ask_emergency_area_again": "The caller described an emergency and the area they gave was not recognised. {number} is the emergency number: give it first, then politely ask for a well known place nearby.",
    "health_ask_place": "The caller asked about a clinic or hospital without naming it. Politely asks which one they mean.",
    "health_ask_place_again": "The place the caller named was not found. Apologises politely and asks for the clinic or hospital, or the area of Lagos they are in.",
    "health_ask_clinic": "The caller wants an appointment but has not said where. Politely asks which clinic they would like, or which area of Lagos they are in.",
    "health_ask_clinic_again": "No clinic matched what the caller said. Apologises politely and asks again for the clinic or the area of Lagos.",
    "health_ask_drug": "The caller asked about a medicine without naming it. Politely asks which medicine, and to say the name as written on the pack.",
    "health_ask_drug_again": "The medicine was not recognised. Apologises politely and asks the caller to say the name as written on the pack.",
    "health_ask_when": "A clinic has been chosen and the caller has not said when they would like to come. {place} is the clinic. Politely asks for the day and time, with an example.",
    "health_ask_when_again": "The caller's day and time were not understood. Apologises politely and asks again, with an example.",
    "health_ask_when_other": "The caller did not want the time that was offered. Kindly asks which day and time would suit them better.",
    "health_giveup_area": "The area could not be understood after two tries. Apologises and says what to tell the next call.",
    "health_giveup_drug": "The medicine could not be understood after two tries. Apologises and says what to tell the next call.",
    "health_giveup_emergency": "The caller described an emergency and the area could not be understood after two tries. {number} is the emergency number: give it first, then apologise.",
    "health_emergency_unreachable": "The caller described an emergency but no clinic system could be reached. {number} is the emergency number: give it first, then say plainly that the clinics could not be reached.",
    "health_emergency_none": "The caller described an emergency but no emergency care was found near them. {number} is the emergency number: give it first, then apologise.",
    "health_giveup_place": "The place could not be found after two tries. Apologises and says what to tell the next call.",
    "health_find_none": "No clinic or pharmacy was found near the caller for what they need. Apologises politely.",
    "health_emergency_call": "Said first for an emergency. {number} is the emergency number.",
    "health_find_nearest": "Names the nearest place. {what} says what kind of place it is and {place} describes it, already written.",
    "health_find_others": "Names the other places that were found. {others} is the list, already written.",
    "health_find_told": "Says that the place's team was told about the emergency. {name} is the place.",
    "health_find_offer_one": "Asks whether the caller would like an appointment at the one place that was found.",
    "health_find_offer_many": "Asks whether the caller would like an appointment at one of the places that were just listed.",
    "health_options_intro": "Introduces a short list of places. {count} is how many and {where} says where and for what.",
    "health_options_item": "One place in the list. {ordinal} is first, second or third and {line} describes the place, already written.",
    "health_options_ask": "Asks which of the listed places the caller would like.",
    "health_options_short": "Asks again which place the caller would like, after the places were already read out. {names} is the list of names, already written.",
    "health_options_short_item": "One place in the short list. {ordinal} is first, second or third and {name} is the place.",
    "health_text_sent_cancel": "Says that a text message confirming the cancellation has been sent to the caller.",
    "health_options_again": "Apologises politely that it was not clear which place the caller meant.",
    "health_status_offers": "Adds what else a place offers. {offers} is the list.",
    "health_slots": "Says the next free appointment times at a place. {place} is the place and {times} are the times.",
    "health_slots_none": "A place has no free appointment times for two weeks. {place} is the place. Apologises politely.",
    "health_offer_slot": "Reads back the booking that is offered and asks for the caller's confirmation. {place}, {day} and {time} are real facts.",
    "health_note_nothing_free": "Said before an alternative time is offered, because the day the caller asked for is full. {day} and {place} are facts.",
    "health_note_taken": "Said before another time is offered, because the time was just taken by someone else.",
    "health_booked": "Confirms a booking that a clinic has just accepted. {place}, {day}, {time} and {code} are the clinic's own facts.",
    "health_text_sent": "Says that a text message with the booking details has been sent to the caller.",
    "health_sms_booked": "The text message that confirms a booking. {place}, {day}, {time} and {code} are the clinic's own facts.",
    "health_question_passed": "A question the patient guide does not cover was passed to the care team. {name} is the care team. Apologises politely and says a text message will follow when they reply.",
    "health_cancel_none": "The caller asked to cancel an appointment but none was found. Apologises politely.",
    "health_cancel_none_day": "No appointment was found for the day the caller named. {day} is the day. Apologises politely.",
    "health_cancel_ask": "Reads back the appointment that would be cancelled and asks for confirmation. {place}, {day} and {time} are facts.",
    "health_cancelled": "Confirms that the appointment is cancelled.",
    "health_cancel_failed": "The clinic would not cancel the appointment. Apologises and suggests phoning the clinic.",
    "health_cancel_kept": "The caller decided to keep the appointment. Confirms it politely.",
    "health_sms_cancelled": "The text message that confirms a cancellation. {code} is the booking code.",
    "health_drug_found": "Says where a medicine is in stock and what a pack costs. {drug}, {where} and {price} are facts.",
    "health_drug_prescription": "Adds that the medicine needs a doctor's prescription.",
    "health_drug_night": "Adds that a pharmacy is open all night. {pharmacy} is the pharmacy.",
    "health_drug_none": "No pharmacy has the medicine. {drug} is the medicine. Apologises politely.",
    "health_sms_staff": "The text message that warns a provider's staff of an urgent request. {code} and {place} are facts.",
    "health_staff_emergency": "What a provider's staff read on their front desk when a caller described an emergency. {said} are the caller's own words.",
}
