"""Service adapters: how Sofa's common voice layer talks to one kind of service (the health front desk, the information search).

An adapter declares its tools (so the registry knows what exists and how risky each is) and, for a service that holds a conversation of its own, takes over
the turns once the caller is inside it. The orchestrator never reaches into a provider directly: it goes through the adapter, and the adapter's tools go through
the registry.
"""

from ..tools import Tool


class ServiceAdapter:
    domain: str = ""

    def tools(self) -> list[Tool]:
        return []

    def holds_session(self, st: dict) -> bool:
        """The caller is already inside this service, so a turn the router cannot place is probably meant for it."""
        return False

    async def turn(self, gw, transcript: str, confidence: float):
        raise NotImplementedError

    async def resolve_pending(self, gw, pending: dict, transcript: str):
        return None
