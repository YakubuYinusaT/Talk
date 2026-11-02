"""Simulates a phone call from start to finish, with no telephony provider and no hosted models, so that the whole conversation can be tried at a desk.

    python -m scripts.simulate_call                          # interactive: type what the caller says
    python -m scripts.simulate_call --script calls/visit.txt  # a prepared conversation, one caller sentence per line

The simulator uses the same /voice/* addresses that the telephony provider calls, so the real callback code is exercised. Talk's replies are read from the
X-Sofa-Reply-Text header, which is present while DEBUG_HEADERS=true. A blank line simulates the caller staying silent.
"""

import argparse
import sys
import uuid

from fastapi.testclient import TestClient

from sofa.audio import mock_recording_url
from sofa.config import get_settings
from sofa.main import create_app


def run_call(client: TestClient, lines: list[str] | None, caller: str, dest: str, secret: str, echo=print) -> list[str]:
    """Places one call and returns everything Talk said, the greeting first. With lines=None the caller's sentences are typed at the terminal."""
    session_id = f"sim-{uuid.uuid4().hex[:8]}"
    replies: list[str] = []

    def show(resp):
        text = resp.headers.get("X-Sofa-Reply-Text", "")
        replies.append(text)
        echo(f"  Talk: {text}")
        return "<Record" in resp.text

    form = {"sessionId": session_id, "callerNumber": caller, "destinationNumber": dest, "isActive": "1"}
    active = show(client.post(f"/voice/inbound/{secret}", data={**form, "direction": "Inbound"}))
    lines_iter = iter(lines) if lines is not None else None
    while active:
        if lines_iter is not None:
            line = next(lines_iter, None)
        else:
            try:
                line = input("  You:  ")
            except EOFError:
                line = None
        if line is None:
            break
        echo(f"  You:  {line}")
        data = dict(form)
        if line.strip():  # a blank line is silence: no recording is sent
            data["recordingUrl"] = mock_recording_url(line)
        r = client.post(f"/voice/turn/{secret}", data=data)
        hops = 0
        while "<Redirect>" in r.text and hops < 12:  # a slow turn: holding messages play first, and then the real reply arrives
            held = r.headers.get("X-Sofa-Reply-Text", "")
            if held:
                echo(f"  Talk (holding): {held}")
            path = r.text.split("<Redirect>")[1].split("</Redirect>")[0].replace(get_settings().public_base_url, "")
            r = client.post(path, data={"sessionId": session_id})
            hops += 1
        active = show(r)
    client.post(f"/voice/events/{secret}", data={"sessionId": session_id, "isActive": "0", "durationInSeconds": "60"})
    return replies


def main() -> None:
    ap = argparse.ArgumentParser(description="Places a simulated phone call to Talk and prints what is said on both sides, using the settings in the environment.")
    ap.add_argument("--script", help="a text file with one sentence the caller says on each line; lines starting with # are ignored")
    ap.add_argument("--caller", default="+2348055550001", help="the phone number the simulated caller is calling from")
    ap.add_argument("--dest", default="", help="the number that was dialled; it defaults to TALK_NUMBER")
    args = ap.parse_args()
    settings = get_settings()
    app = create_app(settings)
    lines = None
    if args.script:
        lines = [line.rstrip("\n") for line in open(args.script, encoding="utf-8") if not line.startswith("#")]
    elif not sys.stdin.isatty():
        lines = [line.rstrip("\n") for line in sys.stdin]
    with TestClient(app) as client:
        run_call(client, lines, args.caller, args.dest or settings.talk_number, settings.at_callback_secret)


if __name__ == "__main__":
    main()
