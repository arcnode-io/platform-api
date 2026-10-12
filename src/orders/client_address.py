"""The client address the rate limit keys on."""

UNKNOWN_CLIENT = "unknown"


def client_address(forwarded_for: str | None, fallback: str | None) -> str:
    """The rightmost X-Forwarded-For entry (appended by Caddy, the one hop we trust), else the
    socket address, else one shared bucket."""
    if forwarded_for:
        return forwarded_for.split(",")[-1].strip()
    return fallback or UNKNOWN_CLIENT
