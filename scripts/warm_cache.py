"""Pre-generate the audio for every fixed phrase when Talk is deployed, so that a caller never waits for the voice to make a sentence it says on every call.

    python -m scripts.warm_cache

Talk speaks English, so every phrase in sofa/dialogue/templates.py that has no placeholder in it is spoken once here and kept. A phrase that does have a placeholder
(a name, a figure or a place) can only be spoken when a call needs it, because its words are not known until then.
"""

import asyncio
from pathlib import Path

from sofa.config import get_settings
from sofa.container import build_services
from sofa.db import make_engine, make_session_factory
from sofa.dialogue import templates


PACE_SECONDS = 0.5          # a little time between phrases, so that the voice service's rate limit is not reached by the warm-up itself
RETRIES = 6                 # a phrase that the voice service refused is asked for again after 5, 10, 15 seconds and so on


async def speak_properly(audio, text: str, lang: str, pace: float = PACE_SECONDS, pause: float = 5.0) -> bool:
    """Speaks one phrase and keeps its audio, but only when the real voice made it. Audio that the stand-in voice made because the real one refused the request is
    thrown away, and the phrase is asked for again after a pause that grows each time. The answer is False when the phrase could not be made in the end."""
    for attempt in range(RETRIES):
        _, path = await audio.speak(text, lang)
        marker = Path(path).with_suffix(".fallback")
        if not marker.exists():
            await asyncio.sleep(pace)
            return True
        Path(path).unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
        await asyncio.sleep(pause * (attempt + 1))
    return False


async def main() -> None:
    settings = get_settings()
    svc = build_services(settings, make_session_factory(make_engine(settings.database_url)))
    made = failed = 0
    for text in templates.fixed_phrases().values():
        ok = await speak_properly(svc.audio, text, templates.LANG)
        made, failed = made + ok, failed + (not ok)
    note = f"; {failed} could not be made with the real voice and will be made when a call first needs them" if failed else ""
    print(f"Cached {made} fixed phrases{note}.")


if __name__ == "__main__":
    asyncio.run(main())
