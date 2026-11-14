# Portfolio release rehearsal — decision evidence

Accepted base 71f10857edb424fa664ce18f6fc38317d61e6065, branch
feat/commerce-staff-investigation. See [the single release handoff](../../docs/commerce/PORTFOLIO-RELEASE.md)
for exact deployment, rollback/teardown, configuration and AWS approval proposal.
No cloud resources, plan upgrade, publication or paid/model calls occurred.

## Actual local execution

A clean detached checkout at 1555a2d399e70c5616ed0a000c7424bdd7b5ab32 built current
source over existing locked caches with network-disabled builds and --pull=false.
The release PG volume was checked absent before startup. No existing .env/private
configuration was used. Only an explicit fictional test password/port was supplied
in the command environment; no invitation default remains. API/PG/web became healthy,
init migrated 0008/seeded/checkpointed a new dedicated database, workers ran.

| Check | Executed result |
|---|---|
| Public/access HTTP matrix | 24 rejected POST/DELETE attempts across public and anonymous interactive endpoints; no durable record changes |
| Old public fixture login | Interactive API returned 401 |
| Valid invited credentials sent to public origin | Public POST still returned 405, no API forwarding |
| Authenticated interactive write with public Origin | 403, durable records unchanged |
| Public browser render | No forms, inputs, buttons, scripts or published invitation password; screenshot [public-readonly.png](public-readonly.png) |
| Actual invited browser/API/workers | 2 passed, 0 skipped: eligible and incomplete cases, refresh, duplicate admission, exact approval/separate execution confirmation |
| Worker restart during eligible run | Stop after 1 committed read; resume 7; 2 lease claims; original deadline/history preserved; all dispatch_count≤1; one proposal and one verified replacement/reservation |
| Whole release stack stop/restart | All 11 exported durable table arrays exactly equal before/after; public static origin remained healthy while interactive stack was stopped |
| Source evidence/public links tests | 4 passed, 0 skips |
| Verifier targeting/cleanup regressions | 2 passed, 0 skips, mocked Docker/HTTP only |
| Dependency-free profile | 465 collected, 200 passed, 265 explicit optional skips, 0 failures/errors |
| Missing invitation configuration | Compose rejected it before resources/startup |
| Cached image/archive checks | Runtime archive gzip integrity, exactly 3 tagged images, existing-engine load/no-pull alias startup, static ZIP CRC and hashes; no invitation/API-key image environment |

[summary.json](summary.json) gives actual run ID/deadline/counters and 51.416s harness
wall time. [public-access.json](public-access.json) records each unauthenticated status.
All browser actions, fictional approvals/replacements, commands and database checks
above were **agent-executed locally**. Richard's prior informal browser trial is
separate. Independent review was static source inspection, not independent runtime
verification. CI and public browser/HTTPS hosting remain unexecuted.

The runtime image export initially saved digest-only PostgreSQL with RepoTags:null.
That is insufficient portable-reference evidence for a new engine. The first archive/
manifest/hash is retained as untagged-postgres, not the deployment artifact. The final
export gives the identical pinned image an explicit decisionops-portfolio-postgres:release
alias; configure COMMERCE_PORTFOLIO_POSTGRES_IMAGE to that alias on an offline host.
No PostgreSQL version/dependency changed. Existing-engine load and no-pull alias startup passed with every durable record unchanged; new-engine bootstrap remains unverified.

## Commands and raw evidence

Build/launch used the new clean checkout with explicit fixture configuration:

```bash
COMMERCE_PORTFOLIO_PASSWORD=<explicit-fictional-test-value> COMMERCE_PORTFOLIO_PORT=8093 sg docker -c 'docker compose --env-file /dev/null -f compose.portfolio.yaml -p decisionops-portfolio-release build --pull=false'
sg docker -c 'docker compose --env-file /dev/null -f compose.walkthrough.yaml -p decisionops-portfolio-walkthrough build --pull=false'
sg docker -c 'docker compose --env-file /dev/null -f compose.walkthrough.yaml -p decisionops-portfolio-walkthrough up -d --wait --wait-timeout 60 --no-build --pull never'
COMMERCE_PORTFOLIO_PASSWORD=<same-value> COMMERCE_PORTFOLIO_PORT=8093 sg docker -c 'docker compose --env-file /dev/null -f compose.portfolio.yaml -p decisionops-portfolio-release up -d --wait --wait-timeout 90 --no-build --pull never'
COMMERCE_PORTFOLIO_PASSWORD=<same-value> COMMERCE_PORTFOLIO_PORT=8093 python3 -B scripts/commerce_portfolio_verify.py --release
python3 -B -S -m unittest discover -s tests -p test_commerce_portfolio_evidence.py -v
python3 -B -S -m unittest discover -s tests -p test_commerce_release_contract.py -v
python3 -B -S scripts/commerce_ci_tests.py dependency-free
```

The password placeholders protect the operator contract: it must be supplied and
must not become a public/default invitation. Browser receives it via environment,
not argv or a Playwright trace. Saved Compose JSON redacts password/database URL.
The first empty-volume check and complete command output remain in runs/portfolio-release:

- before-volume.log,clean-build.log,public-build.log,startup.log,public-start.log.
- rehearsal.log; clean-checkout-artifacts/browser.log and restart-before/stopped/after.json.
- before-stack-stop.json,after-stack-restart.json,shutdown.log,persistent-restart.log,
  public-independent.log; public-browser.log/public-final-start.log.
- public-red.log/public-green.log,verifier-red.log/verifier-green.log,
  dependency-free-final.log,no-invite-password.log,image-identities.log.
- runtime-images.tar.gz/runtime-images.sha256/runtime-image-inventory.json (runtime only),
  public-walkthrough.zip/public-walkthrough.sha256 (independent static host only).

Expected rejection/failure reproductions are preserved, not counted as passes:
public-password regression first failed, then passed after public credentials were
removed; missing release flag initially reached a mocked Docker operation; health
failure initially lacked guarded worker restoration. Both review findings have focused
RED/GREEN tests. Successful --release browser work was not repeated for these fixes.
An archive inspection helper initially mishandled null RepoTags; the archive was not
corrupt. Correct inspection exposed the transfer-tag gap described above.

## Scope, reused evidence and unresolved hosting checks

The business/domain, approval/execution, provider code, migrations, uv.lock,
package-lock and original compose.yaml are unchanged from the accepted base. No
migration was added. Reuse (not rerun) the accepted 194 required PostgreSQL, 13 staff
backend and prior mocked Decisions/legacy checks. New actual PG evidence is the fresh
Compose/browser/restart/persistence rehearsal above. The 265 dependency-free skips are
explicit optional-dependency/database/model tests, not claimed DB/browser passes.
No model checkpoint/SDK experiment or frozen evaluation was repeated.

The historical live Decisions JSON remains byte-identical:
fc42a072225215c4cccd42627a6bb9d858146b721be341facf6c301f9b216bda.
It is static fictional evidence, not active inference: six conditions established,
inventory unread, review, no proposal/execution. Rules/mock proposal completion does
not change that negative live result. Stopped native-pilot failure and historical
reports remain preserved. Stage5 is not declared complete.

Unverified: empty-engine/bootstrap/image loading on a new AWS host; actual account
Free-plan/credit coverage, selected AMI/size/AZ/quota/capacity; public DNS/TLS/renewal;
GitHub Pages eligibility/upload/public method behavior; actual host firewall;
operational reset and cloud teardown. The documented HTTPS template is uninstalled,
not a certificate/security-group test. A graceful rules restart between committed
steps does not prove arbitrary crash/unknown-inference recovery. Invitees share one
fictional staff account; no per-user identity or per-visitor database is claimed.

[US price record](pricing-us-east-1.json), [Paris price record](pricing-eu-west-3.json)
and [decimal cost calculation](cost-estimate.json) come from unauthenticated official
public data only, not Richard's account. 100 USD/$0 due/2027-04-09 are user-reported.
Approval proposal: one 24h us-east-1 c7i-flex.large rehearsal, estimated 2.26–2.35USD
credits; plan 3 USD and explicit teardown. No authorization to spend follows from this
report. Account console confirmation and a separate release decision remain required.
