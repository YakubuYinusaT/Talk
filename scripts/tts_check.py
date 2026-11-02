"""Does the hosted voice work from this machine? It speaks one short sentence and says what the voice service answered.

    python -m scripts.tts_check
    python -m scripts.tts_check --text "Your appointment is confirmed for tomorrow morning."

It prints the status of each answer and, when the service refused, the service's own message. The key is never printed, and it is removed from any
message the service sent back. The exit status is 0 when the voice answered and 1 when it did not.
"""

import argparse
import asyncio
import sys

import httpx

from sofa.config import get_settings

DEFAULT_TEXT = "Hello, this is a test of the voice."


async def run(text: str) -> int:
    settings = get_settings()
    if settings.tts_provider == "azure":
        return await run_azure(settings, text)
    key = settings.spitch_api_key
    print(f"voice provider: {settings.tts_provider}, English voice: {settings.spitch_voice_en}, speed {settings.tts_hosted_speed}, key {'set' if key else 'NOT SET'}")
    if not key:
        print("There is no key for the hosted voice, so there is nothing to test. Put SPITCH_API_KEY in the .env file and run this again.")
        return 1
    body = {"text": text, "language": "en", "voice": settings.spitch_voice_en, "speed": min(1.2, max(0.7, settings.tts_hosted_speed)), "format": "wav"}
    async with httpx.AsyncClient(base_url="https://api.spitch.app", timeout=60, headers={"Authorization": f"Bearer {key}"}) as http:
        for attempt in (1, 2, 3):
            try:
                resp = await http.post("/v1/speech", json=body)
            except httpx.HTTPError as exc:
                print(f"try {attempt}: the voice service could not be reached ({type(exc).__name__})")
                await asyncio.sleep(2)
                continue
            kind = resp.headers.get("content-type", "")
            detail = "" if resp.status_code == 200 else " | " + resp.text[:300].replace(key, "***")
            print(f"try {attempt}: HTTP {resp.status_code}, {kind}, {len(resp.content)} bytes{detail}")
            if resp.status_code == 200:
                print("The hosted voice is working.")
                return 0
            await asyncio.sleep(2)
    print("The hosted voice did not answer well. Talk would speak with the voice on this machine, or the silent stand-in, until it does.")
    return 1


async def run_azure(settings, text: str) -> int:
    """The same check for Microsoft Azure Speech: one sentence in the chosen Nigerian English voice."""
    from sofa.clients.tts import AzureTTS

    key, region = settings.azure_speech_key, settings.azure_speech_region
    print(f"voice provider: azure, voice: {settings.azure_voice}, region: {region or 'NOT SET'}, key {'set' if key else 'NOT SET'}")
    if not (key and region):
        print("Put AZURE_SPEECH_KEY and AZURE_SPEECH_REGION in the .env file and run this again.")
        return 1
    voice = AzureTTS(key, region, settings.azure_voice, settings.tts_hosted_speed)
    try:
        audio = await voice.synthesize(text, "en")
    except httpx.HTTPStatusError as exc:
        print(f"HTTP {exc.response.status_code} | {exc.response.text[:300].replace(key, '***')}")
        print("Azure refused. A 401 means the key or the region is wrong; the key only works in the region where the resource was made.")
        return 1
    except httpx.HTTPError as exc:
        print(f"Azure could not be reached ({type(exc).__name__}).")
        return 1
    print(f"HTTP 200, {len(audio)} bytes of audio. The Azure voice is working.")
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m scripts.tts_check", description="Speak one sentence with the hosted voice and report what the service answered. The key is never printed.")
    ap.add_argument("--text", default=DEFAULT_TEXT, help="the sentence to speak")
    return ap


if __name__ == "__main__":
    sys.exit(asyncio.run(run(parser().parse_args().text)))
