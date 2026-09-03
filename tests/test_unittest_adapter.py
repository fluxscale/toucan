"""The unittest adapter: wrapper report, detection, and end-to-end use."""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from support import RepoCase  # noqa: E402
from toucan import adapters, baseline as baseline_mod  # noqa: E402
from toucan.adapters import unittest_adapter  # noqa: E402

TOUCAN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "toucan"
)

UNITTEST_SUITE = '''
import unittest


class SampleTest(unittest.TestCase):
    def test_ok_one(self):
        self.assertEqual(1, 1)

    def test_ok_two(self):
        self.assertEqual(2, 2)

    def test_broken(self):
        self.assertEqual(1, 2)

    @unittest.skip("not today")
    def test_skipped(self):
        pass


if __name__ == "__main__":
    unittest.main()
'''


class UnittestRepoCase(RepoCase):
    suite_source = UNITTEST_SUITE

    def setUp(self):
        super().setUp()
        os.remove(os.path.join(self.repo, "pytest.ini"))


class WrapperReportTest(UnittestRepoCase):
    def run_wrapper(self):
        report_path = os.path.join(self.repo, "report.json")
        completed = subprocess.run(
            [sys.executable, TOUCAN, "unittest-run", "-s", "tests",
             "--report", report_path],
            cwd=self.repo, capture_output=True, text=True,
        )
        with open(report_path) as handle:
            return completed, json.load(handle)

    def test_counts_match_the_fixture_suite(self):
        completed, report = self.run_wrapper()
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(report["collected"], 4)
        self.assertEqual(report["passed"], 2)
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["skipped"], 1)

    def test_failing_identities_are_exact(self):
        _, report = self.run_wrapper()
        self.assertEqual(len(report["failing_targets"]), 1)
        self.assertIn("test_broken", report["failing_targets"][0])

    def test_green_suite_exits_zero(self):
        path = os.path.join(self.repo, "tests", "test_sample.py")
        with open(path, "w") as handle:
            handle.write(UNITTEST_SUITE.replace("self.assertEqual(1, 2)",
                                                "self.assertEqual(2, 2)"))
        completed, report = self.run_wrapper()
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(report["failed"], 0)


class UnittestDetectionTest(UnittestRepoCase):
    def test_importing_unittest_is_strong_evidence(self):
        candidates = unittest_adapter.detect(self.repo)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["evidence_strength"], "strong")
        self.assertIn("imports unittest", candidates[0]["evidence"])
        self.assertTrue(candidates[0]["runnable"])

    def test_argv_names_the_start_directory(self):
        candidate = unittest_adapter.detect(self.repo)[0]
        self.assertEqual(candidate["argv"], ["toucan", "unittest-run", "-s", "tests"])

    def test_pytest_style_tests_are_weak_evidence(self):
        path = os.path.join(self.repo, "tests", "test_sample.py")
        with open(path, "w") as handle:
            handle.write("def test_plain():\n    assert True\n")
        candidate = unittest_adapter.detect(self.repo)[0]
        self.assertEqual(candidate["evidence_strength"], "weak")

    def test_probe_does_not_execute_tests(self):
        marker = os.path.join(self.repo, "tests", "executed.marker")
        path = os.path.join(self.repo, "tests", "test_sample.py")
        with open(path, "w") as handle:
            handle.write(
                "import unittest\nopen(%r, 'w').close()\n\n"
                "class T(unittest.TestCase):\n    def test_x(self):\n"
                "        pass\n" % marker
            )
        unittest_adapter.probe(["toucan", "unittest-run", "-s", "tests"],
                               cwd=self.repo)
        self.assertFalse(os.path.exists(marker))


class UnittestBaselineTest(UnittestRepoCase):
    def test_baseline_measurements_come_from_the_runner(self):
        record = baseline_mod.capture(self.repo, {
            "argv": ["toucan", "unittest-run", "-s", "tests"],
            "cwd": ".",
            "timeout_seconds": 120,
            "adapter": "unittest",
            "execution_evidence": unittest_adapter.EXECUTION_EVIDENCE,
        })
        measurements = record["measurements"]
        self.assertEqual(measurements["source"], "runner")
        self.assertEqual(measurements["failed"], 1)
        self.assertIn("test_broken", measurements["failing_targets"][0])


class SelfHostingTest(RepoCase):
    """The bootstrap claim: Toucan detects a runnable oracle for itself."""

    def test_own_repository_detects_a_runnable_unittest_oracle(self):
        own_repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates = adapters.detect_all(own_repo)
        runnable = [c for c in candidates if c["runnable"]]
        self.assertTrue(runnable)
        self.assertEqual(runnable[0]["adapter"], "unittest")
        self.assertEqual(runnable[0]["evidence_strength"], "strong")
