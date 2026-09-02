"""Baseline capture: execution, measurement source, and refusals."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from support import RepoCase  # noqa: E402
from toucan import baseline as baseline_mod  # noqa: E402
from toucan.errors import Refusal  # noqa: E402
from toucan.oracle import ExecutionFailure  # noqa: E402

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_runner.py")


class BaselineTest(RepoCase):
    def fake_oracle(self, passing=2, failing=2, skipped=0, timeout=60):
        return {
            "argv": [sys.executable, FAKE, "--pass", str(passing),
                     "--fail", str(failing), "--skip", str(skipped)],
            "cwd": ".",
            "timeout_seconds": timeout,
            "adapter": "pytest",
            "execution_evidence": "JUnit XML report listing each test case.",
        }

    def test_records_counts_from_the_runners_own_report(self):
        record = baseline_mod.capture(self.repo, self.fake_oracle())
        measurements = record["measurements"]
        self.assertEqual(measurements["source"], "runner")
        self.assertEqual(measurements["collected"], 4)
        self.assertEqual(measurements["failed"], 2)
        self.assertEqual(measurements["passed"], 2)

    def test_records_the_identity_of_failing_targets(self):
        record = baseline_mod.capture(self.repo, self.fake_oracle())
        failing = record["measurements"]["failing_targets"]
        self.assertEqual(len(failing), 2)
        self.assertTrue(all("test_broken" in target for target in failing))

    def test_records_the_baseline_commit(self):
        record = baseline_mod.capture(self.repo, self.fake_oracle())
        self.assertTrue(record["base_sha"])
        self.assertEqual(len(record["base_sha"]), 40)

    def test_counts_skips_separately_from_failures(self):
        record = baseline_mod.capture(self.repo, self.fake_oracle(skipped=3))
        self.assertEqual(record["measurements"]["skipped"], 3)
        self.assertEqual(record["measurements"]["executed"], 4)

    def test_missing_command_is_an_execution_failure_not_a_baseline(self):
        oracle = self.fake_oracle()
        oracle["argv"] = ["definitely-not-a-real-command-xyz"]
        with self.assertRaises(ExecutionFailure) as caught:
            baseline_mod.capture(self.repo, oracle)
        self.assertIn("not found", caught.exception.reason)

    def test_timeout_is_an_execution_failure(self):
        oracle = self.fake_oracle(timeout=1)
        oracle["argv"] = [sys.executable, "-c", "__import__('time').sleep(30)"]
        with self.assertRaises(ExecutionFailure) as caught:
            baseline_mod.capture(self.repo, oracle)
        self.assertIn("timeout", caught.exception.reason)

    def test_shell_construct_is_refused_before_execution(self):
        oracle = self.fake_oracle()
        oracle["argv"] = ["pytest -q > /dev/null"]
        with self.assertRaises(ExecutionFailure):
            baseline_mod.capture(self.repo, oracle)

    def test_green_baseline_is_refused_as_unactionable(self):
        record = baseline_mod.capture(self.repo, self.fake_oracle(failing=0))
        with self.assertRaises(Refusal) as caught:
            baseline_mod.require_actionable(record)
        self.assertIn("already passes", str(caught.exception))

    def test_failing_baseline_is_actionable(self):
        record = baseline_mod.capture(self.repo, self.fake_oracle())
        self.assertIs(baseline_mod.require_actionable(record), record)
