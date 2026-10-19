"""CFN Secrets Manager entries for broker + device-api auth.

Both variants get these (the broker runs File RBAC in every deployment).
The customer sets every value as a NoEcho parameter, the same values the
on-prem wizard asks for:

    mqtt-service-password   gateway, device-api, telemetry-writer, der-control-api → broker
    auth-jwt-secret         device-api HS256 session-token signing key
    auth-operator-pw        operator login, also the operator's broker password
    auth-viewer-pw          viewer login, also the viewer's broker password
    grafana-admin-pw        Grafana admin login

Plus two ops-populated placeholders (static content, overwritten per DERMS
integration): der-control-truststore-pem and der-control-lfdi-allowlist.

EC2 UserData fetches each by slot name into secrets.env (services consume) and,
for the broker passwords, also into credentials.xml (broker reads). See
AUTH_SLOTS in cfn_resources.py for the slot→env mapping.
"""

from typing import Final

from src.der_control_truststore import PLACEHOLDER_TRUSTSTORE_PEM
from src.customer_inputs import (
    GRAFANA_ADMIN,
    JWT_SECRET,
    OPERATOR_LOGIN,
    VIEWER_LOGIN,
)

MQTT_SERVICE_SLOT: Final[str] = "mqtt-service-password"
MQTT_SERVICE_PARAM: Final[str] = "MqttServicePw"
# device-api rejects a shorter HS256 key; the wizard asks for the same minimum.
JWT_SECRET_MIN_LENGTH: Final[int] = 32


def _param_secret(slot: str, param: str, description: str) -> dict:
    """A secret whose value is a !Ref to a NoEcho param (customer-pasted)."""
    return {
        "Type": "AWS::SecretsManager::Secret",
        "Properties": {
            "Name": {"Fn::Sub": f"arcnode-ems-${{AWS::StackName}}/{slot}"},
            "Description": description,
            "SecretString": {"Ref": param},
        },
    }


def auth_secrets() -> dict[str, dict]:
    """One secret per customer-set auth parameter."""
    return {
        "MqttServicePwSecret": _param_secret(
            MQTT_SERVICE_SLOT,
            MQTT_SERVICE_PARAM,
            "Broker password shared by the EMS services (gateway, device-api, telemetry-writer, der-control-api).",
        ),
        "AuthJwtSecretSecret": _param_secret(
            JWT_SECRET.slot,
            JWT_SECRET.cfn_param,
            "device-api HS256 session-token signing key.",
        ),
        "AuthOperatorPwSecret": _param_secret(
            OPERATOR_LOGIN.slot,
            OPERATOR_LOGIN.cfn_param,
            "Operator login and broker password (plaintext).",
        ),
        "AuthViewerPwSecret": _param_secret(
            VIEWER_LOGIN.slot,
            VIEWER_LOGIN.cfn_param,
            "Viewer login and broker password (plaintext).",
        ),
        "GrafanaAdminPwSecret": _param_secret(
            GRAFANA_ADMIN.slot,
            GRAFANA_ADMIN.cfn_param,
            "Grafana admin password (plaintext).",
        ),
    }


def der_control_lfdi_allowlist_secret() -> dict[str, dict]:
    """LFDIs allowed to POST DERControls, one list per deployment.

    Placeholder is 40 zeros: a valid LFDI shape no real cert produces, so the
    allowlist stays closed until ops PutSecretValue's the real list. Secrets
    Manager rejects an empty SecretString, and an unset one fails the UserData read.
    """
    return {
        "DerControlLfdiAllowlistSecret": {
            "Type": "AWS::SecretsManager::Secret",
            "Properties": {
                "Name": {
                    "Fn::Sub": "arcnode-ems-${AWS::StackName}/der-control-lfdi-allowlist"
                },
                "Description": (
                    "LFDIs allowed to POST DERControls (40 hex each, comma or "
                    "whitespace separated). Placeholder never matches a real cert. "
                    "Ops overwrites via PutSecretValue, then restarts der-control-api."
                ),
                "SecretString": "0" * 40,
            },
        },
    }


def der_control_truststore_secret() -> dict[str, dict]:
    """Placeholder Secrets Manager slot for der-control-ingress's mTLS
    truststore (the DERMS utility's CA bundle, PEM).

    Not `GenerateSecretString` (there's nothing to randomly generate here)
    and not a `!Ref` to a customer param (onboarding a real DERMS
    integration — which CA to trust — isn't part of the order-intake form
    today; that's a separate product decision). `aws secretsmanager
    put-secret-value` overwrites this with the real bundle once a specific
    integration is being stood up.
    """
    return {
        "DerControlTruststoreSecret": {
            "Type": "AWS::SecretsManager::Secret",
            "Properties": {
                "Name": {
                    "Fn::Sub": "arcnode-ems-${AWS::StackName}/der-control-truststore-pem"
                },
                "Description": (
                    "der-control-ingress mTLS truststore (DERMS CA bundle, "
                    "PEM). Placeholder — ops overwrites via PutSecretValue "
                    "per DERMS integration."
                ),
                "SecretString": PLACEHOLDER_TRUSTSTORE_PEM,
            },
        },
    }


def auth_parameters() -> dict[str, dict]:
    """NoEcho String params for every auth secret. NoEcho keeps them out of the
    Console and audit logs."""
    return {
        MQTT_SERVICE_PARAM: {
            "Type": "String",
            "NoEcho": True,
            "MinLength": 1,
            "Description": "Broker password the EMS services share.",
        },
        JWT_SECRET.cfn_param: {
            "Type": "String",
            "NoEcho": True,
            "MinLength": JWT_SECRET_MIN_LENGTH,
            "Description": f"Session-token signing key, at least {JWT_SECRET_MIN_LENGTH} characters.",
        },
        OPERATOR_LOGIN.cfn_param: {
            "Type": "String",
            "NoEcho": True,
            "MinLength": 1,
            "Description": "Operator login password (HMI dispatch role), also its broker password.",
        },
        VIEWER_LOGIN.cfn_param: {
            "Type": "String",
            "NoEcho": True,
            "MinLength": 1,
            "Description": "Viewer login password (HMI read-only role), also its broker password.",
        },
        GRAFANA_ADMIN.cfn_param: {
            "Type": "String",
            "NoEcho": True,
            "MinLength": 1,
            "Description": "Grafana admin password (observability dashboards).",
        },
    }
