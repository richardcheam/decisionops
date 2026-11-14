# Local release operation and verification

Supported entry point: [root README](../README.md). Fixed project
`decisionops-github-demo`,loopback8133,private PostgreSQL volume
`decisionops-github-demo_portfolio_pgdata`. No old demo project is selected.

## Build and launch from one checkout

Requires Docker/Compose2.24.4+,x86-64,roughly4GB available RAM and registry/package
access for a first build. Use an explicit fictional password,not a real account secret.

```bash
export COMMERCE_DEMO_PASSWORD='fictional-demo-password-only'
bash scripts/demo.sh build
bash scripts/demo.sh start
bash scripts/demo.sh health
# http://127.0.0.1:8133 — visitor / the fictional password above
```

`build` uses committed Dockerfile.app and Dockerfile.web directly. Python installs
only the locked commerce group,not model defaults;Node uses package-lock. No optional
SDK/provider/model is needed for rules or mocked specialists. No sibling path or .env
is consulted. Compose never forwards OPENAI_API_KEY. For an offline host with the
existing locked `decisionops-commerce-app:local` and `decisionops-commerce-browser:local`
images,`build-cached` explicitly reuses those images with networking disabled.
That is an alternative,not an implicit dependency of the standard build.

Rules are default. `COMMERCE_DEMO_MODE=mock-specialists bash scripts/demo.sh start`
reconfigures this project's API;new staff investigations use the opt-in graph.
An executed order stays compensated. Reset is explicit and project-scoped:

```bash
bash scripts/demo.sh stop
# stop retains volume; start resumes existing records
bash scripts/demo.sh start
# Only after preserving needed fictional evidence:
COMMERCE_DEMO_RESET=decisionops-github-demo bash scripts/demo.sh reset
bash scripts/demo.sh start
```

Rollback:stop this project and run the previous source/image against its own previous
volume. Never start old source against migration0009 or downgrade populated specialist
history blindly. Do not migrate/reset/restart the owner's original migration0004 stack.
No public hosting,HTTPS or production identity hardening was provisioned.

## Checks

```bash
python3 -B -S scripts/commerce_ci_tests.py dependency-free
# Required PostgreSQL profile,after starting a separate compose.specialists-test.yaml:
# point COMMERCE_TEST_DATABASE_URL ONLY to specialists_test on loopback55548
# use an existing locked commerce+commerce-api environment,or the documented CI profile
python -B scripts/commerce_ci_tests.py postgres
```

Routine CI is model-free. Optional skips are reported;required DB skips fail the job.
The main Commerce workflow runs on this PR. Public CI/browser results will be recorded
in the PR;local evidence below is not a substitute for executed CI.

## Packaging-source results

Local candidate checks:238 dependency-free passes,297 explicitly reported optional
skips;212 required PostgreSQL passes with zero skips;4 public-evidence checks;2 rules
staff browser checks;3 mocked-specialist browser checks;6 offline citation checks.
The historical viewer also exported with its synthetic/uncalibrated notices.
An accidental browser repeat on an already compensated fixture correctly failed its
eligible-proposal expectation;its raw output was retained,not counted as acceptance.
Fresh-volume browser runs are the passing evidence.

The standard build command executed successfully
using the host's cached layers. This establishes build inputs and no sibling-worktree
requirement;it does not establish registry/PyPI/npm retrieval on a fully uncached host.
Remaining fresh-host requirements are access to pinned Python/Node/nginx/PostgreSQL
images,the locked Python/npm artifacts,and Playwright's browser only for browser tests.
No dependency version was upgraded or added.

Original milestone results and evidence limits are in [EVIDENCE.md](EVIDENCE.md).
The separate browser benchmark is not part of this quickstart,was not rerun,and must
not be confused with real staff UI tests. Live models and telemetry remain off.


Clean-checkout rehearsal source:`8b49deb545da5f4797922322fe01ffa063807ead`.
No private .env or sibling worktree was used for build/start/health. Fresh database
identity was `portfolio|portfolio|0009|0` (DB,user,revision,cases). The2 ordinary rules
browser checks passed again from that clean source;stop retained the project volume.
All local checks were agent-executed,not Richard or supervisor executions. Raw outputs
and the deliberately retained reused-fixture failure are archived outside the checkout.
