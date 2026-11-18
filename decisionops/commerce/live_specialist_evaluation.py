"""Opt-in OpenAI evaluation for the frozen, fictional specialist cases."""
import argparse
import json
import os
from threading import Lock
from time import monotonic

from .observability import SafeTracer
from .specialist_contracts import MockSpecialist, validate_action

MAX_CALLS = 40
MAX_OUTPUT_TOKENS = 128
TRANSPORT_TIMEOUT_SECONDS = 3


class OpenAISpecialistTransport:
    def __init__(self, client, model, *, max_calls, tracer=None):
        if type(max_calls) is not int or not 1 <= max_calls <= MAX_CALLS:
            raise ValueError(f'Choose a request cap between 1 and {MAX_CALLS}')
        self.client = client
        self.model = model
        self.max_calls = max_calls
        self.tracer = tracer
        self.lock = Lock()
        self.calls = []
        self.budget_denials = 0
        self.choice_sources = {}

    decision_source = 'openai_specialist_evaluation'

    def choose(self, request, cancel=None):
        if cancel is not None and cancel.is_set():
            raise RuntimeError('Specialist cancelled')
        try:
            action = validate_action(request, self({'role': 'specialist', 'features': request.features()}))
            source = 'provider'
        except Exception:
            action = MockSpecialist().choose(request, cancel)
            source = 'fallback'
        if source == 'fallback' and self.tracer is not None:
            self.tracer.emit(request.run_id, 'fallback', node=request.specialist,
                             tool=action.tool, sequence=request.ordinal, reason='fallback')
        with self.lock:
            self.choice_sources[request.call_id] = source
        return action

    def __call__(self, request):
        if request['role'] != 'specialist':
            raise ValueError('Only specialist decisions are part of this evaluation')
        features = request['features']
        options = features['allowed_actions']
        if not options:
            raise ValueError('No specialist choices available')
        observations = [
            {key: value for key, value in row.items() if key in ('tool', 'status', 'value', 'scope_known')}
            for row in features['observations']['observations']
        ]
        payload = json.dumps({
            'specialist': features['specialist'],
            'observations': observations,
            'options': options,
        })
        if len(payload.encode()) > 8192:
            raise ValueError('Specialist payload exceeds evaluation cap')

        with self.lock:
            if len(self.calls) >= self.max_calls:
                self.budget_denials += 1
                raise ValueError('Evaluation request cap reached')
            call = {'success': False, 'elapsed_ms': None, 'input_tokens': None, 'output_tokens': None}
            self.calls.append(call)

        started = monotonic()
        usage = None
        success = False
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=(
                    'Select the index of one listed action for this fictional delivery case. '
                    'Prefer a read that supplies a missing fact. Request review when the '
                    'available reads cannot resolve the relevant uncertainty.'
                ),
                input=payload,
                text={'format': {'type': 'json_schema', 'name': 'specialist_choice', 'strict': True,
                      'schema': {'type': 'object', 'properties': {'choice': {'type': 'integer'}},
                                 'required': ['choice'], 'additionalProperties': False}}},
                max_output_tokens=MAX_OUTPUT_TOKENS,
                store=False,
            )
            usage = response.usage
            if response.status != 'completed':
                raise ValueError('Incomplete model response')
            result = json.loads(response.output_text)
            if (not isinstance(result, dict) or set(result) != {'choice'}
                    or type(result['choice']) is not int or not 0 <= result['choice'] < len(options)):
                raise ValueError('Choice is outside the allowed actions')
            success = True
            return options[result['choice']]
        finally:
            with self.lock:
                call.update(success=success, elapsed_ms=round((monotonic() - started) * 1000, 3),
                            input_tokens=getattr(usage, 'input_tokens', None),
                            output_tokens=getattr(usage, 'output_tokens', None))

    def summary(self):
        with self.lock:
            settled = [call for call in self.calls if call['elapsed_ms'] is not None]
            return {
                'model': self.model,
                'max_calls': self.max_calls,
                'attempted_calls': len(self.calls),
                'unfinished_calls': len(self.calls) - len(settled),
                'unsuccessful_calls': sum(not call['success'] for call in settled),
                'budget_denials': self.budget_denials,
                'input_tokens': sum(call['input_tokens'] or 0 for call in settled),
                'output_tokens': sum(call['output_tokens'] or 0 for call in settled),
                'calls_with_reported_usage': sum(call['input_tokens'] is not None for call in settled),
                'request_elapsed_ms': [call['elapsed_ms'] for call in settled],
            }


    def annotate(self, report):
        with self.lock:
            sources = dict(self.choice_sources)
        for row in report['runs']:
            decisions = row.pop('specialist_decisions', [])
            if row['mode'] != 'injected_specialists':
                continue
            counts = {'provider_reads_applied': 0, 'provider_review_choices': 0,
                      'provider_other_dispositions': 0, 'fallback_choices': 0,
                      'unattributed_dispatched_choices': 0}
            for decision in decisions:
                source = sources.get(decision['id'])
                if source == 'provider':
                    if decision['disposition'] == 'applied':
                        counts['provider_reads_applied'] += 1
                    elif decision['error'] == 'specialist_requested_review':
                        counts['provider_review_choices'] += 1
                    else:
                        counts['provider_other_dispositions'] += 1
                elif source == 'fallback':
                    counts['fallback_choices'] += 1
                else:
                    counts['unattributed_dispatched_choices'] += 1
            row['specialist_choice_counts'] = counts


class EvaluationTracer(SafeTracer):
    def defer(self, callback):
        # Capture metadata before the evaluator disposes its temporary database.
        # The sink still runs asynchronously through SafeTracer.emit().
        callback()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True, help='OpenAI model ID with Structured Outputs support')
    parser.add_argument('--max-calls', required=True, type=int, choices=range(1, MAX_CALLS + 1),
                        metavar=f'1-{MAX_CALLS}')
    parser.add_argument('--langsmith', action='store_true', help='Export allowlisted metadata to LangSmith')
    args = parser.parse_args()
    api_key = os.environ.get('OPENAI_API_KEY')
    url = os.environ.get('COMMERCE_TEST_DATABASE_URL')
    if not url or not api_key:
        parser.error('Set disposable loopback COMMERCE_TEST_DATABASE_URL and OPENAI_API_KEY')
    key = os.environ.get('LANGSMITH_API_KEY')
    if args.langsmith and not key:
        parser.error('--langsmith requires LANGSMITH_API_KEY')

    from openai import OpenAI
    from .customer_evaluation import evaluate
    from .observability import LangSmithSink

    tracer = EvaluationTracer(enabled=args.langsmith, sink=LangSmithSink(key) if args.langsmith else None)
    with OpenAI(api_key=api_key, base_url='https://api.openai.com/v1',
                max_retries=0, timeout=TRANSPORT_TIMEOUT_SECONDS) as client:
        transport = OpenAISpecialistTransport(client, args.model, max_calls=args.max_calls, tracer=tracer)
        report = evaluate(url, specialist_adapter=transport, tracer=tracer)
        transport.annotate(report)
        report['live_specialist_requests'] = transport.summary()
    flushed = tracer.flush(timeout=10)
    report['trace_export'] = {
        'enabled': tracer.enabled, 'flushed': flushed, 'errors': tracer.errors, 'dropped': tracer.dropped,
        'hosted_readback_verified': False,
    }
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
