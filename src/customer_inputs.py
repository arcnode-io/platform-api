"""Customer-entered values, defined once.

The cloud's CFN template asks for these at stack create; the on-prem wizard
asks for them on a page. Both read the same slot and env names from here, so
a rename happens in one place.
"""

from typing import Final, NamedTuple


class CustomerSecret(NamedTuple):
    """One value the customer sets: where it's stored, what the container reads it as."""

    slot: str  # Secrets Manager name under arcnode-ems-<stack>/
    env_name: str  # the variable compose reads from secrets.env
    cfn_param: str  # the NoEcho stack parameter the cloud asks for


OPERATOR_LOGIN: Final[CustomerSecret] = CustomerSecret(
    "auth-operator-pw", "AUTH_OPERATOR_PW", "AuthOperatorPw"
)
VIEWER_LOGIN: Final[CustomerSecret] = CustomerSecret(
    "auth-viewer-pw", "AUTH_VIEWER_PW", "AuthViewerPw"
)
GRAFANA_ADMIN: Final[CustomerSecret] = CustomerSecret(
    "grafana-admin-pw", "GF_SECURITY_ADMIN_PASSWORD", "GrafanaAdminPw"
)
JWT_SECRET: Final[CustomerSecret] = CustomerSecret(
    "auth-jwt-secret", "AUTH_JWT_SECRET", "AuthJwtSecret"
)


class CustomerSetting(NamedTuple):
    """One non-secret value the customer sets, with the default both installs offer."""

    cfg_key: str  # the key in the service's cfg.customer.yml
    cfn_param: str  # the stack parameter the cloud asks for
    default: int


# How many days of measurements telemetry-writer keeps.
TELEMETRY_RETENTION_DAYS: Final[CustomerSetting] = CustomerSetting(
    "retention_days", "TelemetryRetentionDays", 7
)
