"""What Sofa remembers about a person from one call to the next.

A person is recognised by the number they call from or, in the browser, by a random identifier in a signed cookie (sofa/onboarding/visitor.py). Neither is
stored here: each is turned into a one-way key with a secret only the server holds, so this table never holds a phone number. What is kept is only what saves the
caller from saying it again: the area they are in or travel from, and the clinic where Sofa last booked them. Never why they needed care. It is forgotten after
CALLER_MEMORY_DAYS without a call, and nothing is kept when that setting is 0.
"""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CallerMemory

KEPT = ("origin", "area", "place")


def key_for(kind: str, who: str, secret: str) -> str:
    """The one-way key for a phone number (kind "phone") or a browser visitor (kind "visitor")."""
    return hmac.new(f"caller-memory|{secret}".encode(), f"{kind}|{who}".encode(), hashlib.sha256).hexdigest()


def load(db: Session, key: str, days: int) -> dict:
    """What is remembered for this key, or nothing when it is older than `days` or memory is off."""
    if not key or days <= 0:
        return {}
    row = db.scalar(select(CallerMemory).where(CallerMemory.key == key))
    if not row:
        return {}
    seen = row.updated_at if row.updated_at.tzinfo else row.updated_at.replace(tzinfo=timezone.utc)
    if seen < datetime.now(timezone.utc) - timedelta(days=days):
        db.delete(row)
        return {}
    try:
        data = json.loads(row.data or "{}")
    except ValueError:
        return {}
    return {k: v for k, v in data.items() if k in KEPT and isinstance(v, str) and v}


def keep(db: Session, key: str, days: int, **facts) -> None:
    """Add to what is remembered for this key. Only the kept facts are stored; anything else is ignored."""
    if not key or days <= 0:
        return
    fresh = {k: v for k, v in facts.items() if k in KEPT and isinstance(v, str) and v}
    if not fresh:
        return
    row = db.scalar(select(CallerMemory).where(CallerMemory.key == key))
    if row is None:
        row = CallerMemory(key=key, data="{}")
        db.add(row)
    try:
        data = json.loads(row.data or "{}")
    except ValueError:
        data = {}
    data.update(fresh)
    row.data = json.dumps(data)
    row.updated_at = datetime.now(timezone.utc)
