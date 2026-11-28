# Catalog vision ablation protocol

Use the three existing catalog cases as a smoke test. Compare the mapping rule,
the shipped supplier-aware catalog policy, a single vision call, and the
combined visual and catalog workflow. The two deterministic arms use the same
snapshots and make no model requests.

The six separate difficult pairs test pixel evidence independently of catalog
actions. All pairs depict the same stylized bottle body. The requested cue is
cap stripe color, mark shape, or mark height. Background changes in every
pair. Three pairs change the cue and three preserve it. Send only the images
and cue, with no SKU, reference answer, or fixture ID. Score exact matches for
the cue and false difference reports on controls. Keep uncertain and invalid
answers in the denominator, separate from wrong definite answers. Measure local
wall time per attempted request.

Freeze the files before running. Use one serial run with the installed
Moondream model, with no tuning on these six labels. A model that sees a
difference supplies a possible reason for staff to review verified metadata.
This diagnostic does not grant authority to change a listing. The current
combined action policy can withhold a relink and cannot override a
catalog-policy keep. These synthetic pairs measure cue discrimination, not
performance on realistic product photography.
