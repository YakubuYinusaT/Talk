"""Secrets that ship with the code are known to everyone who reads it. On an address people can reach they must never be the secret that guards anything."""

import hmac
import ipaddress
import logging
import secrets

log = logging.getLogger("sofa.hardening")

# setting -> the value it has when nobody set it
KNOWN_DEFAULTS = {"at_callback_secret": "dev-secret"}


def public_address(settings) -> bool:
    return str(settings.public_base_url).startswith("https://")


def replace_known_defaults(settings) -> list[str]:
    """On an https address, any secret still at its published default is replaced by a random one for this run, so nothing is guarded by a known value. What it guards
    (the call callback address) then stays shut until the real one is set in the settings. Returns the names that were replaced."""
    if not public_address(settings):
        return []
    replaced = []
    for name, default in KNOWN_DEFAULTS.items():
        if getattr(settings, name) == default:
            setattr(settings, name, secrets.token_urlsafe(24))
            replaced.append(name.upper())
    if replaced:
        log.error("these settings are still at the value published with the code, so they were replaced by a random one for this run: %s. Set them in .env.", ", ".join(replaced))
    return replaced


def source_address(request) -> str:
    """Who is calling. Behind the web server in front of the app, the real address is the last one that server appended to X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for", "")
    last = forwarded.split(",")[-1].strip() if forwarded else ""
    return last or (request.client.host if request.client else "")


def from_allowed_network(request, networks: str) -> bool:
    """True when no networks are set, or when the request comes from one of them."""
    blocks = [b.strip() for b in (networks or "").split(",") if b.strip()]
    if not blocks:
        return True
    try:
        address = ipaddress.ip_address(source_address(request))
    except ValueError:
        return False
    return any(address in ipaddress.ip_network(b, strict=False) for b in blocks)


def callback_allowed(request, secret: str) -> bool:
    """A telephony callback is accepted only with the right secret in its address, compared in constant time, and, when the providers' networks are set,
    only from one of them."""
    settings = request.app.state.svc.settings
    if not hmac.compare_digest(str(secret), str(settings.at_callback_secret)):
        return False
    if not from_allowed_network(request, settings.callback_allowed_networks):
        log.warning("a telephony callback from an address outside the allowed networks was refused")
        return False
    return True
