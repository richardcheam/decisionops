# Maintainer and historical references

- [Deployment and recovery](PORTFOLIO_DEPLOYMENT.md) covers Compose,
  Kubernetes, worker restart, rollback and database restore.
- [Commerce runbook](commerce/RUNBOOK.md) covers database setup and local checks.

## Reset the fictional Compose demo

This removes the demo’s PostgreSQL volume, including saved cases, messages and
replacements. Set the fictional credentials and mode from the
[quickstart](../README.md#run-the-demo) before resetting.

```bash
COMMERCE_DEMO_RESET=decisionops-github-demo bash scripts/demo.sh reset
bash scripts/demo.sh start
```

## Project history

The [documentation before the cleanup](https://github.com/richardcheam/decisionops/tree/a816f6191af1b2ebda9863e1fa20ffdcf6416a14/docs)
contains the older walkthroughs, handoffs and experiment results. The
[design specifications](https://github.com/richardcheam/decisionops/tree/a816f6191af1b2ebda9863e1fa20ffdcf6416a14/docs/superpowers/specs)
are pinned to the same commit. Use the current [docs index](README.md) for
instructions that apply to the product today.
