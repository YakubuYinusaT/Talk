"""Voice XML for the second telephony provider, Twilio, with the same functions as sofa/voicexml.py so that the call code does not care which provider
carries a call. Twilio plays the prompts first and then records, and it asks for the next instruction at the Record element's action address."""

from xml.sax.saxutils import escape, quoteattr


def _wrap(body: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>'


def _plays(urls: list[str]) -> str:
    return "".join(f"<Play>{escape(u)}</Play>" for u in urls)


def record(prompts: list[str], callback_url: str, timeout: int = 2, max_length: int = 15) -> str:
    """One turn: the prompts, then a recording of what the caller says. No beep, silence trimmed, # ends early."""
    return _wrap(f'{_plays(prompts)}<Record action={quoteattr(callback_url)} method="POST" finishOnKey="#" maxLength="{max_length}" '
                 f'timeout="{timeout}" trim="trim-silence" playBeep="false"/>')


def play_and_hangup(prompts: list[str]) -> str:
    """Play, then end the call."""
    return _wrap(f"{_plays(prompts)}<Hangup/>")


def say_and_hangup(text: str) -> str:
    return _wrap(f"<Say>{escape(text)}</Say><Hangup/>")


def redirect(url: str, prompts: list[str] | None = None) -> str:
    return _wrap(f'{_plays(prompts or [])}<Redirect method="POST">{escape(url)}</Redirect>')
