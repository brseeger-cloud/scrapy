"""Email-address scrubbing.

The project must never collect or store email addresses. Every piece of text
taken from a web page passes through :func:`scrub_emails` before it is
analysed, and every value is checked again by the EmailScrubPipeline and the
Excel/CSV writers before it is written to disk.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[email removed]"

# Plain addresses: jane.smith@example.com.au
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")

# Common obfuscations: jane [at] example [dot] com, jane(at)example(dot)com.au
_AT = r"\s*(?:\[\s*at\s*\]|\(\s*at\s*\)|\{\s*at\s*\}|\s+at\s+)\s*"
_DOT = r"\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\}|\s+dot\s+)\s*"
_OBFUSCATED_RE = re.compile(
    rf"[A-Za-z0-9._%+\-]+{_AT}[A-Za-z0-9\-]+(?:{_DOT}[A-Za-z]{{2,}})+",
    re.IGNORECASE,
)

# URL-encoded "@" (e.g. inside a mailto link or tracking URL)
_ENCODED_RE = re.compile(r"[A-Za-z0-9._%+\-]+%40[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")


def scrub_emails(text: str) -> str:
    """Return *text* with anything that looks like an email address removed."""
    if not text:
        return text
    text = _EMAIL_RE.sub(REDACTED, text)
    text = _ENCODED_RE.sub(REDACTED, text)
    return _OBFUSCATED_RE.sub(REDACTED, text)


def contains_email(text: str) -> bool:
    if not text:
        return False
    return bool(_EMAIL_RE.search(text) or _ENCODED_RE.search(text) or _OBFUSCATED_RE.search(text))


def scrub_value(value: Any) -> Any:
    """Recursively scrub strings inside dicts, lists and tuples."""
    if isinstance(value, str):
        return scrub_emails(value)
    if isinstance(value, dict):
        return {k: scrub_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(scrub_value(v) for v in value)
    return value
