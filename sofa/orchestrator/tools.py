"""The tool registry: the one list of things Talk is allowed to do for a caller.

Every operation a service offers is registered here. The model only ever picks an operation; nothing outside this list can run. This is how Talk stays a
medium: the provider's system does the work and stays the source of truth.
"""

from dataclasses import dataclass

RISKS = ("informational", "service")


@dataclass(frozen=True)
class Tool:
    tool_id: str                  # service.operation, for example health.find_facility
    domain: str
    description: str
    risk: str = "informational"   # one of RISKS
    required: tuple[str, ...] = ()  # parameters the caller must give before it can run

    def __post_init__(self):
        if self.risk not in RISKS:
            raise ValueError(f"{self.tool_id}: unknown risk {self.risk!r}")
        if "." not in self.tool_id:
            raise ValueError(f"{self.tool_id}: a tool id looks like service.operation")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""  # unregistered | missing:<parameter>


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.tool_id in self._tools:
            raise ValueError(f"tool {tool.tool_id} is already registered")
        self._tools[tool.tool_id] = tool

    def get(self, tool_id: str) -> Tool | None:
        return self._tools.get(tool_id)

    def for_domain(self, domain: str) -> list[Tool]:
        return [t for t in self._tools.values() if t.domain == domain]

    def authorize(self, tool_id: str, params: dict | None = None) -> Decision:
        """May this operation run now? It must be registered and have every parameter it needs."""
        tool = self.get(tool_id)
        if not tool:
            return Decision(False, "unregistered")
        for name in tool.required:
            if (params or {}).get(name) in (None, ""):
                return Decision(False, f"missing:{name}")
        return Decision(True)
