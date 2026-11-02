"""The services Talk can route a caller to.

The caller never picks one from a menu: they say what they need and the first model call (the router) names the service domain. Each descriptor says how Talk
names the service aloud and what callers ask it for.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceDomain:
    key: str
    label: str          # how Talk names it aloud
    hint: str           # what callers say, shown to the router model
    provider_label: str | None = None  # how Talk names whoever follows up on an unresolved request; None = nobody to hand to


SERVICES: dict[str, ServiceDomain] = {
    s.key: s for s in (
        ServiceDomain("health", "health services", "a clinic, a hospital or a pharmacy near me, how long the queue is, booking or cancelling a health appointment, antenatal care, child immunisation, "
                      "a malaria test, whether a medicine is in stock", "the clinic"),
    )
}

CHAT = "chat"  # a greeting, thanks or small talk with no request in it: answered warmly, never counted as not understood
HUMAN, UNCLEAR = "human", "unclear"  # HUMAN: the caller asked for a person
DOMAIN_CHOICES = [*SERVICES, HUMAN, CHAT, UNCLEAR]
