"""Checks that the Meta Model API works for Talk: the key, the language model (Muse Spark) and the speech model (Muse Voice Transcribe).

The key and the address come from the .env file (LLM_API_KEY and LLM_URL, with LLM_PROVIDER=meta). Put them there yourself and never commit that file. A
META_API_KEY in the environment is used instead of the file when it is set. The script never prints the key, and it removes the key from any message the
service sent back before showing it.

    python -m scripts.meta_check                          # the key, the language model on a few caller sentences, the speech model on a second of silence
    python -m scripts.meta_check --audio call.wav         # also reads one recording and prints the words that were heard
    python -m scripts.meta_check --dir recordings         # name.wav with name.txt (the true words): the word error rate over the folder

The recordings are resampled to 16 kHz mono first, as the voice route does it (this needs ffmpeg; without it the recording is sent as it is). The exit
status is 0 when every check passed and 1 when one did not, so the script can be used in a deployment check.
"""

import argparse
import asyncio
import io
import os
import statistics
import sys
import time
import wave
from pathlib import Path

import httpx
from pydantic import BaseModel

from sofa.audio import to_16k_mono
from sofa.clients.asr import MetaASRClient
from sofa.clients.llm import LLMClient
from sofa.config import get_settings
from sofa.textutil import wer

DEFAULT_BASE = "https://api.meta.ai"

SYSTEM = ("UNDERSTAND. You are the phone assistant of a health line in Lagos. A caller said the sentence below. Fill in the JSON for this turn: "
          "what the caller wants (find_facility, book, cancel, medicine_stock, ask_guide, emergency, confirm or other), the area of Lagos if one was named, "
          "and one short, polite sentence to say back.")

SENTENCES = [
    "Please help me find the nearest clinic for antenatal care.",
    "I am in Surulere.",
    "Hello, do you have amoxicillin in stock, please?",
    "Yes, please go ahead.",
]


class Turn(BaseModel):
    """What the language model is asked to fill in for one sentence."""
    intent: str = "other"
    area: str | None = None
    say: str = ""


def scrub(text: str, key: str) -> str:
    """The text with the key taken out, so a message from the service can be shown without showing the key."""
    return text.replace(key, "***") if key else text


def silence(seconds: float = 1.0) -> bytes:
    """A WAV of silence, 16 kHz mono: it shows that the speech model accepts a request from this key, without needing a recording."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


def took(start: float) -> str:
    return f"{time.perf_counter() - start:.2f} s"


async def check_key(base: str, key: str) -> list[str] | None:
    """Asks the service which models this key may use. Returns their names, or None (after saying why) when the key was not accepted."""
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(f"{base}/v1/models", headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as exc:
        print(f"FAILED  the service at {base} could not be reached: {type(exc).__name__}")
        return None
    if resp.status_code != 200:
        print(f"FAILED  the key was not accepted: HTTP {resp.status_code}: {scrub(resp.text[:200], key)}")
        return None
    try:
        names = sorted(str(m.get("id", "?")) for m in resp.json().get("data", []))
    except ValueError:
        names = []
    print(f"ok      the key was accepted ({took(start)}); the service lists {len(names)} models: {', '.join(names) or 'none named'}")
    return names


async def check_language_model(base: str, key: str, model: str, effort: str, names: list[str]) -> bool:
    """Sends a few caller sentences to the language model and shows how it understood each one and how long it took."""
    if names and model not in names:
        print(f"note    {model} is not in the list above; pass --model with one that is")
    llm = LLMClient(base, model, key, provider="meta", reasoning_effort=effort)
    print(f"\nlanguage model {model} (reasoning effort {effort}), one JSON answer per sentence:")
    good = 0
    for said in SENTENCES:
        start = time.perf_counter()
        try:
            turn, raw = await llm.extract(Turn, SYSTEM, said)
        except httpx.HTTPStatusError as exc:
            print(f"  FAILED  \"{said}\": HTTP {exc.response.status_code}: {scrub(exc.response.text[:200], key)}")
            continue
        except httpx.HTTPError as exc:
            print(f"  FAILED  \"{said}\": {type(exc).__name__}")
            continue
        if "error" in raw:
            print(f"  FAILED  \"{said}\" ({took(start)}): the answer was rejected: {scrub(str(raw['error'])[:160], key)}")
            continue
        if not turn.say.strip():
            print(f"  FAILED  \"{said}\" ({took(start)}): the answer was valid JSON but said nothing back to the caller")
            continue
        good += 1
        print(f"  ok      \"{said}\" ({took(start)}) ->{turn.intent}, area {turn.area or 'none'}, says: {turn.say[:80]}")
    print(f"  {good} of {len(SENTENCES)} sentences were understood")
    return good == len(SENTENCES)


async def check_speech_model(base: str, key: str, asr_model: str, keywords: list[str]) -> bool:
    """Sends a second of silence to the speech model: a good answer is an empty transcript."""
    asr = MetaASRClient(base, key, asr_model, tuple(keywords))
    print(f"\nspeech model {asr_model}, one second of silence:")
    start = time.perf_counter()
    try:
        heard = await asr.transcribe(silence(), "en")
    except httpx.HTTPStatusError as exc:
        print(f"  FAILED  HTTP {exc.response.status_code}: {scrub(exc.response.text[:200], key)}")
        return False
    except httpx.HTTPError as exc:
        print(f"  FAILED  {type(exc).__name__}")
        return False
    print(f"  ok      the model answered in {took(start)} and heard {'nothing, as it should for silence' if not heard.text else 'the words: ' + heard.text}")
    return True


async def hear_recordings(base: str, key: str, asr_model: str, keywords: list[str], files: list[Path]) -> bool:
    """Reads each recording with the speech model, and scores it against the words in the .txt file beside it, when there is one."""
    asr = MetaASRClient(base, key, asr_model, tuple(keywords))
    scores, passed = [], True
    for path in files:
        raw = path.read_bytes()
        try:
            wav = to_16k_mono(raw)
        except (FileNotFoundError, RuntimeError):
            wav = raw          # no ffmpeg here, or a recording it cannot read: it is sent as it is
        start = time.perf_counter()
        try:
            heard = (await asr.transcribe(wav, "en")).text
        except httpx.HTTPError as exc:
            print(f"\n{path.name}\n  FAILED  {type(exc).__name__}")
            passed = False
            continue
        truth = path.with_suffix(".txt")
        said = truth.read_text(encoding="utf-8").strip() if truth.exists() else ""
        score = ""
        if said:
            scores.append(wer(said, heard))
            score = f"  word error rate {scores[-1]:.2f}"
        print(f"\n{path.name} ({took(start)}){score}" + (f"\n  said:  {said}" if said else "") + f"\n  heard: {heard}")
    if scores:
        print(f"\n{len(scores)} recordings scored: mean word error rate {statistics.mean(scores):.3f}, median {statistics.median(scores):.3f}")
    return passed


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m scripts.meta_check", description="Check the Meta key, the language model and the speech model for Talk. The key is never printed.")
    ap.add_argument("--model", default=None, help="the language model (default: LLM_MODEL from the settings)")
    ap.add_argument("--asr-model", default=None, help="the speech model (default: ASR_MODEL from the settings)")
    ap.add_argument("--audio", help="one recording (WAV) to read with the speech model")
    ap.add_argument("--dir", help="a folder of name.wav files, each with name.txt holding the true words, to score the speech model")
    ap.add_argument("--keywords", default="", help="comma-separated words for the speech model to listen for, such as names of places and medicines")
    return ap


async def run(args) -> int:
    settings = get_settings()
    key = os.environ.get("META_API_KEY") or (settings.llm_api_key if settings.llm_provider == "meta" else "")
    base = settings.llm_url.rstrip("/") if settings.llm_provider == "meta" and settings.llm_url.startswith("http") else DEFAULT_BASE
    if not key:
        print("No key was found. Put LLM_PROVIDER=meta and LLM_API_KEY=<your key> in the .env file, or set META_API_KEY, and run this again.")
        return 1
    model, asr_model = args.model or settings.llm_model, args.asr_model or settings.asr_model
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    print(f"checking {base} with the key from {'META_API_KEY' if os.environ.get('META_API_KEY') else 'the settings'} ({len(key)} characters, not shown)\n")
    names = await check_key(base, key)
    if names is None:
        return 1
    passed = await check_language_model(base, key, model, settings.llm_reasoning_effort, names)
    passed = await check_speech_model(base, key, asr_model, keywords) and passed
    files = [Path(args.audio)] if args.audio else sorted(Path(args.dir).glob("*.wav")) if args.dir else []
    if files:
        passed = await hear_recordings(base, key, asr_model, keywords, files) and passed
    print("\nEvery check passed." if passed else "\nAt least one check did not pass: see the lines marked FAILED above.")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run(parser().parse_args())))
