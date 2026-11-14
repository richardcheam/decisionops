"""Immutable portfolio evidence and static navigation checks; no model/runtime I/O."""
import hashlib,json,unittest
from html.parser import HTMLParser
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PUBLIC=ROOT/'frontend/public'
class PortfolioEvidenceTests(unittest.TestCase):
    def test_negative_live_outcome_is_summarized_without_publishing_raw_trace(self):
        summary=json.loads((PUBLIC/'evidence/summary.json').read_text())
        self.assertTrue(summary['raw_artifacts_archived'])
        self.assertEqual(summary['historical_decisions']['outcome'],'review')
        self.assertFalse(summary['historical_decisions']['proposal'])
        self.assertEqual(summary['historical_decisions']['raw_sha256'],'fc42a072225215c4cccd42627a6bb9d858146b721be341facf6c301f9b216bda')
        for raw in ('decisions-live-trace.json','browser-live-failure-trace.html','browser-offline-trace.html'):
            self.assertFalse((PUBLIC/'evidence'/raw).exists())
    def test_every_static_evidence_copy_matches_its_manifest(self):
        for row in json.loads((PUBLIC/'evidence/manifest.json').read_text()):
            with self.subTest(file=row['file']):
                self.assertEqual(hashlib.sha256((PUBLIC/'evidence'/row['file']).read_bytes()).hexdigest(),row['sha256'])
                self.assertFalse(row['source'].startswith('/'))
    def test_walkthrough_has_only_existing_local_resources_and_no_script(self):
        class Links(HTMLParser):
            def __init__(self):super().__init__();self.links=[];self.scripts=0
            def handle_starttag(self,tag,attrs):
                if tag=='script':self.scripts+=1
                self.links.extend(v for k,v in attrs if k in ('src','href'))
        page=Links();page.feed((PUBLIC/'portfolio.html').read_text())
        self.assertEqual(page.scripts,0)
        for target in page.links:
            self.assertFalse('://' in target or target.startswith('//'),target)
            self.assertFalse(target.startswith('/'), 'Static resources must work under a subpath')
            self.assertTrue((PUBLIC/target).is_file(),target)
    def test_public_walkthrough_does_not_distribute_an_invitation(self):
        text=(PUBLIC/'portfolio.html').read_text()
        self.assertNotIn('fictional-portfolio-visitor',text)
        self.assertNotIn('Open the staff workspace',text)
        self.assertIn('read-only',text.lower())
