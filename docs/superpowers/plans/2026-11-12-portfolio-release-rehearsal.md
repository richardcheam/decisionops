# Portfolio release rehearsal and AWS Free-plan proposal

Accepted base71f10857edb424fa664ce18f6fc38317d61e6065; current branch clean. Original,
55521 staff and8091 portfolio runtimes remain untouched. No AWS/account/API operations.

Contracts: standalone interactive Compose project decisionops-portfolio-release,
web loopback8093, empty project-owned PostgreSQL volume and internal backend network.
Require an explicit invitation password; no public fallback. Existing API Basic auth
is the permission boundary, exact proposal approval/execution remain unchanged. The
login UI itself may be public, but all business reads/mutations require invitation
credentials. Reset remains operator-only with no HTTP endpoint.

Separate read-only static walkthrough: compose.walkthrough.yaml on loopback8094 for
local rehearsal; no API upstream/database/VM dependency. GET/HEAD only; API/admin/reset
paths unavailable. No password or interactive URL published. Relative resources make
it suitable for a separately approved static host/subpath (propose GitHub Pages, not
the VM; preserve existing historical viewer). Keep exact historical live-trace bytes.

1. Add failing model-free public/password/relative-link regressions. Correct current
published fixture login and erroneous stage 5-correction documentation path.
2. Add static nginx/image/Compose and fail-closed interactive configuration. Extend
existing stdlib rehearsal harness with explicit release namespace/port/password binding,
without logging secret config or command-line values. No new product/domain features.
3. Clean detached source checkout: build offline using cached locked bases, create
fresh release PG volume, verify no pre-existing tables/data/private config. Inject
only explicit fictional test credentials. Prove public mutations denied on static
site AND unauthenticated/old-default API calls denied on interactive app. Run actual
eligible/incomplete browser cases, graceful worker restart and whole-stack persistence.
Preserve outcomes and failures. Keep public reachable when app is stopped.
4. Collect release Compose/diff/logs/snapshots and static-host artifact; exact source
and image hashes. Model-free checks, inspect final diff, local commits, clean worktree.
Use existing accepted DB/core results where unchanged; CI/cloud remain unexecuted.
5. Document fresh-host Docker/image transfer, HTTPS, invite access, restart, rollback,
operator reset and teardown as instructions (not cloud execution). Read official
AWS eligibility/region/pricing. Candidate c7i-flex.large x86 2vCPU/4GiB in us-east-1;
40GiB gp3, one publicIPv4, low traffic. Separate account console checks for Free plan,
$100 balance/$0 due/reported2027-04-09 end, AMI eligibility, offerings/quota and credit
coverage. No plan upgrade. Predeclare one-day credit budget proposal, not spend.
