"""Verification against a real pytest, when one is available.

The fake runner exercises the parsing path deterministically; this asserts the
adapter's reporting flags are ones pytest genuinely accepts and that the report
it produces has the structure the adapter reads. Skipped where pytest is absent
so the suite stays runnable with no third-party packages installed.
"""

import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from support import FAILING_SUITE, PASSING_SUITE, RepoCase  # noqa: E402
from toucan import baseline as baseline_mod, criteria  # noqa: E402
from toucan.errors import Refusal  # noqa: E402


def _find_pytest():
    for candidate in (
        os.environ.get("TOUCAN_TEST_PYTEST"),
        shutil.which("pytest"),
    ):
        if candidate and os.path.exists(candidate):
            return candidate
    return None


PYTEST = _find_pytest()


@unittest.skipUnless(PYTEST, "no pytest executable available")
class RealPytestTest(RepoCase):
    suite_source = FAILING_SUITE

    def oracle_for(self, timeout=180):
        return {
            "argv": [PYTEST, "-q"],
            "cwd": ".",
            "timeout_seconds": timeout,
            "adapter": "pytest",
            "execution_evidence": "JUnit XML report listing each test case.",
        }

    def test_adapter_flags_are_accepted_by_pytest(self):
        record = baseline_mod.capture(self.repo, self.oracle_for())
        self.assertEqual(record["measurements"]["source"], "runner")

    def test_counts_match_the_fixture_suite(self):
        record = baseline_mod.capture(self.repo, self.oracle_for())
        measurements = record["measurements"]
        self.assertEqual(measurements["collected"], 4)
        self.assertEqual(measurements["passed"], 2)
        self.assertEqual(measurements["failed"], 2)

    def test_failing_target_identities_are_recovered(self):
        record = baseline_mod.capture(self.repo, self.oracle_for())
        failing = record["measurements"]["failing_targets"]
        self.assertEqual(len(failing), 2)
        names = " ".join(failing)
        self.assertIn("test_broken", names)
        self.assertIn("test_also_broken", names)

    def test_ladder_is_built_from_real_target_names(self):
        record = baseline_mod.capture(self.repo, self.oracle_for())
        narrow = criteria.ladder(record)[0]
        self.assertIn("test_broken", narrow["criterion"])


@unittest.skipUnless(PYTEST, "no pytest executable available")
class RealPytestGreenTest(RepoCase):
    suite_source = PASSING_SUITE

    def test_green_suite_is_refused_as_a_baseline(self):
        record = baseline_mod.capture(
            self.repo,
            {
                "argv": [PYTEST, "-q"],
                "cwd": ".",
                "timeout_seconds": 180,
                "adapter": "pytest",
                "execution_evidence": "JUnit XML report.",
            },
        )
        self.assertEqual(record["measurements"]["failed"], 0)
        with self.assertRaises(Refusal):
            baseline_mod.require_actionable(record)
