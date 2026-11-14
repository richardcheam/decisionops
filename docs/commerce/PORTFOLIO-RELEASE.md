# Portfolio release decision: local rehearsal complete

Base: 71f10857edb424fa664ce18f6fc38317d61e6065, feat/commerce-staff-investigation.
This is a fictional portfolio release candidate, not a public deployment. All new
verification is agent-executed locally. Original migration-0004, staff 55521,
portfolio 8091, database volumes, historical reports and model ledgers remain intact.

## Access and hosting layout

| Surface | Package | Permission boundary |
|---|---|---|
| Public walkthrough | frontend/public static assets, separate compose.walkthrough.yaml | No API upstream, workers or database; GET/HEAD only. No invitation URL/password, forms or scripts. |
| Invited fictional staff | compose.portfolio.yaml, project decisionops-portfolio-release, loopback 8093 | Explicit password required; authenticated existing API. No default public login. Login page alone grants no business access. |
| Operator reset | Docker/host access only | No reset HTTP endpoint. Stop access, export/verify evidence, then deliberately recreate only the disposable release volume. |

Deploy the public static artifact separately, proposed as a **separate GitHub Pages
site/subpath**, not on the VM. It must not replace the historical viewer. Relative
assets support subpath hosting; the artifact has a derived index.html. Hosting/account
eligibility and publication are still unverified/unapproved. Public pages continue
working when the VM is stopped/deleted. Do not put API proxies, passwords or runtime
configuration into that static site.

The interactive demo uses rules and explicit reads; optional live provider code is
preserved but no provider key/paid mode is configured. Approval binds the exact current
proposal/generation/hash. Creating a replacement requires a separate staff confirmation,
followed by deterministic locking/revalidation/transaction/reconciliation. Invitees
share fictional staff authority and records; this is not per-person production identity.

## Required configuration and exact local launch

The new release path defaults to 8093 and distinct :release image tags, preserving the
old 8091 containers. It never reads an existing .env. You need Docker/Compose, the three
built runtime images and one explicit invitation password of at least 16 characters.
Use a fresh strong private password for any real invitation; the test fixture used
in local logs is not a deployable secret. No AWS/OpenAI credentials belong in Compose.

```bash
cd <historical-checkout>
# Enter privately; do not paste a real password into command history or a report.
read -r -s -p 'Invitation password: ' COMMERCE_PORTFOLIO_PASSWORD
printf '\n'
export COMMERCE_PORTFOLIO_PASSWORD
export COMMERCE_PORTFOLIO_PORT=8093
export COMMERCE_PORTFOLIO_ORIGIN=http://127.0.0.1:8093
sg docker -c 'docker compose --env-file /dev/null -f compose.portfolio.yaml -p decisionops-portfolio-release up -d --wait --wait-timeout 90 --no-build --pull never'
curl --fail http://127.0.0.1:8093/health
sg docker -c 'docker compose --env-file /dev/null -f compose.portfolio.yaml -p decisionops-portfolio-release ps --all'
# Separate local read-only site, no invitation configuration needed:
sg docker -c 'docker compose --env-file /dev/null -f compose.walkthrough.yaml -p decisionops-portfolio-walkthrough up -d --wait --wait-timeout 60 --no-build --pull never'
curl --fail http://127.0.0.1:8094/health
```

Open 8094 for public read-only material. Invited users open 8093 and sign in as `visitor`
with the privately supplied password. Local HTTP is loopback only; use an SSH tunnel
for a local demonstration. Never expose that HTTP port for remote invitation logins.
Current rehearsal records already contain one completed fictional replacement; do
not expect a second compensation for ORD-1042 without an operator reset window.

Init creates schema 0008, seeds only an empty dedicated database and sets up existing
checkpoints. Volume: decisionops-portfolio-release_portfolio_pgdata. No database host
port exists. API/ordinary worker/staff investigator/PG use an internal network; only
nginx has ingress. Container logs rotate at 10 MiB × 3 files per service.
Keep the configuration available for lifecycle commands; Compose validates the
required password even for status/stop. Never dump `docker compose config` or full
container environments with private credentials; use `config --quiet`.

## Fresh host: preparation after separate resource approval

1. In the console confirm the account-specific checks below. Select one eligible
   Ubuntu 24.04 LTS **x86_64** no-license AMI, c7i-flex.large, 40 GiB gp3 baseline performance,
   one public IPv4 and one availability zone in us-east-1. This guide does not launch it.
   Use no paid AMI, NAT gateway, ALB, RDS, custom KMS key or optional models.
2. Security group: restricted SSH from your address; 443 for invite access, 80 only for
   certificate issuance/redirect. Never expose 8093,5432 or 8000. Attach no AWS credentials
   to the app. EBS DeleteOnTermination must be an explicit teardown choice.
3. Install the host prerequisites only on that later approved empty VM. No host
   bootstrap was executed here. Example Ubuntu commands (review package versions first;
   no blanket apt upgrade):

```bash
sudo apt-get update
apt-cache policy docker.io docker-compose-v2 nginx certbot
sudo apt-get install --no-install-recommends docker.io docker-compose-v2 nginx certbot
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
```

The rehearsal used Docker 29.1.3 and Compose 2.40.3. A different host version is an
unverified compatibility change: validate image loading/Compose before giving access.
Application dependencies stay inside the locked images; no pip/npm/model installation
belongs on the VM.

4. After private transfer is approved, copy the reviewed source/Compose plus
   runtime-images.tar.gz and runtime-images.sha256 to /opt/decisionops. The archive
   contains app:release,web:release and pinned PostgreSQL only, not volumes, secrets,
   SDK/model environments or browser builder. Verify checksum then load:

```bash
cd /opt/decisionops
sha256sum --check runtime-images.sha256
sudo docker load --input runtime-images.tar.gz
sudo docker image inspect decisionops-portfolio-app:release decisionops-portfolio-web:release --format '{{.Id}} {{.Architecture}}'
```

Compare exact IDs with the release evidence, not just mutable tags. Archive loading on the existing engine and no-pull startup through the tagged
PostgreSQL alias were exercised; records were unchanged. Fresh-engine loading and
artifact transfer remain unexecuted. The archive gzip/inventory/hashes were verified. The cached source build is not an empty-host bootstrap.

5. Create a NEW private operator config file (not a prerequisite carried from this
   workstation): /etc/decisionops/portfolio.env, root-owned mode 600, containing only
   COMMERCE_PORTFOLIO_PASSWORD, COMMERCE_PORTFOLIO_PORT=8093,
   COMMERCE_PORTFOLIO_ORIGIN=https://your-approved-demo-hostname and
   COMMERCE_PORTFOLIO_POSTGRES_IMAGE=decisionops-portfolio-postgres:release. Generate a strong
   password locally, give it only to invitees, and never upload that file. Use
   `sudo docker compose --env-file /etc/decisionops/portfolio.env ...` for host lifecycle
   commands instead of --env-file /dev/null. Keep it across SSH sessions/reboots.
6. Run the same named release up/health commands with that explicit private config.
   PG/API/web should be healthy, workers running, init exited 0. Confirm there are no
   host bindings except 127.0.0.1:8093. Test unauthenticated API requests return 401 before
   issuing invitations. Missing/short configuration must fail closed.

### HTTPS and invitation check (not executed against a public hostname)

Point an owner-approved demo hostname at the instance. Before admitting users, issue
its certificate, then adapt docker/nginx.invite-host.example.conf to that exact name
and certificate paths. It proxies HTTPS only to127.0.0.1:8093 and preserves Authorization.
An example certificate step, after DNS/port 80 approval and before nginx is listening:

```bash
sudo certbot certonly --standalone -d YOUR_APPROVED_DEMO_HOSTNAME
# Install the adapted host nginx site; never run the .test placeholder unchanged.
sudo nginx -t
sudo systemctl reload nginx
```

Verify a trusted certificate/redirect, correct API origin and 401 without credentials.
Then use `curl --user visitor https://YOUR_HOST/api/cases` (interactive password prompt,
not password in argv) and exercise one fresh eligible/incomplete case. Check public
static mutations still fail and public-origin requests cannot mutate the invited API.
DNS, issuance/renewal, host nginx installation, security groups and real HTTPS behavior
remain account/host-specific checks, not local test claims. Public Pages has its own
HTTPS lifecycle and no VM origin.

## Restart, rollback, reset and teardown

Use the SAME reviewed configuration/project for every command. On the local rehearsal
substitute --env-file /dev/null and keep the explicit environment above; on the VM use
--env-file /etc/decisionops/portfolio.env.

```bash
sudo docker compose --env-file /etc/decisionops/portfolio.env -f compose.portfolio.yaml -p decisionops-portfolio-release stop staff-investigator
sudo docker compose --env-file /etc/decisionops/portfolio.env -f compose.portfolio.yaml -p decisionops-portfolio-release start staff-investigator
sudo docker compose --env-file /etc/decisionops/portfolio.env -f compose.portfolio.yaml -p decisionops-portfolio-release stop
sudo docker compose --env-file /etc/decisionops/portfolio.env -f compose.portfolio.yaml -p decisionops-portfolio-release up -d --wait --wait-timeout 90 --no-build --pull never
```

A previous lease may take 30s to expire. Inspect durable steps/counters and require the
same deadline, retained observations and one publication/operation. Never reset tokens,
reservations or budgets. Unknown dispatched work is not automatically retried; use
existing explicit investigation recovery. The local test stopped between committed
rules reads, not during unknown model work. The verifier now REQUIRES --release and
restores its owned worker even when its health check fails; there is no default 8091
business-operation path.

Rollback: close access/stop only the release stack, preserve its volume and evidence,
then load the previously reviewed **release** image IDs/source with compatible schema
and the same private invitation config. Do not roll a public-facing host back to the
old public-password 71f1085 packaging. No schema change was made in this slice. If image
or schema compatibility is unclear, keep the stack stopped; never downgrade its DB.
Public static rollback is independent and cannot grant API access.

Reset: operator only. Stop web/API/workers first, pg_dump the fictional database while
PG runs, retain logs/source/trace with SHA256, then down without -v. Only after verifying
the volume's Compose project label matches decisionops-portfolio-release may the
operator deliberately remove that ONE volume and reinitialize. No public reset URL,
startup reset, automatic paid replay or deletion of historical artifacts exists. This
destructive reset was not performed during the rehearsal.

Teardown after an approved cloud rehearsal: export and verify evidence FIRST; down the
release project, terminate the tagged EC2 instance, verify DeleteOnTermination/removal
of its EBS volume, release any allocated Elastic IP and remove only demo snapshots/
DNS/security-group artifacts if applicable. Confirm Billing/Resources shows no orphan
EBS/IP/NAT/ALB resources. Stopping EC2 ends compute charges but retained disk/IP may
still consume credits. Leave the separate public walkthrough if desired. No teardown
or AWS resource operation has been executed by the agent.

## AWS Free-plan proposal for Richard — decision required

Richard reports 100 USD credits, 0 USD due and plan end 2027-04-09. Those are user-reported
account facts, not an independently inspected account or credit-expiry guarantee.
[EC2's current eligibility table](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-free-tier-usage.html)
includes c7i-flex.large for accounts created on/after 2025-07-15. It is x86, 2 vCPU/4 GiB
and fits the tested amd64 stack. [AWS regional documentation](https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-regions.html)
lists C7i-flex in Virginia and Paris. This establishes a regional family offering,
NOT your availability-zone capacity, quota or account launch permission.

The extracted [official regional catalog record](../../reports/commerce-release-rehearsal-20261112/pricing-us-east-1.json)
quotes **0.08479USD/hour Linux On-Demand in us-east-1**; Paris's record quotes 0.10075.
Use Virginia as the first costed candidate, not Lightsail or a plan upgrade. Validate
the exact size/AMI/zone price and eligibility in the console before approval.

| Item, us-east-1 | 24 hours | 30 days /720 hours |
|---|---:|---:|
| c7i-flex.large compute | $2.03496 | $61.04880 |
| 40 GiB gp3 at $0.08/GiB-month, baseline performance | $0.10667 | $3.20 |
| One public IPv4 at $0.005/hour | $0.12 | $3.60 |
| Outbound 1 GB/day or 10 GB/month, if shared allowance remains | $0 | $0 |
| Same traffic if allowance exhausted, assuming $0.09/GB first paid tier | $0.09 | $0.90 |
| Total estimated credit usage | **$2.26–2.35** | **$67.85–68.75** |

Disk day rate assumes a 30-day month. No obsolete free 30 GB/750-hour deduction was taken.
[gp3 published pricing](https://aws.amazon.com/ebs/volume-types/), [IPv4 pricing](https://aws.amazon.com/vpc/pricing/)
and [aggregate 100 GB monthly outbound allowance](https://aws.amazon.com/ec2/pricing/on-demand/)
support the components. Paid traffic tier is a planning assumption to confirm in the
console/calculator. Inbound image transfer is not counted as outbound traffic; avoid
cross-region services. Excludes tax/domain, snapshots, other account use and unplanned
traffic. Static hosting is proposed separately on existing eligible GitHub Pages
($0 platform plan assumption, confirm repository/account eligibility), not billed to
this VM. No Route53, NAT, ALB or RDS is needed for this proposed rehearsal.

At this usage 100 USD covers roughly 44 days, not until April 9 if running continuously.
Eligible does not mean free compute: credits are consumed at regular rates.
[AWS Free-plan rules](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier.html)
end the plan when time/credits run out, whichever comes first. Do not upgrade the plan.

**Proposed next approval:** one 24-hour AWS rehearsal, planning allowance at most 3 USD
eligible credits, followed by evidence export and teardown. This is not spending
authorization and not an automatic hard cap; billing alerts are delayed and do not
stop resources. Do not leave the VM running for a month under a one-day approval.

Account-specific console checks before any launch:

- Confirm Free plan still active, balance/credit eligibility and each credit's expiry,
  separately from the reported plan end. Check other account usage. 0 USD due is not
  proof of 0 credit consumption.
- In us-east-1 confirm c7i-flex.large's Free-tier label, no-license x86 AMI eligibility,
  offered zone, On-Demand standard-vCPU quota of at least 2 and actual capacity.
- Preview the 40 GiB gp3 baseline, public IPv4 and traffic charges/credit coverage. If
  any component requires an upgrade or is not covered, STOP; do not switch plans/types.
- Confirm intended address/DNS/certificate route, operator deletion time and retained
  artifacts. Do not provision extra managed services to bypass a missing prerequisite.

[Actual local results and source/skip attribution](../../reports/commerce-release-rehearsal-20261112/README.md).
