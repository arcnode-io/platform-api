"""A cloud site's DNS name and callback token.

The hostname is `<site-slug>-<order-prefix>.arcnode.io`: the slug's underscores become
hyphens (not valid in hostnames) and the order prefix keeps two customers' identical site
names apart. The token is an HMAC of the order id, so the stack's UserData can prove it
belongs to that order without platform-api storing anything per order."""

import hashlib
import hmac
from typing import Final

DOMAIN: Final[str] = "arcnode.io"
# DNS labels are at most 63 characters; the suffix is "-" plus six characters.
ORDER_PREFIX_LENGTH: Final[int] = 6
MAX_LABEL: Final[int] = 63


def site_host_label(site_id: str, order_id: str) -> str:
    """The hostname's first label: slug (hyphenated, cut to fit) + order prefix."""
    suffix = f"-{order_id.replace('-', '')[:ORDER_PREFIX_LENGTH]}"
    slug = site_id.replace("_", "-").strip("-")
    return f"{slug[: MAX_LABEL - len(suffix)].rstrip('-')}{suffix}"


def site_hostname(site_id: str, order_id: str) -> str:
    """The full DNS name the customer reaches the box at."""
    return f"{site_host_label(site_id, order_id)}.{DOMAIN}"


def site_token(secret: str, order_id: str) -> str:
    """The callback token for one order."""
    return hmac.new(secret.encode(), order_id.encode(), hashlib.sha256).hexdigest()


def token_matches(secret: str, order_id: str, token: str) -> bool:
    """Constant-time check that `token` is this order's token."""
    return hmac.compare_digest(site_token(secret, order_id), token)
