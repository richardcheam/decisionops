"""Pure target-selection guards; never invoke Docker, HTTP or a database."""
import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import commerce_portfolio_verify as v


class RehearsalConfigTests(unittest.TestCase):
    def options(self, **changes):
        options={'--project':'decisionops-portfolio-rc-final','--port':'8103',
                 '--public-url':'http://127.0.0.1:8104','--output':'runs/portfolio-rc-final'}
        options.update(changes)
        return [item for key,value in options.items() for item in (key,value)]

    def reject(self, argv):
        with contextlib.redirect_stderr(io.StringIO()), patch.object(v,'docker',side_effect=AssertionError('No Docker')), patch.object(v.urllib.request,'urlopen',side_effect=AssertionError('No HTTP')):
            with self.assertRaises(SystemExit):v.rehearsal_config(argv)

    def test_explicit_target_is_required(self):
        self.reject([])

    def test_release_retains_exact_original_explicit_behavior(self):
        result=v.rehearsal_config(['--release'])
        self.assertEqual(result['project'],'decisionops-portfolio-release')
        self.assertEqual(result['port'],8093)
        self.assertEqual(result['public_url'],'http://127.0.0.1:8094')
        self.assertEqual(result['output'],v.ROOT/'runs/portfolio-release')
        self.reject(['--release','--port','8103'])
        self.reject(['--release','--project','decisionops-portfolio-rc'])

    def test_new_namespace_explicit_ports_output_and_override(self):
        for project in ('decisionops-portfolio-rc','decisionops-portfolio-rc-final-2',
                        'decisionops-portfolio-rehearsal','decisionops-portfolio-rehearsal-new'):
            with self.subTest(project=project):
                result=v.rehearsal_config(self.options(**{'--project':project,'--compose-override':'/tmp/portfolio-rc.yaml'}))
                self.assertEqual(result['project'],project)
                self.assertEqual(result['port'],8103)
                self.assertEqual(result['public_url'],'http://127.0.0.1:8104')
                self.assertEqual(result['output'],(v.ROOT/'runs/portfolio-rc-final').resolve())
                self.assertEqual(result['compose_override'],Path('/tmp/portfolio-rc.yaml'))
                self.assertFalse(result['release'])

    def test_original_and_ambiguous_project_names_are_rejected(self):
        for project in ('decisionops-portfolio-release','decisionops-portfolio-verify','decisionops-staff-demo',
                        'decisionops-portfolio-rc-','decisionops-portfolio-rcfoo','decisionops-portfolio-rc/other',
                        'decisionops-portfolio-rc--new','decisionops-portfolio-rc-NEW'):
            with self.subTest(project=project):self.reject(self.options(**{'--project':project}))

    def test_rc_requires_all_target_fields(self):
        for flag in ('--port','--public-url','--output'):
            argv=self.options();index=argv.index(flag);del argv[index:index+2]
            with self.subTest(flag=flag):self.reject(argv)

    def test_protected_and_invalid_staff_ports_are_rejected(self):
        for port in sorted(v.PROTECTED_PORTS|{0,80,1023,65536}):
            with self.subTest(port=port):self.reject(self.options(**{'--port':str(port)}))

    def test_public_target_cannot_access_original_or_remote_services(self):
        urls=['http://127.0.0.1:'+str(p) for p in sorted(v.PROTECTED_PORTS|{80,8103,65536})]
        urls+=['https://127.0.0.1:8104','http://example.com:8104','http://127.0.0.1',
               'http://user:pass@127.0.0.1:8104','http://127.0.0.1:8104/api',
               'http://127.0.0.1:8104?query=1','http://127.0.0.1:8104#fragment','http://127.0.0.1:bad']
        for url in urls:
            with self.subTest(url=url):self.reject(self.options(**{'--public-url':url}))

    def test_original_evidence_output_is_rejected(self):
        for output in ('runs/portfolio-demo','runs/portfolio-release'):
            with self.subTest(output=output):self.reject(self.options(**{'--output':str(v.ROOT/output)}))
