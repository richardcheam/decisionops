# DecisionOps

DecisionOps contains a working local Commerce application and preserved historical
diagnostic experiments with an offline trace viewer.

## DecisionOps Commerce: local staff workflow

Store staff use a browser to select a fictional order, check a missing shipment,
review the evidence, approve an exact replacement proposal, and explicitly create
the replacement. Deterministic rules distinguish failed conditions from missing
or unsupported evidence. **Commerce is local-only and currently uses no paid
inference.**

Replacement creation and stock reservation are real transactional writes to
fictional business records in PostgreSQL. Execution rechecks the approved proposal
and current records before committing. Operation reconciliation, worker lease
fencing and checkpoint recovery support interruption/retry without duplicate
reservations. The demo does not make real shipments, payments, refunds or customer
communications. It is not a production deployment.

Start with the [Commerce operator guide](docs/commerce/README.md). Detailed setup
commands and dependency profiles stay in the operator documentation; staff need
only the browser and sign-in details supplied by the operator.

| Audience or task | Guide |
| --- | --- |
| Understand and start the local application | [Commerce README](docs/commerce/README.md) |
| Use the browser as store staff | [Staff guide](docs/commerce/STAFF-GUIDE.md) |
| Review guarantees, tests and reproducibility | [Source review guide](docs/commerce/REVIEW.md) |
| Operate, diagnose, patch and recover | [Runbook](docs/commerce/RUNBOOK.md) |

## Historical diagnostic experiments and offline viewer

The preserved incident-classification harness compares rules, GLiClass and Laya
on 48 hand-authored development examples. Its separate bounded diagnostic workflow
uses 24 synthetic scenarios and recorded fixture observations; it does not contact
live services or perform operational actions. These limits apply to the historical
harness, rather than to Commerce's local business-record writes.

The [offline trace viewer](https://richardcheam.github.io/decisionops/) presents the
committed comparison and replayable traces. Fixed order remains the strongest
baseline on the inspected synthetic workflow suite. Scores are uncalibrated,
fixture timing is not live latency, and the inspected examples are not independent
held-out evidence or proof of production accuracy. Historical model results do not
establish model usefulness for Commerce.

Read [FINDINGS.md](FINDINGS.md) for measured results and limitations,
[reports/README.md](reports/README.md) for preserved evidence, and the
[five-minute viewer walkthrough](docs/WORKFLOW-DEMO-WALKTHROUGH.md) to explore it.
Full historical setup, model smoke checks, evaluation and replay commands are in
[the historical diagnostic guide](docs/HISTORICAL-DIAGNOSTICS.md); the
[portfolio handoff](docs/PORTFOLIO-HANDOFF.md) retains project context and source
links. Offline replay/export requires no model weights or paid inference; optional
cached-model experiments remain separate from Commerce's model-free operation.
