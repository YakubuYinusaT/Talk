"""Sentences a caller might say, each with the level of danger a careful person would hear in it. The emergency tests read them.

Each row is (id, text, truth, floor, model, kind).
  truth  what a careful person would conclude: emergency | possible | none
  floor  what the keyword floor alone must conclude (the floor is tuned for recall, so it may be one level above the truth for a few rows, and it must never be below the
         truth for a row of kind "clear", "third", "misheard" or "pidgin" unless the row says model-only by floor = none)
  model  what the model's urgency field should say (used by the stand-in model in the tests)
  kind   clear | indirect | third | negated | misheard | pidgin | joking | near | hesitant | selfharm | info
The system level is always max(floor, model), so the floor can only raise it.
"""

E, P, N = "emergency", "possible", "none"

CORPUS = [
    # clear
    ("c01", "My brother is not breathing, we are in Ikeja.", E, E, E, "clear"),
    ("c02", "Please help, my father has collapsed and he is unconscious.", E, E, E, "clear"),
    ("c03", "She is bleeding heavily and the blood will not stop.", E, E, E, "clear"),
    ("c04", "My baby is having a seizure.", E, E, E, "clear"),
    ("c05", "I have a terrible pain in my chest and I cannot breathe.", E, E, E, "clear"),
    ("c06", "A man was knocked down by a car outside our gate and he is not moving.", E, E, E, "clear"),
    ("c07", "He is choking on food and he cannot speak.", E, E, E, "clear"),
    ("c08", "She swallowed poison, please help me.", E, E, E, "clear"),
    ("c09", "There has been a bad accident on the Ikorodu road and people are badly hurt.", E, E, E, "clear"),
    ("c10", "My wife is in labour and the baby is coming now.", E, P, E, "clear"),
    ("c11", "He has been stabbed and there is blood everywhere.", E, E, E, "clear"),
    ("c12", "My sister has been shot.", E, E, E, "clear"),
    # indirect: the danger is described, not named
    ("i01", "Please come quickly, my wife is just lying on the floor and she will not answer me.", E, P, E, "indirect"),
    ("i02", "My grandmother is cold and stiff and I do not know what to do.", E, N, E, "indirect"),
    ("i03", "His lips have turned blue.", E, E, E, "indirect"),
    ("i04", "She went very quiet and her eyes are rolling back.", E, P, E, "indirect"),
    ("i05", "The pain in my chest is spreading to my arm and I am sweating a lot.", E, E, E, "indirect"),
    ("i06", "I think my husband is dying.", E, E, E, "indirect"),
    ("i07", "The boy fell from the second floor and now he is not talking.", E, P, E, "indirect"),
    ("i08", "My neighbour's house is on fire and a child is inside.", E, N, E, "indirect"),
    ("i09", "She drank something from the cupboard and now she is vomiting and very sleepy.", E, P, E, "indirect"),
    ("i10", "My mother cannot wake up since this morning.", E, E, E, "indirect"),
    # third person
    ("t01", "My neighbour just fell down and is not breathing well.", E, E, E, "third"),
    ("t02", "The driver slumped on the steering wheel and is not responding.", E, E, E, "third"),
    ("t03", "A woman at the bus stop has fainted and people are crowding round her.", E, P, E, "third"),
    ("t04", "My colleague is shaking and foaming at the mouth.", E, E, E, "third"),
    ("t05", "Our gateman has been bitten by something and he is swelling and dizzy.", E, N, E, "third"),
    ("t06", "My two year old swallowed a battery.", E, P, E, "third"),
    ("t07", "My sister is bleeding a lot after the delivery.", E, E, E, "third"),
    ("t08", "The old man next door is gasping for air.", E, E, E, "third"),
    # negated or only about a check-up: no emergency
    ("n01", "I am not bleeding, I only want a check-up.", N, N, N, "negated"),
    ("n02", "My child is not choking, he only coughs a little at night. Please find a clinic.", N, N, N, "negated"),
    ("n03", "She did not collapse, she only felt dizzy yesterday and is fine now.", N, N, N, "negated"),
    ("n04", "I have no chest pain, I would like a blood pressure check.", N, N, N, "negated"),
    ("n05", "He is breathing normally, I just want to book an antenatal visit for my wife.", N, N, N, "negated"),
    ("n06", "There was no accident, I only need a medical report for my insurance.", N, N, N, "negated"),
    ("n07", "My mother used to have seizures many years ago and I want to refill her tablets.", N, N, N, "negated"),
    ("n08", "Nobody is hurt, I only need to know where the hospital is.", N, N, N, "negated"),
    ("n09", "I stopped bleeding yesterday after the small cut, I only want to ask about a tetanus jab.", N, N, N, "negated"),
    ("n10", "I have a small cut on my finger and it is bleeding a little.", N, N, N, "negated"),
    # misheard by the recogniser
    ("m01", "My brother is not breathin.", E, E, E, "misheard"),
    ("m02", "She is bleding heavily.", E, E, E, "misheard"),
    ("m03", "He is unconcious and not wakin up.", E, E, E, "misheard"),
    ("m04", "My mother has colapsed.", E, E, E, "misheard"),
    ("m05", "He is not breeding and his lips are blue.", E, E, E, "misheard"),
    ("m06", "My baby is having a sea zur.", E, N, E, "misheard"),
    ("m07", "Please come he is chocking.", E, E, E, "misheard"),
    ("m08", "A woman is having a heart atack.", E, E, E, "misheard"),
    ("m09", "He cant breath and his chest is hurting.", E, E, E, "misheard"),
    # Nigerian English and Pidgin turns of phrase
    ("p01", "Abeg come, my wife don collapse for ground.", E, E, E, "pidgin"),
    ("p02", "E no dey breathe again, abeg help me.", E, E, E, "pidgin"),
    ("p03", "The boy don faint and him body dey cold.", E, P, E, "pidgin"),
    ("p04", "Blood dey comot plenty from her leg.", E, E, E, "pidgin"),
    ("p05", "Doctor abeg, my pikin dey shake body and him eye don turn white.", E, E, E, "pidgin"),
    ("p06", "She dey vomit blood.", E, E, E, "pidgin"),
    ("p07", "Oga the man no gree wake.", E, E, E, "pidgin"),
    ("p08", "Na so my neighbour take fall, him no talk again.", E, P, E, "pidgin"),
    ("p09", "My belle dey pain me small, abeg where I fit see doctor?", N, N, N, "pidgin"),
    ("p10", "The woman has slumped o, she is not talking and her mouth is twisted.", E, E, E, "pidgin"),
    # jokes and figures of speech
    ("j01", "I am dying of hunger, please find me a pharmacy that sells something sweet.", N, N, N, "joking"),
    ("j02", "That traffic on Third Mainland Bridge almost killed me, I need a clinic for a check-up.", N, N, N, "joking"),
    ("j03", "My phone has died, may I call you later about my appointment?", N, N, N, "joking"),
    ("j04", "I nearly collapsed with laughter at my friend's joke, but now I want a malaria test.", N, N, N, "joking"),
    ("j05", "My boss is giving me a heart attack with all this work, please book me a doctor.", N, N, N, "joking"),
    ("j06", "It was an accident that I deleted my number, I want to book a visit.", N, N, N, "joking"),
    ("j07", "I passed out from university in 2015 and I want to renew my hospital card.", N, N, N, "joking"),
    # near misses and ordinary requests
    ("o01", "Hello, good morning, I want to book an antenatal appointment in Surulere, please.", N, N, N, "near"),
    ("o02", "Do you have paracetamol in stock, please?", N, N, N, "near"),
    ("o03", "I need an urgent appointment for tomorrow, my child has an ear infection.", N, N, N, "near"),
    ("o04", "I want to ask about the stroke clinic review next month.", N, N, N, "near"),
    ("o05", "I accidentally missed my appointment yesterday, may I book another?", N, N, N, "near"),
    ("o06", "How long is the queue at Aguda health centre, please?", N, N, N, "near"),
    # hesitant and uncertain
    ("h01", "I am not sure if this is serious, my husband has been sleeping since morning and I cannot wake him properly.", E, E, E, "hesitant"),
    ("h02", "Maybe it is nothing, but my daughter is breathing very fast and looks scared.", P, N, P, "hesitant"),
    ("h03", "I want to see a doctor about my chest, it has been tight for some days.", P, P, P, "hesitant"),
    ("h04", "I have been bleeding since I gave birth two days ago and it is not reducing.", P, P, P, "hesitant"),
    ("h05", "I do not know if she is breathing, she is very still.", E, E, E, "hesitant"),
    ("h06", "Please hurry, my mother is in a very bad way.", E, N, E, "hesitant"),
    ("h07", "My son has a very high fever and is shaking badly.", P, P, P, "hesitant"),
    # the caller is in danger, or asks about the emergency service itself
    ("s01", "I want to kill myself.", E, E, E, "selfharm"),
    ("s02", "I do not want to live any more.", E, P, E, "selfharm"),
    ("s03", "I dey feel like say I wan die.", P, P, P, "selfharm"),
    ("f01", "What is the number for emergencies, please?", P, P, P, "info"),
    ("f02", "Is the emergency department at Ikeja Heights open now?", P, P, P, "info"),
    ("f03", "The baby has stopped moving in my wife's stomach.", E, E, E, "info"),
]

LEVEL = {N: 0, P: 1, E: 2}
