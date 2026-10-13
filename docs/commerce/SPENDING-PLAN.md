# Spending gates — proposed, not approved or executed

Checked official documentation on 2026-10-13. Routine local/CI operation remains
rules-only and makes no inference calls. Richard's autonomous-development request
does not remove the explicit paid-inference/AWS spending gate.

## Optional OpenAI experiment

Purpose: compare bounded decision selection and grounded language drafting with
the existing rules/template baseline. No model controls approval or execution.
Use fictional records only; customer text cannot override tool permissions.

The [Decisions guide](https://developers.openai.com/api/docs/guides/decisions)
currently documents beta access, gpt-6-luna and Python SDK >=3.26.0. Decisions
charges $0.10 per million input tokens, with no output/cache charges; regional and
long-context premiums can apply. Account access remains unverified. Do not replace
this endpoint silently if unavailable.

Proposed first experiment: maximum 100 Decisions requests and 100 Responses
requests, at most 2,000 input tokens each; language output capped at 300 tokens.
[GPT-6 Luna standard pricing](https://developers.openai.com/api/docs/models/gpt-6-luna)
is $0.10/M input and $0.50/M output; the documented EU regional premium is 10%.
No tools, images, cache writes, priority tier or long context. Conservative uncached
estimates, if that regional premium applies:

| Category | Formula | Estimated USD |
| --- | --- | ---: |
| Decisions | 100 × 2,000 / 1M × 0.10 × 1.10 | 0.0220 |
| Responses | 100 × (2,000 × 0.10 + 300 × 0.50) / 1M × 1.10 | 0.0385 |
| Combined | Before taxes, uncertain charges or contingencies | 0.0605 |
| Double allowance | Does not authorize extra requests | 0.1210 |

Proposed approved ceiling: **USD 1**, replacing the earlier tentative USD 5 for
this one experiment only. No approval exists yet. Recheck pricing and account
availability immediately before spending. Exact input includes all instructions
and schema, not only case text. Verify tokenizer/endpoint accounting before live
calls. Count reasoning/output tokens within the output cap where applicable.

Before implementation can run live: explicit opt-in flag, server-only expiring
project key, persistent atomic pre-call budget reservations, max calls/deadline,
no SDK automatic retries, usage settlement, and unresolved reservations retained
after uncertain responses. Exhaustion/unavailability routes to review, never to
invented evidence. Fake provider tests must exercise timeout, malformed output,
instruction override and budget races without network access. Separate development
and independently reviewed evaluation sets must be frozen before tuning. Current
hand-inspected regressions are not held-out model-generalization evidence.

No OpenAI SDK/API adapter was installed or called in the local release. This plan
is a concrete proposal for later approval, not an implemented budget guarantee.

## Proposed seven-day AWS pilot

Target proposed: eu-west-3, one Linux Lightsail instance, 2 GB RAM/public IPv4,
rules mode, existing images built off-server. The [official bundle table](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-bundles.html)
lists this bundle at USD 12/month with 60 GB storage. Seven days at an illustrative
730-hour month gives 12 × 168/730 ≈ USD 2.76; confirm actual hourly/region billing.
The 4 GB alternative is USD 24/month and needs a revised approval if required.
Local memory measurements do not prove a 2 GB server load test.

| Item | Proposed pilot allocation, USD | Condition |
| --- | ---: | --- |
| One instance/public IPv4 | 3.00 | Delete after seven days, not merely stop |
| Encrypted S3 backup storage/requests | 1.00 | Small fictional dump, seven-day lifecycle; verify regional rates |
| Snapshot/log/transfer contingency | 2.00 | No automatic snapshots or paid log export by default |
| Tax and uncertainty reserve | 4.00 | Confirm account billing/tax before approval |
| Total proposed pilot ceiling | **10.00** | Alerts are not a hard billing cap |

Full-month planning allowance: instance 12 + backup allowance 2 + operational
contingency 6 + tax/uncertainty reserve 5 = **USD 25**. This is an allocation, not
a regional AWS quote. Domain purchase, load balancer, managed database, local model
hosting, NAT gateway and unrelated existing resources are excluded and unauthorized.

Before Terraform/apply: verify actual account plan, eligible credits, expiry,
region availability and tax; assume zero credits until verified. Choose domain/TLS,
restricted SSH CIDR, staff identity, encrypted off-host backup and tested restore,
OIDC repository/environment restrictions, secrets/bootstrap/rotation and Terraform
state handling. Lightsail does not automatically supply an EC2 instance profile;
server S3 credentials/federation need an explicit reviewed plan. Never put staff
or API passwords in Terraform state/user-data.

Pilot must define billing alerts (e.g. USD 5 and 8), daily human cost inspection,
end date and teardown owner. A stopped Lightsail instance can still incur costs;
delete approved instance/static IP/snapshots and review backup/bucket retention.
Verify the billing inventory afterward. Account/region/domain facts are missing,
so a resource-accurate Terraform plan and provisioning approval cannot yet be
claimed. No AWS resource, bucket, IAM principal or paid API request was created.
