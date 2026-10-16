# Fixtures

The edp-module-assemblies files are not committed. They're pinned to one commit
in `.gitlab-ci.yml` (`EDP_MODULE_ASSEMBLIES_SHA`). CI fetches them before the
checks job. To run the orders integration test locally, run the same step:

    uv run python tests/fixtures/edp_assets.py --sha 2cfac23

One archive download (per-file raw fetches get rate-limited by GitLab).
`edp_assets.py` writes the manifest to `tests/fixtures/edp-module-assemblies-manifest.yaml`
and the referenced files to `tests/fixtures/edp-assets/`.
Boms and plate specs the repo doesn't have get an empty stub in the test seeder.
Topology files must be present; the seeder fails if one is missing.
