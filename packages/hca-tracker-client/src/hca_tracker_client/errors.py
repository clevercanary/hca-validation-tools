import re

_URL = re.compile(r"https?://\S+")


def redact(text: str, *secrets: str | None) -> str:
    """Remove every URL (a presigned one carries credentials) and the given secrets, so text is safe to show."""
    text = _URL.sub("<url>", text)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    return text


class TrackerError(Exception):
    pass


class ConfigError(TrackerError):
    """HCA_TRACKER_* configuration is missing or invalid."""


class AuthError(TrackerError):
    """The tracker rejected the API token (401) or the request (403)."""


class SelectionError(TrackerError):
    """No atlas version or file matches the request."""


class CheckError(TrackerError):
    """A check before downloading failed; nothing was fetched."""


class JobError(TrackerError):
    """A download job does not exist, or cannot be changed as asked."""
