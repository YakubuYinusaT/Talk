"""The emergency floor: the keyword reading that runs before the model on every turn. It must catch the plain ways people describe danger, allow for the
speech recogniser's spelling, stay quiet when there is no danger, and never lower what the model hears."""

import itertools

import pytest

from sofa.health import floor
from tests.emergency_corpus import CORPUS, E, N, P

RANK = {N: 0, P: 1, E: 2}


@pytest.mark.parametrize("rid, text, truth, want, model, kind", CORPUS, ids=[row[0] for row in CORPUS])
def test_each_sentence_gets_the_level_the_floor_is_meant_to_give(rid, text, truth, want, model, kind):
    assert floor.read(text).level == want


def test_no_sentence_without_danger_raises_an_alarm():
    calm = [row for row in CORPUS if row[2] == N]
    assert calm and all(floor.read(text).level == N for _, text, *_ in calm)


def test_most_true_emergencies_are_caught_by_the_words_alone():
    emergencies = [row for row in CORPUS if row[2] == E]
    caught = sum(floor.read(text).level == E for _, text, *_ in emergencies)
    raised = sum(floor.read(text).level != N for _, text, *_ in emergencies)
    assert caught >= 39 and raised >= 48      # the rest are left for the model, which reads urgency by meaning


@pytest.mark.parametrize("said", ["I am not bleeding, I only want a check-up.", "My child is not choking, she is fine now.", "I had a seizure many years ago.",
                                  "I am dying of hunger, please find me a pharmacy.", "I accidentally missed my appointment.", "I would like an urgent appointment, please."])
def test_ordinary_sentences_with_alarming_words_stay_quiet(said):
    assert floor.read(said).level == N


@pytest.mark.parametrize("said", ["My father has colapsed in the kitchen.", "She is bleding badly from her head.", "My son is chocking on a sweet."])
def test_a_misspelling_from_the_speech_recogniser_is_still_caught(said):
    assert floor.read(said).level == E


def test_the_model_can_raise_the_level_but_never_lower_it():
    for floor_level, model_level in itertools.product(floor.LEVELS, [*floor.LEVELS, None, "panic"]):
        combined = floor.combine(floor.Signal(floor_level), model_level)
        assert RANK[combined.level] >= RANK[floor_level]
        if model_level in RANK:
            assert RANK[combined.level] == max(RANK[floor_level], RANK[model_level])


def test_the_floor_names_the_patterns_it_matched_and_never_keeps_the_words():
    signal = floor.read("Please help, my brother is not breathing.")
    assert signal.level == E and "not breathing" in signal.hits and "brother" not in " ".join(signal.hits)
