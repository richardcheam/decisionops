# Run DecisionOps with a model on your laptop

Ollama runs the model. DecisionOps sends it a question and a list of allowed actions.
LangGraph runs the investigation, and the application checks the records and enforces
staff approval. One model can serve the customer assistant, staff assistant, and both
investigation specialists.

## Start Ollama on the host

Install Ollama using its [Linux instructions](https://docs.ollama.com/linux).
If Ollama is already running as a system service, configure that service for
[local-only mode](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features).
Otherwise run this in its own terminal:

```bash
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NO_CLOUD=1 OLLAMA_CONTEXT_LENGTH=4096 ollama serve
```

In a second terminal, from the DecisionOps checkout:

```bash
ollama pull qwen3:1.7b
export COMMERCE_LLM_MODEL=qwen3:1.7b
python3 scripts/check_local_model.py
ollama ps
```

The download is about 1.4 GB. In `ollama ps`, the **PROCESSOR** column shows whether
Ollama is using the GPU. The check prints warmup time separately, then checks three
chat actions and one specialist decision using the same transport as the app.
The script marks a decision as passing only if it matches the expected action
and finishes in under 4.5 seconds. If the 1.7B model is too slow or
uses too much memory, repeat with `qwen3:0.6b` (about 523 MB).
[Model sizes](https://ollama.com/library/qwen3/tags)

## Run the app

Use a disposable PostgreSQL database. This example uses Docker for PostgreSQL and
runs Ollama and the app directly on your machine. Run it from the checkout.

```bash
docker run -d --name decisionops-local-model-db -p 127.0.0.1:55480:5432 \
  -e POSTGRES_DB=decisionops_demo -e POSTGRES_USER=demo \
  -e POSTGRES_PASSWORD=fictional-local-database postgres:16
docker exec decisionops-local-model-db pg_isready -U demo -d decisionops_demo
```

Repeat the readiness check until PostgreSQL accepts connections. In the app shell:

```bash
export COMMERCE_DATABASE_URL='postgresql+psycopg://demo:fictional-local-database@127.0.0.1:55480/decisionops_demo'
export COMMERCE_LLM_MODEL=qwen3:1.7b
export COMMERCE_STAFF_USERNAME=operator
export COMMERCE_STAFF_PASSWORD=fictional-manager-demo-only
export COMMERCE_CUSTOMER_CAMILLE_PASSWORD=fictional-camille-demo-only
export COMMERCE_CUSTOMER_ALEX_PASSWORD=fictional-alex-demo-only

uv sync --locked --only-group commerce
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/alembic upgrade head
.venv/bin/python -B -m decisionops.commerce.portfolio_seed
.venv/bin/python -B -m decisionops.commerce.worker setup
.venv/bin/python -B scripts/commerce_delivery_local.py --mode llm --port 8155
```

From another terminal, run `curl --fail http://127.0.0.1:8155/health`.
Staff can sign in as `operator`. Use `camille` for the customer view of Lyon.

The health response should say `local_llm`. Sign in at
[Customer](http://127.0.0.1:8155/customer) or [Staff](http://127.0.0.1:8155/staff).
Open Lyon and ask staff to investigate. Check that it proposes a replacement only
after the records support one. Then try Lille and Saint-Denis and check that
neither gets a replacement proposal. Creation still takes staff approval and a
separate confirmation.

## Use the Compose launcher

If you already have a local Ollama image and model files, you can run the whole
stack in Docker. First set the fictional credentials in the
[quickstart](../README.md#run-the-demo). Then point the launcher at the existing
model directory.

```bash
export COMMERCE_DEMO_MODE=llm
export COMMERCE_LLM_MODEL=qwen3:1.7b
export COMMERCE_OLLAMA_MODEL_DIR='/absolute/path/to/ollama/models'
bash scripts/demo.sh build
bash scripts/demo.sh start
bash scripts/demo.sh health
```

Set `COMMERCE_OLLAMA_IMAGE` if your local image uses a tag other than
`ollama/ollama:latest`. Compose mounts the model files read-only, disables Ollama
cloud features, and checks that the specified model is installed. Sign in as
`visitor` on the [staff page](http://127.0.0.1:8133/staff).

## What the checks cover

The [automated tests](../tests/test_commerce_local_llm.py) exercise the Ollama
protocol with a local stub. Running the model check above measures your machine's
response time and checks the expected actions for those examples. Live-model accuracy and latency still need to be measured on the target hardware.

## Where to make changes

| What you want to change | Where to do it |
|---|---|
| Use a different model | Export `COMMERCE_LLM_MODEL`, rerun the check, and restart DecisionOps |
| Use another local Ollama port | Set `COMMERCE_OLLAMA_URL` and restart DecisionOps |
| Change how chat chooses actions | Edit the role prompts in [local_llm.py](../decisionops/commerce/local_llm.py) |
| Change recognized chat actions | Edit [role_actions.py](../decisionops/commerce/role_actions.py) and the corresponding [customer](../decisionops/commerce/customer.py) or [staff](../decisionops/commerce/conversations.py) handler |
| Change which specialist can read which records | Start with the [workflow registry](../decisionops/commerce/workflow_registry.py) |
| Change whether a replacement qualifies | Start with [eligibility.py](../decisionops/commerce/eligibility.py) |
| Add a question with a known expected answer | Edit the checks in [check_local_model.py](../scripts/check_local_model.py) |

A failed model check prints the error and exits with a nonzero status. If the
connection is refused, check that Ollama is running. If a decision is wrong,
inspect the prompt and try the same question again before changing business rules.
