"""Aurora serverless PG CFN resources — cluster, instance, master secret.

Engine version 16.13 (PG 16.x supports scale-to-0 ACU; 16.3+ required).
The cluster sits in the existing public subnet for MVP; locking it into
private subnets is a future hardening step (introduces NAT, changes
cost; out of scope here).
"""

from typing import Final

from src.cfn.persistence.aurora_bootstrap_resources import (
    DEFAULT_LAMBDA_RUNTIME,
    MASTER_USERNAME,
    PSYCOPG2_LAYER_ARN_TEMPLATE,
    aurora_bootstrap_resources,
)
from src.cfn.persistence.aurora_maintenance import (
    PARAMETER_GROUP,
    pg_cron_parameter_group,
)

# Pinned to a minor AWS still offers AND cfn-lint's catalog knows: 16.4 was withdrawn
# and every commercial CreateStack failed with "Cannot find version 16.4" (e2e,
# 2026-10-11). Before bumping, check both
# `aws rds describe-db-engine-versions --engine aurora-postgresql` and cfn-lint.
ENGINE_VERSION: Final[str] = "16.13"
SECONDS_UNTIL_AUTO_PAUSE: Final[int] = 300  # 5 min idle → auto-pause
DB_PASSWORD_PARAM: Final[str] = (
    "DbPassword"  # noqa: S105  # nosec B105 — a parameter name
)


# Per-variant Aurora slice sets. Commercial keeps document + vector
# (Tiger Cloud owns the timeseries slice). Defense adds timeseries (Aurora
# pg_partman absorbs telemetry). Both carry dercontrol — ems-der-control-api's
# own database in the shared cluster (device-api owns the document schema, so
# a second Hibernate ddl-auto tenant there would be a schema-ownership hazard).
COMMERCIAL_SLICES: Final[tuple[str, ...]] = ("document", "vector", "dercontrol")
DEFENSE_SLICES: Final[tuple[str, ...]] = (
    "document",
    "vector",
    "timeseries",
    "dercontrol",
)


def aurora_cluster_resources(
    lambda_runtime: str = DEFAULT_LAMBDA_RUNTIME,
    psycopg2_layer_arn_template: str | None = PSYCOPG2_LAYER_ARN_TEMPLATE,
    slices: tuple[str, ...] = COMMERCIAL_SLICES,
) -> dict[str, dict]:
    """CFN resources for a scale-to-0 Aurora serverless PG cluster.

    `slices` lists the per-variant database names the bootstrap Lambda must
    create. The custom resource receives the list as a CFN property; the
    Lambda branches on it. Defaults to commercial (`document + vector`).

    `psycopg2_layer_arn_template=None` omits the Layers field — the test
    deploy uses this because LocalStack community can't fetch shared layers
    from real AWS (Pro-only feature). Prod always sets the layer.
    """
    # Per-slice connection-URL secrets, CFN-native. Pre-creating them as
    # CFN resources (with a fixed placeholder) lets the stack OWN their
    # lifecycle — delete cleans automatically, no orphans. The bootstrap
    # Lambda overwrites the placeholder via PutSecretValue with the real
    # `postgres://master:pw@endpoint:5432/db` URL once the slice DB exists.
    #
    # Naming: `arcnode-ems-{STACK}/<slice>-url` — UserData curls these by
    # name into /opt/arcnode/secrets.env.
    slice_secrets = {
        f"AuroraSlice{slice_name.title()}Secret": {
            "Type": "AWS::SecretsManager::Secret",
            "Properties": {
                "Name": {
                    "Fn::Sub": (f"arcnode-ems-${{AWS::StackName}}/{slice_name}-url"),
                },
                "Description": (
                    f"Aurora {slice_name} slice connection URL "
                    "(populated by AuroraBootstrapLambda PutSecretValue)."
                ),
                "SecretString": "set by AuroraBootstrapLambda",
            },
        }
        for slice_name in slices
    }
    return {
        **slice_secrets,
        "AuroraMasterSecret": {
            "Type": "AWS::SecretsManager::Secret",
            "Properties": {
                "Description": "Aurora master password (the customer's DbPassword).",
                "SecretString": {"Ref": DB_PASSWORD_PARAM},
            },
        },
        "AuroraSubnetGroup": {
            "Type": "AWS::RDS::DBSubnetGroup",
            "Properties": {
                "DBSubnetGroupDescription": "Aurora serverless subnet group",
                "SubnetIds": [{"Ref": "EmsSubnet"}, {"Ref": "EmsSubnetB"}],
            },
        },
        "AuroraSecurityGroup": {
            "Type": "AWS::EC2::SecurityGroup",
            "Properties": {
                "GroupDescription": "Aurora serverless ingress (Postgres)",
                "VpcId": {"Ref": "EmsVpc"},
                "SecurityGroupIngress": [
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 5432,
                        "ToPort": 5432,
                        "SourceSecurityGroupId": {"Ref": "EmsSecurityGroup"},
                    }
                ],
            },
        },
        "AuroraCluster": {
            "Type": "AWS::RDS::DBCluster",
            "Properties": {
                "Engine": "aurora-postgresql",
                "EngineMode": "provisioned",
                "EngineVersion": ENGINE_VERSION,
                "MasterUsername": MASTER_USERNAME,
                "MasterUserPassword": {
                    "Fn::Sub": "{{resolve:secretsmanager:${AuroraMasterSecret}}}"
                },
                "DBSubnetGroupName": {"Ref": "AuroraSubnetGroup"},
                "VpcSecurityGroupIds": [{"Ref": "AuroraSecurityGroup"}],
                "ServerlessV2ScalingConfiguration": {
                    "MinCapacity": 0,
                    "MaxCapacity": 4,
                    "SecondsUntilAutoPause": SECONDS_UNTIL_AUTO_PAUSE,
                },
            },
        },
        "AuroraInstance": {
            "Type": "AWS::RDS::DBInstance",
            "Properties": {
                "DBClusterIdentifier": {"Ref": "AuroraCluster"},
                "DBInstanceClass": "db.serverless",
                "Engine": "aurora-postgresql",
                "EngineVersion": ENGINE_VERSION,
                **(
                    {"DBParameterGroupName": {"Ref": PARAMETER_GROUP}}
                    if "timeseries" in slices
                    else {}
                ),
            },
        },
        **(pg_cron_parameter_group(ENGINE_VERSION) if "timeseries" in slices else {}),
        **aurora_bootstrap_resources(
            lambda_runtime=lambda_runtime,
            psycopg2_layer_arn_template=psycopg2_layer_arn_template,
            slices=slices,
        ),
    }


def aurora_parameters() -> dict[str, dict]:
    """The customer's database password: Aurora's master login, and the password
    in every slice URL. One password, same as the on-prem Postgres page."""
    return {
        DB_PASSWORD_PARAM: {
            "Type": "String",
            "NoEcho": True,
            "MinLength": 8,
            "MaxLength": 128,
            # Reason: Aurora rejects / " @ and spaces in a master password.
            "AllowedPattern": '^[^/"@ ]+$',
            "ConstraintDescription": '8-128 characters, no / " @ or spaces.',
            "Description": "Database password for every EMS database.",
        },
    }
