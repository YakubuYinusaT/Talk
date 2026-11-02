"""Shows what happened to the text messages the server sent, and sends one test message.

    python -m scripts.sms_check --recent
    python -m scripts.sms_check +2348012345678

--recent lists the last 25 texts the server sent: when, what kind, to which number (only the last four digits), and the status the text message provider
gave (sent, delivered, failed or rejected). A phone number sends one test message and says why it was refused when it was.
The script reads the same settings as the server (AT_USERNAME, AT_API_KEY, AT_SANDBOX and SMS_SENDER_ID from the .env file) and never prints the key.
The exit status is 0 when the listing was shown or the test message was accepted, and 1 otherwise.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from sofa.clients.sms import SMSClient
from sofa.config import get_settings
from sofa.db import make_engine, make_session_factory
from sofa.models import Notification


def settings_line(s) -> str:
    return f"user {s.at_username!r}, {'sandbox' if s.at_sandbox else 'live'}, key {'set' if s.at_api_key else 'NOT SET'}, sender id {s.sms_sender_id or '(none: the default is used)'}"


def recent() -> int:
    s = get_settings()
    print(settings_line(s))
    with make_session_factory(make_engine(s.database_url))() as db:
        rows = db.scalars(select(Notification).where(Notification.channel == "sms").order_by(Notification.created_at.desc()).limit(25)).all()
    if not rows:
        print("No texts have been recorded yet.")
    for r in rows:
        print(f"{r.created_at:%d %b %H:%M}  {r.template:<18} to ...{r.to_number[-4:]}  {r.status:<9} {r.provider_message_id or '(no message id)'}")
    return 0


async def send(to: str) -> int:
    s = get_settings()
    print(settings_line(s))
    status, message_id, reason = await SMSClient(s).deliver(to, "Talk: this is a test message from the Talk server.")
    print(f"result: {status}; {reason}" + (f"; message id {message_id}" if message_id else ""))
    return 0 if status == "sent" else 1


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m scripts.sms_check", description="List the texts the server sent, or send one test message. The key is never printed.")
    ap.add_argument("number", nargs="?", help="a phone number in international form, such as +2348012345678, to send one test message to")
    ap.add_argument("--recent", action="store_true", help="list the last 25 texts the server sent")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = parser()
    args = ap.parse_args(argv)
    if args.recent and not args.number:
        return recent()
    if args.number and not args.recent and args.number.startswith("+"):
        return asyncio.run(send(args.number))
    ap.error("please give either --recent, or one phone number that starts with + and the country code, such as +2348012345678")
    return 2


if __name__ == "__main__":
    sys.exit(main())
