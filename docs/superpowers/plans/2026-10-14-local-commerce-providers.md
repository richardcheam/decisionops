# Local Commerce providers implementation plan

> Execute with executing-plans/TDD and independent final code review.

Spec: ../specs/2026-10-14-local-commerce-providers.md
No dependency upgrades, downloads, exposed-provider UI, business schema changes.

- [x] Extend typed configs/results and zero-API-charge ledger semantics. Test old
      fake compatibility, malformed native scores, false provenance and forced mode.
- [x] Add commerce/local_provider.py feature/label/subprocess boundary and
      commerce/local_model_worker.py using reusable cached loaders. Test feature
      isolation, sparse cached snapshot, bad dependencies/cache, deadline kill/reap
      and exactly one family per process without importing model packages in CI.
- [x] Integrate provider_service/provider_demo operator mode, retaining no locks
      while waiting and stale-result/recovery fencing. Add required database tests
      with a fake local subprocess result and forced choice/no dispatch.
- [x] Add offline comparison/walkthrough, run actual cached CPU inference one
      family at a time, record meaningful-input count and measured negative results.
- [x] Verify existing model-free/PG regressions, document operator commands, inspect
      source/private inventory, independent review, commit/publish separate unmerged PR.
