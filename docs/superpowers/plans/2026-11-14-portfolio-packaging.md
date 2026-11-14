# Portfolio release packaging plan

Goal: publish one curated PR from a clean origin/main-based delta, retaining accepted
07904d19e6192560461c0ff84c25a885a1afea31 behavior and evidence limits.
No new product logic, dependencies, inference, telemetry or original-runtime operations.

1. Verify remote identity, source/working trees and unpublished history. Use release/commerce-portfolio on origin/main b27e2d7; overlay accepted final tree without its unpublished commit ancestry.
2. Copy task/raw evidence to dated external archive; SHA-256 verify before deleting candidate duplicates. Preserve old worktrees/runtime and all required frozen fixtures/historical viewer inputs.
3. Add standalone Compose quickstart with rules default, mocked-specialists opt-in, unique project/port/images; self-contained locked Dockerfiles and explicit cached-build alternative. Root README, architecture diagrams, sanitized evidence summary/screenshots, archive index.
4. Run affected static/dependency-free checks, required database/staff checks and real staff browser on isolated demo; rehearse from clean committed candidate. Record skips and uncached build limits.
5. Review final tree and every outgoing commit; publish clean release branch and one PR, inspect CI, fix in-scope regressions, leave unmerged.
