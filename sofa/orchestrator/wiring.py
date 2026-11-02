"""This module builds the orchestrator, which holds the service adapters that are switched on and the tool registry that is made from their tools."""

from . import registry, understanding
from .adapters import ServiceAdapter
from .adapters.health import HealthAdapter
from .tools import ToolRegistry


class Orchestrator:
    def __init__(self, adapters: list[ServiceAdapter]):
        self.tools = ToolRegistry()
        self._adapters: dict[str, ServiceAdapter] = {}
        for adapter in adapters:
            self._adapters[adapter.domain] = adapter
            for tool in adapter.tools():
                self.tools.register(tool)

    def domains(self) -> list[str]:
        return list(self._adapters)

    def adapter(self, domain: str | None) -> ServiceAdapter | None:
        return self._adapters.get(domain) if domain else None

    # ---- what the router and the model can choose from -----------------------------------------

    def service(self, domain: str | None):
        """How Talk describes a service: its registered descriptor."""
        return registry.SERVICES.get(domain) if domain else None

    def domain_choices(self) -> list[str]:
        return [*registry.DOMAIN_CHOICES, *[d for d in self._adapters if d not in registry.DOMAIN_CHOICES]]

    def extra_domains(self) -> list[str]:
        """Registered services the model may name that are not one of its fixed choices: the health service."""
        return [d for d in self._adapters if d not in understanding.SPECIAL]

    def voice_tools(self) -> dict[str, str]:
        """tool id -> its service, for every tool the model may name as the caller's action."""
        return {t.tool_id: "health" for t in self.tools.for_domain("health")}

    def authorize(self, tool_id: str, params: dict | None = None):
        """May this call run this tool right now?"""
        return self.tools.authorize(tool_id, params)


ADAPTERS = {"health": HealthAdapter}


def enabled_services(settings=None) -> list[str]:
    """The services switched on, in the order they are registered."""
    wanted = [x.strip() for x in (getattr(settings, "services_enabled", None) or ",".join(ADAPTERS)).split(",") if x.strip()]
    return [k for k in ADAPTERS if k in wanted]


def build_orchestrator(settings=None) -> Orchestrator:
    return Orchestrator([ADAPTERS[k]() for k in enabled_services(settings)])
