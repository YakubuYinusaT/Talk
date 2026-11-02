"""Who is asking, for the providers that only some callers may see.

The four simulated providers are shown to every caller. A hospital made in the onboarding wizard is shown only to the visitor who made it, and to the phone number
that visitor gave with their consent. The health front desk asks this module whose turn it is, so that the list of providers it asks is the right one for that caller and
no other. The value follows the turn through every task the turn starts, and is put back to nothing when the turn ends.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class Asker:
    visitor: str | None = None   # the signed visitor of the wizard, for a conversation typed in the browser
    phone: str | None = None     # the caller's phone number, for a call


_current: ContextVar[Asker] = ContextVar("health_asker", default=Asker())


def current() -> Asker:
    return _current.get()


@contextmanager
def asking(visitor: str | None = None, phone: str | None = None):
    """Everything asked of the providers inside this block is asked on behalf of this visitor and this phone number."""
    token = _current.set(Asker(visitor, phone))
    try:
        yield
    finally:
        _current.reset(token)
