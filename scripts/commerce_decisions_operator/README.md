# Offline Decisions config verification

From the checkout root with the locked Commerce dependencies installed:

```bash
PYTHONPATH="$PWD" .venv/bin/python -B scripts/commerce_decisions_operator/verify_config.py
```

The verifier reads the adjacent [Decisions configuration](api-decisions-proposed.json)
and checks its document hash and budget caps. The optional SDK tests use a mock
transport. The original operator kit and consumed live attempt are in the
[archived project](https://github.com/richardcheam/decisionops/tree/0cf3de4bc0e54a58f2f26d844059fd83b187c2ed/scripts/commerce_decisions_operator).
