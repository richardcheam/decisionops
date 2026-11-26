"""Warm the configured local Ollama model and check DecisionOps actions."""
import argparse
import http.client
import json
from pathlib import Path
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from decisionops.commerce.local_llm import LocalModel
from decisionops.commerce.role_actions import CUSTOMER_KINDS, STAFF_KINDS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-warmup', action='store_true', help='Use a model already loaded in Ollama')
    args = parser.parse_args()
    try:
        model = LocalModel.from_environment()
        if not args.skip_warmup:
            connection = http.client.HTTPConnection(model.host, model.port, timeout=120)
            start = monotonic()
            try:
                body = json.dumps({'model': model.model, 'keep_alive': '30m', 'stream': False})
                connection.request('POST', '/api/chat', body, {'Content-Type': 'application/json'})
                with connection.getresponse() as response:
                    if response.status != 200:
                        raise ValueError(f'Ollama warmup returned HTTP {response.status}; check ollama list')
                    if json.loads(response.read(65537)).get('done') is not True:
                        raise ValueError('Ollama did not finish warming up')
            finally:
                connection.close()
            print(f'Warmup: {monotonic() - start:.2f}s')
        checks = [
            ('staff', 'Which parcels are late?', STAFF_KINDS, 'overdue'),
            ('customer', 'What did I order?', CUSTOMER_KINDS, 'order_summary'),
            ('customer', 'How do I return an item?', CUSTOMER_KINDS, 'returns_help'),
        ]
        passed = True
        for role, message, allowed, expected in checks:
            start = monotonic()
            result = model.route({'role': role, 'message': message, 'allowed_actions': list(allowed)})['kind']
            elapsed = monotonic() - start
            ok = result == expected and elapsed < 4.5
            passed &= ok
            print(f'{role}: {result} (expected {expected}, {elapsed:.2f}s) {"PASS" if ok else "FAIL"}')
        start = monotonic()
        actions = [{'kind': 'request_review', 'reason': 'unknown_evidence'}, {'kind': 'read', 'tool': 'payment'}]
        result = model.specialist({'binding': {}, 'features': {
            'specialist': 'order', 'report': 'Check whether the order was paid.',
            'observations': {'observations': []}, 'allowed_actions': actions,
        }}, timeout_ms=5000, cancel=None)
        elapsed = monotonic() - start
        ok = result['action'] == actions[1] and elapsed < 4.5
        print(f'order specialist: {result["action"]} (expected payment read, {elapsed:.2f}s) {"PASS" if ok else "FAIL"}')
        return 0 if passed and ok else 1
    except (OSError, ValueError, http.client.HTTPException) as error:
        print(f'Local model check failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
