"""Render an EMQX rule HOCON template with parsed Postgres connection fields.

EMQX 5.x's Postgres connector takes ``server``, ``database``, ``username``,
``password`` as separate fields — it does not accept a single ``url``.
This script bridges the gap: read ``TIMESERIES_URL`` from env, parse it
with ``urllib.parse``, render the HOCON template, write the final file
to the emqx config volume.

Used by the ``emqx-rule-render`` init container in both the commercial
and defense variant compose files. Runs once at ``docker compose up``;
``restart: "no"`` keeps it from re-running on reboot.

Env contract (set by docker-compose ``env_file: /opt/arcnode/persistence.env``):
    TIMESERIES_URL   - postgres://user:pass@host:port/dbname[?...]
    TEMPLATE_PATH    - path to the variant's HOCON template (read-only mount)
    OUTPUT_PATH      - where to write the rendered HOCON (emqx-mounted volume)
"""

import os
import sys
from urllib.parse import urlparse


def render(template: str, *, timeseries_url: str) -> str:
    """Substitute ``{host} {port} {user} {password} {db}`` from a Postgres URL."""
    u = urlparse(timeseries_url)
    if u.scheme != "postgres" and u.scheme != "postgresql":
        raise ValueError(
            f"unexpected scheme {u.scheme!r}; expected postgres / postgresql"
        )
    if not u.hostname or not u.username or u.password is None:
        raise ValueError("TIMESERIES_URL must include host, username, and password")
    db = (u.path or "").lstrip("/")
    if not db:
        raise ValueError("TIMESERIES_URL must include a database name in the path")
    return template.format(
        host=u.hostname,
        port=u.port or 5432,
        user=u.username,
        password=u.password,
        db=db,
    )


def main() -> int:
    """Read env, render template, write output. Exits non-zero on failure."""
    try:
        template_path = os.environ["TEMPLATE_PATH"]
        output_path = os.environ["OUTPUT_PATH"]
        timeseries_url = os.environ["TIMESERIES_URL"]
    except KeyError as e:
        print(f"missing required env var: {e}", file=sys.stderr)
        return 1

    with open(template_path) as f:
        template = f.read()
    rendered = render(template, timeseries_url=timeseries_url)
    with open(output_path, "w") as f:
        f.write(rendered)
    print(f"rendered {template_path} -> {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
