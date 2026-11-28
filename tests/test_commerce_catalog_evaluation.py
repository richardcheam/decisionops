"""Dependency-free catalog evaluation tests. No real Ollama calls."""

import json
import shutil
from pathlib import Path
import tempfile
import unittest

from decisionops.commerce.catalog_evaluation import (
    FIXTURES, SINGLE_FORMAT, VISUAL_FORMAT, VisionUnavailable, compare,
)


class CatalogEvaluationTests(unittest.TestCase):
    def test_missing_model_keeps_vision_outcomes_unobserved(self):
        report = compare(unavailable_reason='unsupported fixture model')
        self.assertEqual(set(row['case'] for row in report['rows']),
                         {'BOTTLE-GREEN', 'MUG-CREAM', 'BOTTLE-GRAY'})
        rule = report['summary']['mapping_rule']
        self.assertEqual((rule['observed'], rule['exact_matches'], rule['missed_referrals']), (3, 2, 1))
        for arm in ('single_vision', 'visual_and_catalog'):
            result = report['summary'][arm]
            self.assertEqual((result['observed'], result['unavailable']), (0, 3))
            self.assertIsNone(result['wrong_fixes'])
            self.assertIsNone(result['missed_defects'])
            self.assertIsNone(result['appropriate_referrals'])
            self.assertIsNone(result['median_observed_ms'])

    def test_label_and_case_metadata_never_reach_visual_prompts(self):
        calls = []

        def simulated_vision(prompt, paths, schema):
            calls.append((prompt, paths, schema))
            self.assertNotIn('SECRET_EVALUATION_LABEL', prompt)
            self.assertNotIn('heldout', prompt)
            if schema == SINGLE_FORMAT:
                return {'action': 'keep'}
            self.assertNotIn('BOTTLE-GREEN', prompt)
            return {'current': 'coral bottle', 'candidate': 'green bottle', 'comparison': 'different'}

        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / 'catalog'
            shutil.copytree(FIXTURES, snapshot)
            case_file = snapshot / 'cases.json'
            cases = json.loads(case_file.read_text())
            for case in cases:
                case['expected'] = 'SECRET_EVALUATION_LABEL'
            case_file.write_text(json.dumps(cases))
            report = compare(snapshot, vision=simulated_vision)
        self.assertEqual([schema for _, _, schema in calls], [SINGLE_FORMAT]*3 + [VISUAL_FORMAT]*3)
        workflow = report['summary']['visual_and_catalog']
        self.assertEqual((workflow['exact_matches'], workflow['appropriate_referrals']), (3, 1))
        self.assertEqual(report['summary']['single_vision']['missed_defects'], 1)

    def test_malformed_output_and_transport_rejection_are_distinct(self):
        def simulated_vision(_prompt, _paths, schema):
            if schema == VISUAL_FORMAT:
                raise VisionUnavailable('fake loopback rejection')
            return {'action': ['relink']}

        report = compare(vision=simulated_vision)
        self.assertEqual(report['summary']['single_vision']['invalid'], 3)
        self.assertEqual(report['summary']['visual_and_catalog']['unavailable'], 3)
        self.assertTrue(all(row['elapsed_ms'] is not None for row in report['rows']))

    def test_missing_supplier_is_a_catalog_referral(self):
        def simulated_vision(_prompt, _paths, schema):
            if schema == SINGLE_FORMAT:
                return {'action': 'review'}
            return {'current': 'gray bottle', 'candidate': 'unknown', 'comparison': 'uncertain'}

        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / 'catalog'
            shutil.copytree(FIXTURES, snapshot)
            case_file = snapshot / 'cases.json'
            cases = json.loads(case_file.read_text())
            next(case for case in cases if case['id'] == 'BOTTLE-GRAY')['supplier'] = None
            case_file.write_text(json.dumps(cases))
            report = compare(snapshot, vision=simulated_vision)
        row = next(row for row in report['rows']
                   if row['case'] == 'BOTTLE-GRAY' and row['arm'] == 'visual_and_catalog')
        self.assertEqual(row['status'], 'observed')
        self.assertEqual(row['action'], 'review')
        self.assertIn('supplier', row['catalog']['reason'])

    def test_invalid_outer_json_is_a_per_case_result(self):
        from unittest.mock import patch
        from decisionops.commerce.catalog_evaluation import LocalVision

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size):
                return b'[]'

        with patch('http.client.HTTPConnection') as connection:
            connection.return_value.getresponse.return_value = Response()
            instance = object.__new__(LocalVision)
            instance.model = 'test'
            instance.host = '127.0.0.1'
            instance.port = 11434
            report = compare(vision=instance)
        self.assertEqual(report['summary']['single_vision']['invalid'], 3)
        self.assertEqual(report['summary']['visual_and_catalog']['invalid'], 3)

    def test_both_vision_arms_get_supplier_image_even_for_referrals(self):
        calls = []

        def simulated_vision(_prompt, paths, schema):
            calls.append(tuple(path.stem for path in paths))
            if schema == SINGLE_FORMAT:
                return {'action': 'relink'}
            return {'current': 'gray bottle', 'candidate': 'coral bottle', 'comparison': 'different'}

        report = compare(vision=simulated_vision)
        self.assertEqual(calls[:3], calls[3:])
        self.assertIn(('bottle-gray', 'bottle-coral'), calls)
        self.assertEqual(report['summary']['single_vision']['wrong_fixes'], 2)
        self.assertEqual(report['summary']['visual_and_catalog']['wrong_fixes'], 0)

    def test_rejects_heldout_image_bytes_reused_under_a_new_id(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / 'catalog'
            shutil.copytree(FIXTURES, snapshot)
            shutil.copyfile(snapshot / 'images' / 'tote-blue.png', snapshot / 'images' / 'bottle-green.png')
            with self.assertRaisesRegex(ValueError, 'disjoint image bytes'):
                compare(snapshot)
        report = compare()
        self.assertIn('bottle-green', report['assets_sha256'])
        self.assertNotIn('tote-blue', report['assets_sha256'])

    def test_remote_alias_is_rejected_before_inference(self):
        from unittest.mock import patch
        from decisionops.commerce.catalog_evaluation import LocalVision

        installed = {'models': [{'name': 'renamed:latest', 'size': 1, 'remote_host': 'https://ollama.com'}]}
        with patch.object(LocalVision, '_request', return_value=installed) as request:
            with self.assertRaisesRegex(ValueError, 'weights installed'):
                LocalVision('renamed:latest')
        request.assert_called_once_with('GET', '/api/tags')
