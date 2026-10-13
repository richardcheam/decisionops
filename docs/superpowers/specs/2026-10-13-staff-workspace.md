# Local authenticated staff API and workspace

Autonomous local implementation authorized. One configured staff operator and one
fictional store. FastAPI with strict typed requests; React/TypeScript/Vite client.
No general conversational interpretation or provider calls. Structured controls
and evidence templates are honestly labeled. API and durable worker separate.

HTTP Basic authentication on loopback/local demo, TLS required before external
access. Password configured through untracked environment, minimum 16 characters;
no default staff secret. Constant-time checks. Browser keeps credentials in memory,
never localStorage; server allows no cross-origin CORS. Mutation JSON and Origin
checks prevent browser cross-site actions. Every case/job access checks configured
store binding server-side; arbitrary actor/approval fields rejected. CLI remains
local-demo identity; API passes authenticated operator name to review service.

API: health readiness (no business side effects); authenticated session, orders,
case list/create/detail; enqueue investigation/approved execution; exact review,
escalation, job/graph inspection and explicit checkpoint resume. Domain transactions
stay authoritative; no staff request waits for background investigation/execution.
Errors bounded/sanitized; unavailable returns 503, wrong binding/lifecycle 409,
unknown/unauthorized-store IDs 404, malformed input 422, missing auth 401.

UI: login; case inbox/new case; evidence/facts with unknown/blocker distinctions,
immutable proposal contents, ordered timeline, explicit approve/reject/escalate,
approved execution and verified result. Disabled invalid-state controls; server
still enforces permissions. Poll case/job state without inference calls. Readiness
failure shown with actionable restart guidance. No fictional promise of shipment.
No credential, internal infrastructure or technical jargon in normal product flow.

Build/test: locked frontend dependencies, actual production build, authenticated
API integration and browser tests. Compose app containers share local PostgreSQL
network; API binds loopback, frontend proxy serves same-origin. Persistent business
and graph data survive restart. Operator setup/rotation, startup/shutdown, deployment
rollback and failure reproduction documented. No AWS provisioning or paid API.
