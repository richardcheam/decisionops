"""Read-only comparison of catalog recommendations on fictional cases."""

import argparse
import base64
import hashlib
import http.client
import json
from pathlib import Path
import re
from statistics import median
from time import perf_counter

from .local_llm import LocalModel

FIXTURES = Path(__file__).resolve().parents[2] / 'data' / 'commerce' / 'catalog'
ARMS = ('mapping_rule', 'single_vision', 'visual_and_catalog')
ACTIONS = ('keep', 'relink', 'review')
SINGLE_FORMAT = {
    'type': 'object',
    'properties': {'action': {'enum': list(ACTIONS)}},
    'required': ['action'],
    'additionalProperties': False,
}
VISUAL_FORMAT = {
    'type': 'object',
    'properties': {
        'current': {'type': 'string', 'minLength': 1, 'maxLength': 300},
        'candidate': {'type': 'string', 'minLength': 1, 'maxLength': 300},
        'comparison': {'enum': ['same', 'different', 'uncertain', 'no_candidate']},
    },
    'required': ['current', 'candidate', 'comparison'],
    'additionalProperties': False,
}


class VisionUnavailable(RuntimeError):
    """An attempted request could not return a vision result."""


class LocalVision:
    """The benchmark only sends image bytes to a locally installed loopback tag."""

    def __init__(self, model, endpoint='http://127.0.0.1:11434'):
        transport = LocalModel(model, endpoint)
        if transport.host not in ('127.0.0.1', '::1'):
            raise ValueError('Catalog evaluation requires a literal loopback Ollama endpoint')
        self.model = model
        self.host, self.port = transport.host, transport.port
        installed = self._request('GET', '/api/tags')
        models = installed.get('models')
        if not isinstance(models, list) or not any(
            isinstance(row, dict) and row.get('name') == model
            and not row.get('remote_model') and not row.get('remote_host')
            and type(row.get('size')) is int and row['size'] > 0
            for row in models
        ):
            raise ValueError('Use an exact model tag with weights installed in local Ollama')

    def _request(self, method, path, payload=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=30)
        try:
            connection.request(method, path, None if payload is None else json.dumps(payload),
                               {'Content-Type': 'application/json'})
            with connection.getresponse() as response:
                raw = response.read(65537)
                if response.status != 200:
                    raise VisionUnavailable(f'Ollama HTTP {response.status}')
                if len(raw) > 65536:
                    raise ValueError('Ollama reply exceeds the response cap')
                reply = json.loads(raw)
                if not isinstance(reply, dict):
                    raise ValueError('Expected an Ollama JSON object')
                return reply
        except (OSError, http.client.HTTPException) as error:
            raise VisionUnavailable(type(error).__name__) from error
        finally:
            connection.close()

    def __call__(self, prompt, paths, schema):
        encoded = []
        for path in paths:
            with path.open('rb') as image:
                content = image.read(262145)
            if not content.startswith(b'\x89PNG\r\n\x1a\n') or len(content) > 262144:
                raise ValueError('Use a PNG fixture of at most 256 KiB')
            encoded.append(base64.b64encode(content).decode('ascii'))
        response = self._request('POST', '/api/chat', {
            'model': self.model,
            'stream': False,
            'think': False,
            'format': schema,
            'options': {'temperature': 0, 'num_predict': 192},
            'messages': [{'role': 'user', 'content': prompt, 'images': encoded}],
        })
        message = response.get('message')
        if response.get('done') is not True or not isinstance(message, dict):
            raise ValueError('Incomplete Ollama reply')
        content = message.get('content')
        if not isinstance(content, str) or len(content) > 4096:
            raise ValueError('Invalid Ollama message content')
        return json.loads(content)


def scoped_catalog(case):
    # The loader never passes arbitrary keys (including labels) to either prompt.
    return {
        'sku': case['sku'],
        'visual_traits': list(case['visual_traits']),
        'current_image_id': case['current_image_id'],
        'images': [{key: item[key] for key in ('id', 'sku', 'verified')} for item in case['images']],
        'supplier': None if case['supplier'] is None else {
            key: case['supplier'][key] for key in ('sku', 'image_id', 'verified')
        },
    }


def mapping_rule(case):
    candidates = {row['id'] for row in case['images'] if row['verified'] and row['sku'] == case['sku']}
    if case['current_image_id'] in candidates:
        return 'keep', None
    if len(candidates) == 1:
        return 'relink', candidates.pop()
    return 'review', None


def _comparison_candidate(case):
    current = case['current_image_id']
    supplier = case['supplier']
    alternatives = [row for row in case['images'] if row['id'] != current]
    ids = {row['id'] for row in alternatives}
    if supplier and supplier['image_id'] in ids:
        return supplier['image_id']
    matching = {row['id'] for row in alternatives if row['verified'] and row['sku'] == case['sku']}
    return next(iter(matching)) if len(matching) == 1 else None


def _asset(directory, identity):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', identity):
        raise ValueError('Invalid fixture image ID')
    path = directory / 'images' / (identity + '.png')
    if not path.is_file():
        raise ValueError(f'Missing fixture image {identity}')
    return path


def _vision_result(arm, case, paths, candidate, vision):
    if arm == 'single_vision':
        prompt = (
            'First image is the current listing. A second image, if present, is the candidate. '
            'Use the images and supplied listing, SKU mappings, and verified supplier record '
            'to recommend keep, relink to the candidate, or review. Review missing or '
            'conflicting authority. Never relink to any other image. Catalog data follows.\n'
            + json.dumps(case, sort_keys=True)
        )
        result = vision(prompt, paths, SINGLE_FORMAT)
        if not isinstance(result, dict) or set(result) != {'action'} or result['action'] not in ACTIONS:
            raise ValueError('Invalid single-call recommendation')
        if result['action'] == 'relink' and candidate is None:
            raise ValueError('Relink selected without a candidate')
        return result['action'], candidate if result['action'] == 'relink' else None, {}

    from .catalog_policy import assess

    result = vision(
        'Describe the visible object and colors in the first image and, if present, the second. '
        'Compare visible traits as same, different, uncertain, or no_candidate. '
        'Report uncertainty when lighting, framing or ambiguity prevents comparison. '
        'You have no authority to identify SKUs or choose a listing action.',
        paths, VISUAL_FORMAT,
    )
    if (not isinstance(result, dict) or set(result) != {'current', 'candidate', 'comparison'}
            or result['comparison'] not in ('same', 'different', 'uncertain', 'no_candidate')
            or any(not isinstance(result[key], str) or not 1 <= len(result[key]) <= 300
                   for key in ('current', 'candidate'))):
        raise ValueError('Invalid visual description')
    action, target, reason = assess(case)
    evidence = {'visual': result, 'catalog': {'action': action, 'image_id': target, 'reason': reason}}
    if action == 'relink' and (result['comparison'] != 'different' or target != candidate):
        action, target = 'review', None
    return action, target, evidence


def _asset_hashes(directory, cases, split):
    partitions = {'demo': set(), 'heldout': set()}
    assets = {}
    for case in cases:
        ids = {case['current_image_id'], *(item['id'] for item in case['images'])}
        for identity in ids:
            if identity not in assets:
                assets[identity] = hashlib.sha256(_asset(directory, identity).read_bytes()).hexdigest()
            partitions[case['split']].add(assets[identity])
    if partitions['demo'] & partitions['heldout']:
        raise ValueError('Demo and held-out cases must use disjoint image bytes')
    selected = {case['current_image_id'] for case in cases if case['split'] == split}
    selected.update(item['id'] for case in cases if case['split'] == split for item in case['images'])
    return {identity: assets[identity] for identity in sorted(selected)}


def compare(directory=FIXTURES, *, split='heldout', vision=None, unavailable_reason=None):
    raw_cases = (directory / 'cases.json').read_bytes()
    raw_labels = (directory / 'labels.json').read_bytes()
    cases, labels = json.loads(raw_cases), json.loads(raw_labels)
    if len({case['id'] for case in cases}) != len(cases) or set(labels) != {case['id'] for case in cases}:
        raise ValueError('Case IDs and the separately held labels must match one-to-one')
    for label in labels.values():
        if (set(label) != {'action', 'image_id'} or label['action'] not in ACTIONS
                or (isinstance(label['image_id'], str) != (label['action'] == 'relink'))
                or (label['action'] != 'relink' and label['image_id'] is not None)):
            raise ValueError('Invalid evaluation label')
    selected = [case for case in cases if case['split'] == split]
    if not selected:
        raise ValueError('Selected split contains no cases')
    asset_hashes = _asset_hashes(directory, cases, split)
    rows = []
    for arm in ARMS:
        for fixture in selected:
            case = scoped_catalog(fixture)
            label = labels[fixture['id']]
            row = {'case': fixture['id'], 'arm': arm, 'status': 'unavailable', 'elapsed_ms': None,
                   'expected': label, 'action': None, 'image_id': None}
            candidate = _comparison_candidate(case)
            paths = [_asset(directory, case['current_image_id'])]
            if candidate:
                paths.append(_asset(directory, candidate))
            if arm != 'mapping_rule' and vision is None:
                row['reason'] = unavailable_reason or 'No local vision model selected'
            else:
                start = perf_counter()
                try:
                    if arm == 'mapping_rule':
                        row['action'], row['image_id'] = mapping_rule(case)
                    else:
                        action, target, evidence = _vision_result(arm, case, paths, candidate, vision)
                        row.update(action=action, image_id=target, **evidence)
                    row['status'] = 'observed'
                except VisionUnavailable as error:
                    row['reason'] = str(error)
                except (ValueError, TypeError, KeyError) as error:
                    row['status'] = 'invalid'
                    row['reason'] = type(error).__name__
                finally:
                    row['elapsed_ms'] = round((perf_counter() - start) * 1000, 3)
            rows.append(row)
    summary = {}
    for arm in ARMS:
        group = [row for row in rows if row['arm'] == arm]
        observed = [row for row in group if row['status'] == 'observed']
        timings = [row['elapsed_ms'] for row in observed]
        summary[arm] = {
            'cases': len(group),
            'observed': len(observed),
            'unavailable': sum(row['status'] == 'unavailable' for row in group),
            'invalid': sum(row['status'] == 'invalid' for row in group),
            'wrong_fixes': sum(
                row['action'] == 'relink' and (row['expected']['action'] != 'relink'
                or row['image_id'] != row['expected']['image_id']) for row in observed
            ) if observed else None,
            'missed_defects': sum(
                row['expected']['action'] == 'relink' and (row['action'] != 'relink'
                or row['image_id'] != row['expected']['image_id']) for row in observed
            ) if observed else None,
            'appropriate_referrals': sum(
                row['action'] == row['expected']['action'] == 'review' for row in observed
            ) if observed else None,
            'missed_referrals': sum(
                row['expected']['action'] == 'review' and row['action'] != 'review' for row in observed
            ) if observed else None,
            'exact_matches': sum(
                row['action'] == row['expected']['action'] and row['image_id'] == row['expected']['image_id']
                for row in observed
            ) if observed else None,
            'median_observed_ms': median(timings) if timings else None,
        }
    return {'split': split, 'cases_sha256': hashlib.sha256(raw_cases).hexdigest(),
            'labels_sha256': hashlib.sha256(raw_labels).hexdigest(), 'assets_sha256': asset_hashes,
            'summary': summary, 'rows': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', choices=('demo', 'heldout'), default='heldout')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--model', help='Exact installed Ollama vision tag')
    modes.add_argument('--unavailable-reason', help='Document an independently verified capability blocker')
    parser.add_argument('--endpoint', default='http://127.0.0.1:11434')
    args = parser.parse_args()
    try:
        vision = LocalVision(args.model, args.endpoint) if args.model else None
        report = compare(split=args.split, vision=vision, unavailable_reason=args.unavailable_reason)
    except (ValueError, VisionUnavailable) as error:
        parser.error(str(error))
    print(json.dumps(report | {'model': args.model}, indent=2))


if __name__ == '__main__':
    main()
