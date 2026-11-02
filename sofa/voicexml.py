"""Voice XML builders for the telephony provider (Say, Play, Record, Redirect)."""

from xml.sax.saxutils import escape, quoteattr


def _wrap(body: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>'


def _plays(urls: list[str]) -> str:
    return "".join(f"<Play url={quoteattr(u)}/>" for u in urls)


def record(prompts: list[str], callback_url: str, timeout: int = 2, max_length: int = 15) -> str:
    """One turn: prompt audio nested in Record. No beep, trim silence, # ends early."""
    return _wrap(
        f'<Record finishOnKey="#" maxLength="{max_length}" timeout="{timeout}" trimSilence="true" '
        f'playBeep="false" callbackUrl={quoteattr(callback_url)}>{_plays(prompts)}</Record>'
    )


def play_and_hangup(prompts: list[str]) -> str:
    """Play then end the call (no Record follows)."""
    return _wrap(_plays(prompts))


def say_and_hangup(text: str) -> str:
    return _wrap(f"<Say>{escape(text)}</Say>")


def redirect(url: str, prompts: list[str] | None = None) -> str:
    return _wrap(f"{_plays(prompts or [])}<Redirect>{escape(url)}</Redirect>")
