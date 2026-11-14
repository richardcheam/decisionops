# Archive and curation

Archive ID: **2026-11-14-portfolio-release**, alongside the existing
**2026-10-16-wrapup** archive. Operator-local location:
`$HOME/projects/decisionops-archive/2026-11-14-portfolio-release/`.
`manifest.json` records original paths,accepted source identities,destinations,byte
sizes and SHA-256. Copies were byte/hash-verified before removing candidate duplicates.
Archive contents are not published; request them from the owner for a private review.

Archived:790 files /50,259,068 bytes initially,including the accepted multi-agent
bundle/logs/SQL exports, both browser live runs,prior Commerce live/manual evidence,
stopped cached-pilot records and candidate raw public exports. The originals in
accepted historical worktrees remain untouched. Two large generated Docker image
archives were excluded from copying; their existing originals were preserved.
No credentials,model weights,environments,caches or original runtime data were copied.

Removed from the new release tree only:

- `frontend/public/evidence/decisions-live-trace.json`
- `frontend/public/evidence/browser-live-failure-trace.html`
- `frontend/public/evidence/browser-offline-trace.html`

They are replaced with a small outcome summary. The original citation regression
fixture was also archived before removing its unnecessary provider envelope,IDs and
usage;the exact final action arguments and needed fictional observation blocks remain. The static walkthrough and its
manifest/tests now refer to that summary,not a raw provider trace. Required bounded
fictional citation-regression excerpts remain test fixtures;they are not live-run
ledgers or model inputs. Frozen evaluation cases/hashes and historical viewer data
remain unchanged. The old browser experiment's build-asset freeze is historical;
this curated release does not satisfy its old live admission identity and does not
re-authorize an evaluation. No frozen artifact was regenerated.

Retained: application,seven explicit tools,approval/execution/recovery,optional adapters,
migrations0001–0009,locks,container definitions,CI,tests,fictional records and necessary
scripts/docs. Existing tracked diagnostic reports remain because the offline viewer
and regression checks depend on them;they are synthetic project fixtures already in
the remote base,not newly exported private logs. Historical summaries/screenshots are
kept where existing guides/tests use them. No unrelated tracked component was removed.

Publication uses one clean delta on remote `main` b27e2d7 rather than the accepted
branch's unpublished commit ancestry. This preserves all local accepted branches and
avoids publishing raw files from earlier commits that a later commit would remove.
Only this release branch is pushed;no history rewrite,visibility change,branch deletion,
merge or deployment is performed.

## Final cleanup — 2026-11-14

The main-based cleanup archive is `$HOME/projects/decisionops-archive/2026-11-14-final-cleanup/`.
`tracked-file-manifest.json` records the removed milestone/review guides and the
original diagrams with source commit, paths and SHA-256. Historical links now target
immutable `e311fe0` versions instead of broken local paths. Current operation is in
[RELEASE.md](RELEASE.md); specialist architecture is in [ARCHITECTURE.md](ARCHITECTURE.md).

Archived guides: PORTFOLIO-DEMO/RC/RELEASE, STAFF-INVESTIGATION-PLAN,
STAGE2/3/4-REVIEW, STAGE5-CORRECTION/LEDGER/REVIEW and
MULTI-AGENT-EVIDENCE/VERIFICATION (all under `docs/commerce/`).
The original Git history remains available; this removes duplicate instructions,
not product features. Existing scripts, Compose variants and fixture launchers remain
where CI, frozen experiments or preserved demos depend on them. Synthetic reports
remain because the historical viewer and regression tests read them. Raw live traces,
stopped ledgers and SQL/log exports remain outside the active tree in the earlier
archive; no frozen input or historical result was regenerated.

The existing `2026-10-16-wrapup/repository.bundle` was refreshed after preserving its
previous copy. Every inventoried branch tip was recovered in an independent bare
repository before any ref deletion. `refs-before.json`, `bundle-verification.json`
and `branch-decisions.json` record ancestry, actual-tree comparisons and retention
reasons. Open PR branches, active worktrees and unique changes are preserved.

## One application Compose file

At baseline `a584930`, all original Compose files were copied and hash-verified in
`$HOME/projects/decisionops-archive/2026-11-14-single-compose/`. The final application
now uses only root `compose.yaml`; CI/storefront/historical definitions are retained
under `tests/compose/` with explicit repository-root path resolution. The separate
cached-build overlay was retired; the normal locked build still reuses Docker caches.
No runtime volumes, model checkpoints, frozen manifests or historical traces were moved.
