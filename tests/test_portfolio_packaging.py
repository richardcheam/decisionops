"""Release entry-point checks; no Docker service, credentials or provider calls."""
import os
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
class PortfolioPackagingTests(unittest.TestCase):
    def test_supported_build_has_no_sibling_or_private_configuration_dependency(self):
        text=(ROOT/'compose.demo.yaml').read_text()
        self.assertIn('docker/Dockerfile.app',text)
        self.assertIn('docker/Dockerfile.web',text)
        self.assertNotIn('Dockerfile.portfolio-',text)
        self.assertNotIn('OPENAI_API_KEY',text)
        self.assertIn('COMMERCE_DEMO_MODE:-rules',text)
        self.assertIn(':-8133',text)
        self.assertNotIn('env_file:',text)
        readme=(ROOT/'README.md').read_text()
        self.assertNotIn('../stage5-correction',readme)
        self.assertIn('bash scripts/demo.sh build',readme)
        self.assertIn('COMMERCE_DEMO_MODE=mock-specialists',readme)
    def test_launcher_rejects_short_password_and_paid_mode_before_docker(self):
        for password,mode in [('short','rules'),('fictional-unit-password-only','openai')]:
            with self.subTest(mode=mode):
                result=subprocess.run(['bash',str(ROOT/'scripts/demo.sh'),'start'],
                    env={'PATH':os.defpath,'COMMERCE_DEMO_PASSWORD':password,'COMMERCE_DEMO_MODE':mode},capture_output=True,text=True,timeout=3)
                self.assertEqual(result.returncode,2)
                self.assertNotIn('command not found',result.stderr)
