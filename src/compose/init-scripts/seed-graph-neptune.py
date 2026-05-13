"""Seed the Neptune graph (defense variant) via the Bulk Loader REST API.

Neptune Bulk Loader pulls CSV directly from S3 — boto3 just kicks off
the job and polls until it terminates. Marker lives as an
ArcnodeSeedMarker openCypher node in the graph itself; survives EC2
instance replacement.

Required env (from /opt/arcnode/persistence.env):
    NEPTUNE_HOST              — cluster endpoint hostname (IAM-auth)
    NEPTUNE_LOADER_ROLE_ARN   — role Neptune assumes to read S3 seed CSV

The compose entry installs `boto3` before invoking this script.
"""

import os
import sys
import time

import boto3

NEPTUNE_PORT = 8182
SEED_S3_PREFIX = "s3://arcnode-public/seed/graph-neptune/"
POLL_INTERVAL_SECONDS = 5


def already_seeded(client) -> bool:
    """True when the ArcnodeSeedMarker node exists."""
    result = client.execute_open_cypher_query(
        openCypherQuery="MATCH (m:ArcnodeSeedMarker {slice: 'graph'}) RETURN m"
    )
    return bool(result.get("results"))


def apply_seed(client) -> None:
    """Kick off the bulk load + poll until it lands."""
    load = client.start_loader_job(
        source=SEED_S3_PREFIX,
        format="csv",
        iamRoleArn=os.environ["NEPTUNE_LOADER_ROLE_ARN"],
        s3BucketRegion="us-east-1",
        mode="AUTO",
        failOnError="TRUE",
    )
    load_id = load["payload"]["loadId"]
    print(f"started Neptune bulk load: {load_id}")
    while True:
        status = client.get_loader_job_status(loadId=load_id)
        overall = status["payload"]["overallStatus"]["status"]
        if overall == "LOAD_COMPLETED":
            print("bulk load complete")
            return
        if overall == "LOAD_FAILED":
            raise RuntimeError(f"Neptune bulk load failed: {status}")
        time.sleep(POLL_INTERVAL_SECONDS)


def write_marker(client) -> None:
    """Stamp the marker node so re-runs short-circuit."""
    client.execute_open_cypher_query(
        openCypherQuery=(
            "MERGE (m:ArcnodeSeedMarker {slice: 'graph'}) "
            "ON CREATE SET m.seeded_at = datetime()"
        )
    )


def main() -> int:
    """Build a client, short-circuit if seeded, else apply + stamp the marker."""
    host = os.environ["NEPTUNE_HOST"]
    client = boto3.client("neptunedata", endpoint_url=f"https://{host}:{NEPTUNE_PORT}")
    if already_seeded(client):
        print("graph already seeded; exiting")
        return 0
    apply_seed(client)
    write_marker(client)
    print("graph seeded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
