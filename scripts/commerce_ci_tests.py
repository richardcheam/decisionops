"""Run model-free checks or required PostgreSQL tests with explicit skip accounting."""
import argparse
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATABASE_MODULES = (
    'test_commerce_postgres', 'test_commerce_investigations',
    'test_commerce_execution', 'test_commerce_jobs', 'test_commerce_api',
)


class CountingResult(unittest.TextTestResult):
    passed = 0

    def addSuccess(self, test):
        self.passed += 1
        super().addSuccess(test)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', choices=('dependency-free', 'postgres'))
    args = parser.parse_args()
    loader = unittest.TestLoader()
    if args.profile == 'postgres':
        if not os.environ.get('COMMERCE_TEST_DATABASE_URL'):
            parser.error('postgres profile requires COMMERCE_TEST_DATABASE_URL')
        sys.path.insert(0, str(ROOT / 'tests'))
        suite = unittest.TestSuite()
        for module in DATABASE_MODULES:
            tests = loader.loadTestsFromName(module)
            if not tests.countTestCases():
                parser.error(f'No tests collected from {module}')
            suite.addTests(tests)
    else:
        # This command must be launched with -S; dependency-free CI cannot
        # silently gain site-packages or run opted-in database/model checks.
        if not sys.flags.no_site:
            parser.error('dependency-free profile requires python -S')
        os.environ.pop('COMMERCE_TEST_DATABASE_URL', None)
        suite = loader.discover(str(ROOT / 'tests'))
    result = unittest.TextTestRunner(verbosity=2, resultclass=CountingResult).run(suite)
    summary = {
        'profile': args.profile, 'collected': result.testsRun,
        'passed': result.passed,
        'failures': len(result.failures), 'errors': len(result.errors),
        'skipped': [{'test': str(test), 'reason': reason} for test, reason in result.skipped],
    }
    print(json.dumps(summary, indent=2))
    required_skipped = args.profile == 'postgres' and bool(result.skipped)
    return 0 if result.wasSuccessful() and result.testsRun and not required_skipped else 1


if __name__ == '__main__':
    raise SystemExit(main())
