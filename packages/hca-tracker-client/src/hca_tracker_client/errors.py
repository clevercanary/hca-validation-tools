"""Errors whose messages are safe to show: no API token, no presigned URL."""

import re

_URL = re.compile(r"https?://\S+")


def redact(text: str, *secrets: str | None) -> str:
    """Remove URLs and the given secret values from text meant for the user.

    Presigned URLs carry their own credentials in the query string, so any URL
    that reaches a message is removed whole rather than trimmed.
    """
    text = _URL.sub("<url>", text)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    return text


class TrackerError(Exception):
    """Base class for errors raised by this package."""


class ConfigError(TrackerError):
    """Required configuration is missing or invalid."""


class AuthError(TrackerError):
    """The tracker rejected the API token."""


class SelectionError(TrackerError):
    """No atlas version or file matches the request."""


class CheckError(TrackerError):
    """A check before downloading failed; nothing was fetched."""


class JobError(TrackerError):
    """A download job does not exist or cannot be changed as asked."""
