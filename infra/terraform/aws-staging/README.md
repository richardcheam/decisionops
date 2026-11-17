# Proposed AWS staging, not provisioned

This prepares a private EKS cluster and one managed node, private PostgreSQL 16 on
RDS, app/web ECR repositories, and a private encrypted/versioned S3 backup bucket.
The existing VPC must supply at least two private subnets with reviewed egress and
private operator access. Supply a currently supported EKS version explicitly.

No account IDs, credentials, passwords or real customer data belong in this folder.
The database password is generated into AWS Secrets Manager, not Terraform outputs.
Outputs contain references only. Application secrets must be delivered separately;
this configuration does not silently grant workloads access to AWS credentials.

Only local formatting and validation are authorized in this session:

```bash
terraform -chdir=infra/terraform/aws-staging fmt -check
terraform -chdir=infra/terraform/aws-staging init -backend=false
terraform -chdir=infra/terraform/aws-staging validate
```

Provider installation contacts the public provider registry; it does not provision
resources. Do not run `plan`, `apply`, ECR push or AWS commands without owner approval.
Before an authorized apply, choose and configure a private encrypted remote Terraform
state backend, review IAM/network access and ongoing EKS/node/RDS/logging costs, set
an explicit budget and review the plan. Backend/state configuration is deliberately
not invented for an unknown AWS account. Deletion protections and final snapshots
require an explicit teardown plan; they do not make resources free or ephemeral.

The local Kubernetes manifests use in-cluster PostgreSQL solely for the disposable
local rehearsal. AWS staging must omit that StatefulSet, configure the RDS URL via a
Secret, use ECR image digests, provide storage/network policy and TLS/identity, and
repeat the browser, interruption, rollback and restore checks. No ALB, public DNS,
TLS certificate, real carrier integration or hosted telemetry is provisioned here.

The proposed minimum is one t3.medium worker, one db.t4g.micro database with 20 GiB
(initial) storage and 7-day EKS log retention. This is a sizing proposal, not a
measured capacity or price estimate. Review the current regional cost and set an
owner-approved monthly cap before provisioning; the configuration creates no
paid resource or budget alert until separately applied. NAT/private-endpoint costs
from the existing VPC remain part of that review.
