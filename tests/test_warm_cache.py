"""The audio warm-up keeps only the audio that the real voice made, asks again for a phrase that the voice service refused, and prepares only the phrases that are fixed."""

import asyncio

from scripts import warm_cache
from sofa.dialogue import templates


class FakeAudio:
    """An audio service whose voice is refused for the first `refusals` tries of each phrase, as a rate-limited voice service would do."""

    def __init__(self, folder, refusals):
        self.folder, self.refusals, self.tries = folder, refusals, {}

    async def speak(self, text, lang):
        n = self.tries[text] = self.tries.get(text, 0) + 1
        path = self.folder / f"{abs(hash(text))}.wav"
        path.write_bytes(b"audio")
        marker = path.with_suffix(".fallback")
        if n <= self.refusals:
            marker.write_text("0")
        else:
            marker.unlink(missing_ok=True)
        return "url", str(path)


def test_a_refused_phrase_is_thrown_away_and_asked_for_again_until_the_real_voice_makes_it(tmp_path):
    audio = FakeAudio(tmp_path, refusals=2)
    assert asyncio.run(warm_cache.speak_properly(audio, "Are you still there?", "en", pace=0, pause=0)) is True
    assert audio.tries["Are you still there?"] == 3 and not list(tmp_path.glob("*.fallback"))


def test_a_phrase_that_is_never_made_is_reported_and_leaves_no_silent_file_behind(tmp_path):
    audio = FakeAudio(tmp_path, refusals=99)
    assert asyncio.run(warm_cache.speak_properly(audio, "Hello", "en", pace=0, pause=0)) is False
    assert audio.tries["Hello"] == warm_cache.RETRIES and not list(tmp_path.glob("*.wav")) and not list(tmp_path.glob("*.fallback"))


def test_a_phrase_that_is_made_at_the_first_attempt_is_kept(tmp_path):
    audio = FakeAudio(tmp_path, refusals=0)
    assert asyncio.run(warm_cache.speak_properly(audio, "Hello", "en", pace=0, pause=0)) is True and audio.tries["Hello"] == 1
    assert len(list(tmp_path.glob("*.wav"))) == 1


def test_the_warm_up_prepares_every_fixed_phrase_in_english_and_nothing_with_a_placeholder(monkeypatch, tmp_path, capsys):
    spoken = []

    class Recorder:
        async def speak(self, text, lang):
            spoken.append((text, lang))
            return "url", str(tmp_path / "clip.wav")

    class Services:
        audio = Recorder()

    monkeypatch.setattr(warm_cache, "build_services", lambda settings, session_factory: Services())
    monkeypatch.setattr(warm_cache, "make_engine", lambda url: None)
    monkeypatch.setattr(warm_cache, "make_session_factory", lambda engine: None)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(warm_cache.asyncio, "sleep", lambda seconds: real_sleep(0))      # the pause between phrases is not needed here
    asyncio.run(warm_cache.main())
    assert [text for text, _ in spoken] == list(templates.fixed_phrases().values())
    assert {lang for _, lang in spoken} == {templates.LANG} and not any("{" in text for text, _ in spoken)
    assert f"Cached {len(spoken)} fixed phrases" in capsys.readouterr().out
