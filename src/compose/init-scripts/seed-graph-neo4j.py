"""Seed the Neo4j graph (commercial Aura, ISO self-hosted) from the public dump.

The seed bundle is a gzipped tar of Cypher CREATE statements. The marker
lives as an :ArcnodeSeedMarker node in the graph itself — survives EC2
instance replacement.

Required env (from /opt/arcnode/persistence.env):
    GRAPH_URL — neo4j+s://user:pass@host:7687

The compose entry installs the `neo4j` driver before invoking this script
(no top-of-script subprocess.run shenanigans needed).
"""

import io
import os
import sys
import tarfile
import urllib.request

from neo4j import GraphDatabase

SEED_URL = "https://arcnode-public.s3.us-east-1.amazonaws.com/seed/graph-neo4j.tar.gz"


def already_seeded(driver) -> bool:
    """True if the marker node is already in the graph."""
    with driver.session() as s:
        record = s.run("MATCH (m:ArcnodeSeedMarker {slice: 'graph'}) RETURN m").single()
        return record is not None


def apply_seed(driver) -> None:
    """Stream the seed tarball, run each Cypher statement against the target."""
    with urllib.request.urlopen(SEED_URL) as resp:
        buf = io.BytesIO(resp.read())
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        member = tar.next()
        if member is None:
            raise RuntimeError("seed tarball is empty")
        extracted = tar.extractfile(member)
        if extracted is None:
            raise RuntimeError(f"seed entry {member.name!r} not extractable")
        body = extracted.read().decode()
    with driver.session() as s:
        for raw in body.split(";\n"):
            stmt = raw.strip()
            if stmt:
                s.run(stmt)


def write_marker(driver) -> None:
    """Stamp the marker node so re-runs short-circuit."""
    with driver.session() as s:
        s.run(
            "MERGE (m:ArcnodeSeedMarker {slice: 'graph'}) "
            "ON CREATE SET m.seeded_at = datetime()"
        )


def main() -> int:
    """Connect, short-circuit if seeded, else apply + stamp the marker."""
    url = os.environ["GRAPH_URL"]
    driver = GraphDatabase.driver(url)
    try:
        if already_seeded(driver):
            print("graph already seeded; exiting")
            return 0
        apply_seed(driver)
        write_marker(driver)
        print("graph seeded")
        return 0
    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
