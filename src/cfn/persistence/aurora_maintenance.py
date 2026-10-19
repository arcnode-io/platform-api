"""pg_cron for the timeseries slice: pg_partman's hourly maintenance makes the
next partitions and drops the ones past the customer's retention window."""

from typing import Final

PARAMETER_GROUP: Final[str] = "AuroraParameterGroup"
# Reason: setting the list replaces Aurora's default, so keep pg_stat_statements.
PRELOAD_LIBRARIES: Final[str] = "pg_stat_statements,pg_cron"


def pg_cron_parameter_group(engine_version: str) -> dict[str, dict]:
    """A DB parameter group that preloads pg_cron. shared_preload_libraries is
    static, so it has to be on the instance from the start."""
    major = engine_version.split(".")[0]
    return {
        PARAMETER_GROUP: {
            "Type": "AWS::RDS::DBParameterGroup",
            "Properties": {
                "Description": "Preloads pg_cron for pg_partman maintenance",
                "Family": f"aurora-postgresql{major}",
                "Parameters": {"shared_preload_libraries": PRELOAD_LIBRARIES},
            },
        },
    }
