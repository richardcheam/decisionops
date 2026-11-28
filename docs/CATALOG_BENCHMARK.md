# Catalog image benchmark

**Keep the shipped catalog checks in charge.** They matched all three smoke
cases. Moondream could identify conspicuous colors, but the measured run found
no reliable new evidence for subtle variants and no improvement in catalog
decisions.

## Same cases, four methods

All four methods use the same three synthetic catalog cases. The supplier-aware
baseline calls the same read-only policy as the app on these valid fixture
snapshots. The production wrapper also validates asset existence and refers
malformed records. Labels are separate from model inputs. Timings are local wall
times and exclude the database and browser.

| Method | Exact | Wrong fixes | Missed defects | Correct referrals | Missed referrals | Median |
|---|---:|---:|---:|---:|---:|---:|
| Image ID to SKU mapping | 2/3 | 0 | 0 | 0 | 1 | <0.01 ms |
| Shipped catalog policy | 3/3 | 0 | 0 | 1 | 0 | <0.01 ms |
| Single Moondream call | 1/3 | 2 | 0 | 0 | 1 | 3.961 s |
| Visual check and catalog policy | 2/3 | 0 | 1 | 1 | 0 | 1.146 s |

The supplier-aware policy caught the disagreement the simple mapping rule
missed. The two wrong single-call recommendations would have changed a correct
mug listing and acted on the disputed gray bottle. The benchmark wrote no
listings. The combined arm kept the catalog decision unless a proposed relink
lacked a visual difference. Moondream said there was no candidate in all three
cases, although each call included a second image. That veto stopped the one
correct relink. The combined arm can only withhold a catalog-approved relink, so
these smoke cases exercise one opportunity for vision to affect a decision.

## What the pixels added

Two single-image checks on catalog PNGs identified the red and blue totes,
and a separate two-image check identified their color difference. Those
development checks took 6.671 s cold, 1.791 s warm, and 2.074 s for the pair.
They show the local artifact received usable visual input for conspicuous cues.

A separate six-pair frozen set tested small differences in cap stripe color,
mark shape, and mark height. Each cue reused its background palette across one
changed pair and one match. The prompt named only the cue and supplied two PNGs.
Moondream scored **1/6**, with two false matches, three uncertain answers, zero
false differences, and zero invalid or unavailable responses. It detected
**0/3** real differences. Either constant answer would attain 3/6 on this
balanced set. Median attempted wall time was **4.227 s**.

The one correct answer was a matching shape, and the answer repeated the
requested cue without naming the shape. The evaluator scores the comparison,
and format-checks the descriptions. On the stripe pair, the text called one
stripe blue and one gray while the comparison said they were the same. This
run supports investigating conspicuous visual cues further. It does not
support using this model to resolve subtle variants or veto a verified relink.

These are small, synthetic, labeled fixture sets. They cannot estimate
accuracy on real photos. The final background correction and response schema
were committed before inference at `840664c`. See the
[protocol](CATALOG_VISION_PROTOCOL.md).

## Local runtime and reproduction

Moondream `1.8b` ID `55fc3abd3867` ran in Ollama 0.40.18 on the GTX 1050 Ti
Max-Q, with `ollama ps` reporting **100% GPU**, 1.2 GB loaded and a 2048-token
context. The host has an Intel Core i7-8750H and 4 GiB of GPU memory.
The earlier `qwen35-local:2b` artifact rejected PNG input with HTTP 500 and a
missing projector hint. That artifact's 6.404 s cold and 0.029 s loaded
times were rejection times. The new measurements used only local inference.

With the model installed in Ollama, run serially from the checkout:

```bash
python3 -B -S -m decisionops.commerce.catalog_evaluation --split heldout --model moondream:1.8b
python3 -B -S -m decisionops.commerce.catalog_evaluation --split difficult --model moondream:1.8b
```

Omit `--model` on the smoke run to evaluate the two deterministic arms alone.
Raw per-case evidence stays in ignored `runs/vision-ablation/`. Run the staffed
demo from the [portfolio guide](PORTFOLIO_DEMO.md#verify-a-catalog-image).
