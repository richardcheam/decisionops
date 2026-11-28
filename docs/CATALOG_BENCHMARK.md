# Catalog image benchmark

Use the catalog's verified records to decide whether a listing image should
change. Keep the visual model out of approval and confirmation. The installed
model rejected image input, so this run gives no basis for adopting a vision
model or splitting the work into separate agents.

## Held-out results

Three synthetic cases cover a wrong image, a correct but ambiguous-looking image,
and a supplier disagreement. Each arm uses the same cases. Demo and held-out sets
use distinct image assets. The scoring labels sit in a separate file and stay
out of model requests.

| Method | Observed | Exact | Wrong fixes | Missed defects | Appropriate referrals | Missed referrals | Median observed wall time |
|---|---:|---:|---:|---:|---:|---:|---:|
| Image ID to SKU rule | 3/3 | 2/3 | 0 | 0 | 0 | 1 | <0.01 ms |
| Single multimodal call | 0/3 | — | — | — | — | — | — |
| Visual check and catalog reads | 0/3 | — | — | — | — | — | — |

The ID rule caught the wrong green bottle image and kept the correct cream mug
image. It also kept the gray bottle image when the label called for staff review
of conflicting records. Its time covers local computation on a fixture snapshot
and excludes database or UI work. Unavailable vision cases have no correctness
or latency score. Three stylized cases provide a smoke benchmark for these
conditions. Labels are visible in the repository. The fixture split does not
estimate real catalog accuracy or constitute a blinded trial. The combined
arm also adds supplier checks beyond the mapping baseline, so this design
leaves the isolated value of vision open.

The single-call arm asks for one decision from the available images and listing
traits. The combined arm asks only what is visible, with uncertainty. A separate
catalog check reads scoped verified SKU mappings and the supplier record. The combined arm recommends a relink only when the catalog checks identify
the verified candidate and the visual response says the images differ. The
descriptions do not establish SKU identity. Offline tests exercise response handling
and scoring with stubs. The app uses the deterministic catalog checks and refers
conflicts to staff.

## Local vision capability

Ollama 0.40.18 received actual PNG bytes for `qwen35-local:2b`, ID
`806d46073db0`. It returned HTTP 500 and reported “image input is not supported”
with a hint about the missing multimodal projector. The initial red-square
request took 6.404 seconds and a request with a catalog PNG took 0.029 seconds
with the runner loaded. These are rejection times. Ollama reported the runner
on a GTX 1050 Ti Max-Q with 4 GiB VRAM, alongside an Intel Core i7-8750H host.

Moondream 1.8B is a candidate to try locally. Ollama lists it as a 1.7 GB
image-capable model. That artifact size makes it a reasonable candidate for
the 4 GiB GPU. Actual fit and latency still need a run on this machine.
[Ollama model card](https://ollama.com/library/moondream)

## Reproduce

```bash
python3 -B -S -m decisionops.commerce.catalog_evaluation --split heldout \
  --unavailable-reason 'qwen35-local:2b rejected image bytes (HTTP 500, missing mmproj)'
```

To measure both vision arms, use `--model` with an image-capable tag already
installed in local Ollama in place of `--unavailable-reason`. The evaluator
sends PNG bytes only to the local endpoint. It records results and errors
without writing a listing. Run the staffed demo from the
[portfolio guide](PORTFOLIO_DEMO.md#verify-a-catalog-image).
