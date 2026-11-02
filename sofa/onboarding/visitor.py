"""Who a visitor of the wizard is, without any account: a random identifier in a signed cookie.

The wizard gives each visitor a random identifier and a signature made with a key only the server holds. A hospital is shown to the visitor whose identifier it was made for,
and to nobody else, so that judges trying the demonstration at the same time never see or disturb each other's hospitals. The cookie holds no personal data.
"""

import hashlib
import hmac
import secrets

COOKIE = "talk_demo"


def _sign(visitor: str, key: str) -> str:
    return hmac.new(f"onboarding|{key}".encode(), visitor.encode(), hashlib.sha256).hexdigest()[:32]


def issue(key: str) -> tuple[str, str]:
    """A new visitor and the value of the cookie that proves it."""
    visitor = secrets.token_urlsafe(16)
    return visitor, f"{visitor}.{_sign(visitor, key)}"


def read(cookies, key: str) -> str | None:
    """The visitor a cookie proves, or None when there is no cookie or it was not made by this server."""
    value = (cookies or {}).get(COOKIE) or ""
    visitor, _, signature = value.partition(".")
    if visitor and signature and hmac.compare_digest(signature, _sign(visitor, key)):
        return visitor
    return None


def tag(visitor: str) -> str:
    """A short, one-way label of a visitor, used to recognise the conversations that visitor had (it is not the visitor's identifier)."""
    return hashlib.sha256(f"tag|{visitor}".encode()).hexdigest()[:8]
