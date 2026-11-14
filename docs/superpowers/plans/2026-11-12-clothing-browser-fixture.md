# First clothing storefront fixture

Base d2f174e preserved on feat/commerce-staff-investigation. Work only on the new
feat/commerce-shop-fixture worktree. No changes to existing runtime images, volumes,
release artifacts or other worktrees. No real sites/inference/dependencies/publication.

Build THREAD / STUDY, a fictional clothing shop: four locally illustrated garments,
product pages with accessible colour/size options, a clearly labelled fictional
customer account with three scoped order records, detail and tracking links. No
checkout, real login or money. Customer projection comes from the same fictional
orders/lines/shipments as staff. Inventory/history/policy remain staff-only.

New opt-in storefront flag plus verified shop_fixture database/user identity, strict
allowlist and store scope. Customer routes read only explicit columns; do not query
internal history/policy/stock. A separate one-time fixture seed in the NEW database
makes ORD-TRACKING's update three days old; ORD-1042 remains explicitly lost and
ORD-HISTORY demonstrates a separate staff-only missing-history limitation. Never
rewrite an existing seed or use this fixture seed on portfolio/original databases.

Staff display adds immutable observation source/hash and bounded record references,
with a presentation link to the matching customer page where applicable. Clearly
state database read (rules), not browser navigation. No new policy-visible evidence,
hash contract, approval/execution change, adaptive browser runner or model activity.

Tests first: opt-in/identity/scope/column privacy/read-only API, missing tracking,
stale tracking remains unknown, record provenance. Build cached assets/images under
shop-only tags; run isolated PG55526/web8095 with schema0008/new volume. Real shopper
Playwright follows normal links, selects garment options, checks lost/stale tracking;
existing staff browser suite runs in the same isolated fixture to prove proposal,
exact approval/one execution and incomplete-history review. Preserve scripted traces
as such. Model-free/relevant backend regressions; source review; local commits.

Document a minimal future browser tool contract and two-site evaluation matrix now,
but only build/test Site A. Site B, browser-agent decisions and transfer testing are
next milestone and must not be claimed from scripted Playwright navigation.
