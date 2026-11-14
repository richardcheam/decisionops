# Verification fixtures, not application startup

The final application has one definition: [../../compose.yaml](../../compose.yaml),
launched by `bash scripts/demo.sh start` from the repository root.

These files retain isolated CI, browser/storefront and historical rehearsal fixtures;
they are not alternative deployments. Use `--project-directory .` from the repository
root so build contexts and bind mounts resolve to the root. The existing fixture
launchers and CI do this explicitly. Never apply a fixture to an existing app project.

`ci.yaml` is the legacy app/database fixture for backup, rollback and browser regression
checks. `specialists-test.yaml` is a disposable test database. `browser-fixtures.yaml`
and `shop-fixture.yaml` support the separate fictional storefront tests. The remaining
portfolio/multi-agent/walkthrough files preserve older rehearsals only.

Original definitions were copied and SHA-256 verified in the owner-local
`decisionops-archive/2026-11-14-single-compose/` before relocation. Frozen experiment
manifests remain unchanged: historical paid-run admission belongs to its recorded
source, and moving files does not authorize another experiment.
