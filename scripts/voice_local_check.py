"""Does the voice on this machine speak? It speaks two sentences with that voice and says how long each took.

    python -m scripts.voice_local_check
    python -m scripts.voice_local_check --text "Your appointment is confirmed for tomorrow morning."

The voice is the Piper voice that PIPER_MODEL points to (deploy/setup_voice.sh sets it up). Nothing is sent anywhere. The exit status is 0 when the
voice spoke and 1 when there is no voice on this machine.
"""

import argparse
import asyncio
import io
import sys
import time
import wave

from sofa.clients.tts import build_local_voice
from sofa.config import get_settings

SENTENCES = (
    "Hello, this is a test of the voice on this machine.",
    "The nearest place is Yaba Lakeview Clinic, a private clinic on Herbert Macaulay Way, less than a kilometre away. It is open until six in the evening.",
)


async def run(sentences: tuple[str, ...]) -> int:
    settings = get_settings()
    print(f"PIPER_MODEL: {settings.piper_model or 'not set'}")
    voice = build_local_voice(settings)
    if voice is None:
        print("There is no voice on this machine: the model is not set, the file is missing, or the piper package is not installed. See deploy/setup_voice.sh.")
        return 1
    print(f"voice: {voice.tag}")
    for text in sentences:
        started = time.perf_counter()
        audio = await voice.synthesize(text, "en")
        took = time.perf_counter() - started
        with wave.open(io.BytesIO(audio)) as w:
            seconds = w.getnframes() / w.getframerate()
        print(f"   {len(text.split()):>2} words: {took:.2f} s to make {seconds:.1f} s of speech")
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m scripts.voice_local_check", description="Speak sentences with the voice on this machine and report how long each took.")
    ap.add_argument("--text", help="one sentence to speak instead of the two built-in ones")
    return ap


if __name__ == "__main__":
    args = parser().parse_args()
    sys.exit(asyncio.run(run((args.text,) if args.text else SENTENCES)))
