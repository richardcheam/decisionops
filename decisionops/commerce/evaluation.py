"""Model-free, reproducible evidence regression report; no database or providers."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

from .eligibility import REQUIREMENTS
from .evidence import assess_evidence, utc_timestamp

ROOT = Path(__file__).resolve().parents[2]


def evaluate(dataset, fixture):
    if dataset['schema_version'] != 1 or dataset['kind'] != 'hand_inspected_regression':
        raise ValueError('Unsupported regression dataset')
    now = utc_timestamp(dataset['as_of'])
    results = []
    ids = set()
    for case in dataset['cases']:
        if not isinstance(case['id'],str) or case['id'] in ids:
            raise ValueError('Case IDs must be unique strings')
        ids.add(case['id'])
        if set(case['changes']) - set(REQUIREMENTS):
            raise ValueError('Unknown changed requirement')
        observations = deepcopy(fixture['observations'])
        for record in observations:
            changes = case['changes'].get(record['requirement'], {})
            if set(changes) - {'observed_at','value','status','order_id','source_id','source_version'}:
                raise ValueError('Unsupported evidence change')
            record.update(changes)
        if 'contradict' in case:
            if case['contradict'] not in REQUIREMENTS:
                raise ValueError('Unknown contradictory requirement')
            conflicting = deepcopy(next(record for record in observations if record['requirement'] == case['contradict']))
            conflicting['value'] = False
            conflicting['source_version'] = 'contradictory-version'
            observations.append(conflicting)
        started = time.perf_counter()
        # customer_text is deliberately not a source of business permission.
        assessment = assess_evidence(observations, order_id=fixture['order_id'],
            supported_case=case.get('supported_case',fixture['supported_case']),now=now,
            trusted_sources=fixture['trusted_sources'],max_age_seconds=fixture['max_age_seconds'])
        actual = assessment['decision']
        results.append({'id':case['id'],'passed':actual == case['expected'],
                        'expected':case['expected'],'actual':actual,
                        'established_requirements':sum(value is not None for value in assessment['facts'].values()),
                        'required_requirements':len(REQUIREMENTS),'issues':assessment['issues'],
                        'elapsed_ms':round((time.perf_counter()-started)*1000,3)})
    if not results:
        raise ValueError('Regression dataset cannot be empty')
    passed = sum(result['passed'] for result in results)
    return {'schema_version':1,'kind':'commerce_regression_report',
            'evidence_level':'hand_inspected_regression',
            'native_input':'trusted fictional adapter attestations; no language interpretation',
            'as_of':dataset['as_of'],'passed':passed,'failed':len(results)-passed,
            'provider_calls':0,'tool_calls':0,'input_tokens':0,'output_tokens':0,'cost_usd':'0',
            'execution_verification':'not measured by this fixture report; see PostgreSQL and browser tests',
            'results':results}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,default=ROOT/'data/commerce/regression-v1.json')
    parser.add_argument('--fixture',type=Path,default=ROOT/'data/commerce/eligible.json')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    try:
        dataset_raw=args.dataset.read_bytes()
        fixture_raw=args.fixture.read_bytes()
        report=evaluate(json.loads(dataset_raw),json.loads(fixture_raw))
        report.update(dataset_sha256=hashlib.sha256(dataset_raw).hexdigest(),fixture_sha256=hashlib.sha256(fixture_raw).hexdigest())
        rendered=json.dumps(report,indent=2)+'\n'
        if args.output:
            with args.output.open('x') as output:
                output.write(rendered)
        print(rendered,end='')
        return 1 if report['failed'] else 0
    except (OSError,ValueError,TypeError,KeyError,StopIteration) as error:
        print(json.dumps({'event':'evaluation_input_error','error':str(error)}),file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
