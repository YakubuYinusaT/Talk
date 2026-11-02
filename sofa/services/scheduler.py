"""Background jobs, run inside the API process: recordings past their time are deleted, demonstration hospitals past their time are removed, and the follow-ups around a booked visit are sent.

Each job keeps its own record of what it has already done (the follow-ups mark every text they send), so two workers, a restart or a slow tick never repeat one.
"""

import asyncio
import logging

log = logging.getLogger("sofa.scheduler")


async def tick(svc) -> None:
    """One pass of every job."""
    from . import retention

    retention.run_if_due(svc)  # recordings past their time are deleted, about once an hour
    if getattr(svc, "onboarding", None):
        svc.onboarding.sweep()  # the hospitals visitors made in the onboarding wizard are removed when their 24 hours are up, with their secrets and their records
    if svc.orchestrator.adapter("health"):
        from ..health import followups

        await followups.run(svc)  # reminders before a booked visit, and a follow-up after it


async def loop(svc) -> None:
    """Tick forever; one bad tick must never stop the scheduler."""
    interval = svc.settings.scheduler_interval_seconds
    while True:
        try:
            await tick(svc)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(interval)
