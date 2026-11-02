from sqlalchemy.orm import Session

from ..models import Call, Handoff


async def open_handoff(db: Session, call: Call, reason: str, summary: str) -> Handoff:
    """Record a request Talk could not finish, so the people who follow up can see why."""
    h = Handoff(call_id=call.id, service_domain=call.service_domain, reason=reason, summary=summary)
    db.add(h)
    db.flush()
    call.handoff_id = h.id
    call.outcome = "handoff"
    return h
