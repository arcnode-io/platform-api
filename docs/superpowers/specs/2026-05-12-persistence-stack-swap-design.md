# Persistence Stack Swap — Design

**Date:** 2026-05-12
**Source of truth:** `ems/system_adr.md` §7
**Status:** Locked, awaiting implementation plan.

## Goal

Replace the current single-stack (Aurora + Tiger Cloud + Neo4j Aura) per-order
CFN persistence section with two variants chosen at template-render time by
`DeploymentContext`:

- **Commercial** — Aurora (document + vector) + Tiger Cloud + Neo4j Aura.
  Customer pastes 2 connection URLs into CFN parameters. ~$65–$95/mo idle.
- **Defense** (sovereign_government, defense_forward) — Aurora (document +
  vector + timeseries via pg_partman) + Neptune Serverless + AOSS.
  Zero customer-supplied parameters. ~$480/mo idle.

## Constraints

1. **Zero customer ops on the defense path.** Customer runs `aws cloudformation
   create-stack` once. No manual instance creation, no console clicks.
2. **Two connection-string params on the commercial path.** No OAuth flows, no
   Lambda vendor provisioners — just paste-the-URL ergonomics.
3. **Same connection-string-via-Secrets-Manager pattern as today.** UserData
   fetches, docker-compose sources. No code changes in the EC2 boot path
   beyond renaming secret slots.
4. **Idempotent bootstrap.** Lambda retries should not double-create databases
   or duplicate secrets.
5. **Single AZ, no redundancy.** Demo grade. All redundancy knobs
   CFN-parameterized so a paying customer can crank them up.
6. **Aurora bootstrap Lambda schema is hardcoded SQL strings** in
   `aurora_bootstrap.py`. Two parent tables; no YAML schema config.

## Variant Matrix

| Slice | Commercial | Defense |
|---|---|---|
| Document | Aurora (`ems_document` db) | Aurora (`ems_document` db) |
| Vector | Aurora (`ems_vector` db, `pgvector` ext) | Aurora (`ems_vector` db, `pgvector` ext) |
| Time series | **Tiger Cloud** (customer URL) | Aurora (`ems_timeseries` db, `pg_partman` ext) |
| Graph | **Neo4j Aura** (customer URL) | **Neptune Serverless** |
| Graph FTS | Aura native | **AOSS** (SEARCH, standby OFF) |
| Object | S3 (shared) | S3 (shared) |
| Ingest | EMQX rule engine → Tiger over SQL | EMQX rule engine → Aurora over SQL |

## CFN Parameters

### Commercial template

Required:
- `TigerCloudConnectionUrl` — `postgres://user:pass@host:port/db?sslmode=require`
- `Neo4jAuraConnectionUrl` — `neo4j+s://host:7687` plus credentials inline

Optional (with defaults targeting cheapest demo footprint):
- `AuroraMinAcu` (default `0`)
- `AuroraMaxAcu` (default `1`)
- `MeasurementsRetentionDays` (default `7`) — applies to Aurora pg_partman if
  the operator opts in to a future "commercial w/ Aurora timeseries" hybrid.
  No-op when timeseries lives in Tiger.

### Defense template

Required: none.

Optional:
- `AuroraMinAcu` (default `0`)
- `AuroraMaxAcu` (default `1`)
- `MeasurementsRetentionDays` (default `7`)
- `StatusRetentionDays` (default `30`)
- `NeptuneNcu` (default `1` — the floor; can crank up for production)
- `AossStandbyEnabled` (default `false`)

## Routing

Template selection happens in `CfnService.render_template` based on
`DeploymentContext`:

```python
if payload.deployment_context == DeploymentContext.COMMERCIAL:
    persistence = CommercialPersistence(...)
else:  # SOVEREIGN_GOVERNMENT or DEFENSE_FORWARD
    persistence = DefensePersistence(...)
```

`PersistenceService` becomes a thin discriminator. Each variant builds its
own CFN resource block and parameter set.

## File Layout

```
src/cfn/persistence/
  __init__.py
  persistence_module.py
  persistence_service.py         (discriminator only)
  commercial/
    __init__.py
    aurora_resources.py          (doc+vector only, no pg_partman, no timeseries db)
    persistence.py               (CommercialPersistence class — aurora bootstrap + 2 connection-string secrets)
  defense/
    __init__.py
    aurora_resources.py          (doc+vector+timeseries, pg_partman)
    neptune_resources.py         (NEW)
    aoss_resources.py            (NEW)
    persistence.py               (DefensePersistence class — aurora + neptune + aoss bootstrap)
  lambda_code/
    aurora_bootstrap.py          (handles both: parameterized on which dbs to create)
```

Existing `tiger_resources.py` + `aura_resources.py` get deleted. Their Lambda
code under `lambda_code/` follows.

## Aurora Bootstrap Lambda

One Lambda, parameterized via CFN custom-resource properties on which slices
to bootstrap:

```yaml
AuroraBootstrapCustomResource:
  Type: Custom::AuroraBootstrap
  Properties:
    ServiceToken: !GetAtt AuroraBootstrapLambda.Arn
    AuroraClusterEndpoint: !GetAtt AuroraCluster.Endpoint.Address
    AuroraMasterSecretArn: !Ref AuroraMasterSecret
    Slices:
      - document
      - vector
      # commercial: stops here
      # defense: also includes timeseries
      - timeseries
```

Lambda:
1. Connects to Aurora cluster with master credentials from Secrets Manager
2. For each slice, runs `CREATE DATABASE IF NOT EXISTS <slice>_db`
3. For `vector`: `CREATE EXTENSION IF NOT EXISTS vector`
4. For `timeseries`: `CREATE EXTENSION IF NOT EXISTS pg_partman`, then hardcoded
   SQL creates parent `measurements` + `status` tables, registers them with
   `partman.create_parent(...)`, sets retention
5. Writes a per-slice connection string secret (`AuroraDocumentSecret`,
   `AuroraVectorSecret`, `AuroraTimeseriesSecret` where applicable)

All idempotent: `IF NOT EXISTS`, `partman.create_parent` checks for prior
registration, `secretsmanager:PutSecretValue` overwrites.

## Connection-string Secrets

Standardized names per slice, regardless of variant:

```
ems-{stack-uuid}/document   → Aurora doc db connection
ems-{stack-uuid}/vector     → Aurora vector db connection
ems-{stack-uuid}/timeseries → Aurora timeseries db (defense) OR Tiger (commercial)
ems-{stack-uuid}/graph      → Neptune endpoint (defense) OR Aura URL (commercial)
ems-{stack-uuid}/aoss       → AOSS endpoint (defense only — absent on commercial)
```

EC2 UserData fetches by slot name. Consumers never know which variant they're
running on; they read `ems-.../graph` and pass it through.

## Test Coverage

### Layer 1: CFN structural deploy (every push)

`tests/test_cfn_deploy.py` extends to two parametrized cases:

- Commercial: pass valid-shape Tiger + Aura connection-string params, assert
  Aurora resources + 2 secrets reach CREATE_COMPLETE. AuroraBootstrap custom
  resource reaches CREATE_COMPLETE (it has real Aurora to talk to).
- Defense: no params, assert Aurora + Neptune + AOSS resources reach
  CREATE_COMPLETE. Bootstrap Lambda CREATE_COMPLETE.

LocalStack Pro: Aurora works, Neptune is Ultimate-tier (not Pro), AOSS is
backlog. The defense smoke for Neptune+AOSS will likely fail at resource
creation against current LocalStack Pro. Accept the gap; mark
`test_cfn_deploy_defense` as `skipif` on `LOCALSTACK_TIER != "ultimate"`.

### Layer 2 + 3: real-AWS test stack (pre-release)

Pre-release run spins up a real AWS test stack, runs python-mcp-server's
`GraphitiClient.search()` against the live endpoints, tears down. ~$1–3 per
run. Not in main CI.

## python-mcp-server Driver Abstraction

Out of scope of this repo, but spec calls for:

- Tagged-union `GraphBackend = Neo4jBackend | NeptuneBackend` discriminated on
  `kind`
- `GraphitiClient.from_backend(backend, password)` factory returns a
  `GraphitiClient` wrapping the appropriate `Graphiti` instance:
  - `Neo4jBackend` → wraps `Graphiti(uri, user, password)` (Aura URL works as
    standard `neo4j+s://` URI)
  - `NeptuneBackend` → wraps `Graphiti(graph_driver=NeptuneDriver(host, aoss_host))`
- No new ABC. `if isinstance` branch in the factory.

## Out of Scope

- Aurora consumer migration in ems-analyst-model
- EMQX rule-engine config (writes telemetry to Aurora vs Tiger) — next session
- Graphiti driver swap implementation in python-mcp-server (separate repo)
- ISO/air-gapped variant (separate spec)

## Open Questions (deferred)

- Whether Tiger Cloud is reachable from EC2 inside the customer's VPC by
  default (private link required?) — deferred until first real commercial
  deployment.
- Whether to add a `commercial-with-aurora-timeseries` hybrid for customers
  who don't want a Tiger account — deferred; ship the 2-variant model first.
