"""Runs one follow-up pass by hand: reminders for the visits that are coming up, and a thank-you text or a gentle "we missed you" text for the visits that have passed.

    python -m scripts.health_followups

The server does this by itself every few minutes, so this script is only for a demonstration or a check. It uses the same settings as the server: when no SMS key is set
the texts are only written to the log, and when a key is set the texts are really sent.
"""

import asyncio

from sofa.config import get_settings
from sofa.container import build_services
from sofa.db import make_engine, make_session_factory
from sofa.health import followups
from sofa.health.links import specs_from_settings


async def main() -> None:
    s = get_settings()
    svc = build_services(s, make_session_factory(make_engine(s.database_url)))
    health = svc.orchestrator.adapter("health")
    if health:
        health.set_providers(specs_from_settings(s))
    print("The text messages are only logged and none are sent." if s.sms_is_mock else "The text messages are really being sent, because an SMS key is set.")
    print(await followups.run(svc))


if __name__ == "__main__":
    asyncio.run(main())
