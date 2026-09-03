"""The bounded loop: ledger-derived state, stall, budget, and closure."""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from support import RepoCase  # noqa: E402
from toucan import baseline as baseline_mod, loop as loop_mod  # noqa: E402
from toucan import spec as spec_mod, store  # noqa: E402

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_runner.py")
TOUCAN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "toucan"
)


class LoopCase(RepoCase):
    def cli(self, *args, expect=0):
        result = subprocess.run(
            [sys.executable, TOUCAN, "--repo", self.repo] + list(args),
            capture_output=True, text=True,
        )
        self.assertEqual(
            result.returncode, expect,
            "exit %d\nstdout: %s\nstderr: %s"
            % (result.returncode, result.stdout, result.stderr),
        )
        payload = result.stdout or result.stderr
        return json.loads(payload) if payload.strip() else {}

    def frozen_slice(self, slice_id="loop", iteration_maximum=3, stall=None):
        document = self.complete_draft(slice_id)
        oracle = {
            "argv": [sys.executable, FAKE, "--fail", "2"],
            "cwd": ".", "timeout_seconds": 60, "adapter": "pytest",
            "execution_evidence": "JUnit XML report.",
        }
        spec_mod.set_field(document, "oracle", oracle, spec_mod.DETECTED, "x")
        spec_mod.set_field(document, "iteration_maximum", iteration_maximum,
                           spec_mod.YOURS, "chosen")
        if stall is not None:
            spec_mod.set_field(document, "stall", stall, spec_mod.YOURS, "chosen")
        document["baseline"] = baseline_mod.capture(self.repo, oracle)
        store.save_draft(self.repo, document)
        store.freeze(self.repo, slice_id, "abc123")
        return slice_id

    def start(self, sid, expect=0):
        return self.cli("attempt", "start", "--slice-id", sid, expect=expect)

    def verdict(self, sid, verdict, failed=None, expect=0, **extra):
        args = ["verdict", "record", "--slice-id", sid, "--verdict", verdict]
        if failed is not None:
            args += ["--measurements", json.dumps({"failed": failed})]
        for key, value in extra.items():
            args += ["--%s" % key, value]
        return self.cli(*args, expect=expect)


class OrderingTest(LoopCase):
    def test_verdict_without_a_started_attempt_is_refused(self):
        sid = self.frozen_slice()
        report = self.verdict(sid, "FAIL", failed=2, expect=2)
        self.assertIn("no attempt is awaiting", report["message"])

    def test_second_attempt_refused_while_verdict_pending(self):
        sid = self.frozen_slice()
        self.start(sid)
        report = self.start(sid, expect=2)
        self.assertIn("no recorded verdict", report["message"])

    def test_duplicate_verdict_is_refused(self):
        sid = self.frozen_slice()
        self.start(sid)
        self.verdict(sid, "FAIL", failed=2)
        report = self.verdict(sid, "FAIL", failed=2, expect=2)
        self.assertIn("no attempt is awaiting", report["message"])

    def test_prior_observations_reach_the_next_attempt(self):
        sid = self.frozen_slice()
        self.start(sid)
        self.verdict(sid, "FAIL", failed=2,
                     observation="cache not invalidated",
                     eliminates="the TTL hypothesis")
        started = self.start(sid)
        self.assertEqual(started["prior_observations"][0]["eliminates"],
                         "the TTL hypothesis")


class BudgetTest(LoopCase):
    def test_budget_exhausts_on_fail_verdicts(self):
        sid = self.frozen_slice(iteration_maximum=2)
        for failed in (2, 1):
            self.start(sid)
            self.verdict(sid, "FAIL", failed=failed)
        report = self.start(sid, expect=2)
        self.assertIn("budget exhausted", report["message"])

    def test_blocked_consumes_no_budget(self):
        sid = self.frozen_slice(iteration_maximum=1)
        self.start(sid)
        recorded = self.verdict(sid, "BLOCKED")
        self.assertEqual(recorded["consumed_iterations"], 0)
        self.start(sid)  # still allowed

    def test_pass_ends_the_loop(self):
        sid = self.frozen_slice()
        self.start(sid)
        self.verdict(sid, "PASS", failed=0)
        report = self.start(sid, expect=2)
        self.assertIn("PASS", report["message"])


class StallTest(LoopCase):
    def run_fails(self, sid, series):
        for failed in series:
            self.start(sid)
            self.verdict(sid, "FAIL", failed=failed)

    def test_plateau_fires_stall(self):
        sid = self.frozen_slice(iteration_maximum=10)
        self.run_fails(sid, [2, 2, 2])
        check = self.cli("stall", "check", "--slice-id", sid, expect=2)
        self.assertTrue(check["stalled"])
        report = self.start(sid, expect=2)
        self.assertIn("stalled", report["message"])

    def test_improvement_resets_the_window(self):
        sid = self.frozen_slice(iteration_maximum=10)
        self.run_fails(sid, [3, 3, 2])
        check = self.cli("stall", "check", "--slice-id", sid)
        self.assertFalse(check["stalled"])

    def test_declared_window_is_honoured(self):
        sid = self.frozen_slice(iteration_maximum=10,
                                stall={"window": 2})
        self.run_fails(sid, [2, 2])
        check = self.cli("stall", "check", "--slice-id", sid, expect=2)
        self.assertTrue(check["stalled"])
        self.assertTrue(check["rule"]["declared"])

    def test_epsilon_absorbs_noise(self):
        sid = self.frozen_slice(iteration_maximum=10,
                                stall={"metric": "failed", "epsilon": 1})
        self.run_fails(sid, [5, 4, 4])
        check = self.cli("stall", "check", "--slice-id", sid, expect=2)
        self.assertTrue(check["stalled"], check)

    def test_without_epsilon_the_same_series_is_not_stalled(self):
        sid = self.frozen_slice(iteration_maximum=10)
        self.run_fails(sid, [5, 4, 4])
        check = self.cli("stall", "check", "--slice-id", sid)
        self.assertFalse(check["stalled"], check)

    def test_unmeasurable_window_is_stalled(self):
        sid = self.frozen_slice(iteration_maximum=10)
        for _ in range(3):
            self.start(sid)
            self.verdict(sid, "FAIL")  # no measurements at all
        check = self.cli("stall", "check", "--slice-id", sid, expect=2)
        self.assertTrue(check["stalled"])

    def test_stalling_changes_no_verdict(self):
        sid = self.frozen_slice(iteration_maximum=10)
        self.run_fails(sid, [2, 2, 2])
        state = loop_mod.replay(store.ledger_path(self.repo, sid))
        self.assertEqual(state["last_verdict"], "FAIL")


class ClosureTest(LoopCase):
    def test_full_loop_to_pass(self):
        sid = self.frozen_slice()
        self.start(sid)
        self.verdict(sid, "FAIL", failed=2)
        self.start(sid)
        self.verdict(sid, "PASS", failed=0)
        closed = self.cli("slice", "close", "--slice-id", sid,
                          "--outcome", "passed")
        self.assertTrue(closed["closed"])
        status = self.cli("status")
        self.assertEqual(status["slices"][0]["state"], "passed")
        self.assertFalse(status["has_live_slice"])

    def test_cannot_close_passed_without_a_pass_verdict(self):
        sid = self.frozen_slice()
        self.start(sid)
        self.verdict(sid, "FAIL", failed=2)
        report = self.cli("slice", "close", "--slice-id", sid,
                          "--outcome", "passed", expect=2)
        self.assertIn("not PASS", report["message"])

    def test_exhausted_is_never_passed(self):
        sid = self.frozen_slice(iteration_maximum=1)
        self.start(sid)
        self.verdict(sid, "FAIL", failed=2)
        self.cli("slice", "close", "--slice-id", sid, "--outcome", "exhausted",
                 "--reason", "budget")
        status = self.cli("status")
        self.assertEqual(status["slices"][0]["state"], "exhausted")

    def test_closed_slice_refuses_attempts_and_verdicts(self):
        sid = self.frozen_slice()
        self.start(sid)
        self.verdict(sid, "FAIL", failed=2)
        self.cli("slice", "close", "--slice-id", sid, "--outcome", "abandoned")
        self.start(sid, expect=2)
        self.verdict(sid, "FAIL", failed=1, expect=2)

    def test_ledger_stays_intact_through_a_full_loop(self):
        sid = self.frozen_slice()
        self.start(sid)
        self.verdict(sid, "FAIL", failed=2)
        self.start(sid)
        self.verdict(sid, "PASS", failed=0)
        self.cli("slice", "close", "--slice-id", sid, "--outcome", "passed")
        verify = self.cli("ledger", "verify", "--slice-id", sid)
        self.assertTrue(verify["intact"])
        self.assertEqual(verify["entries"], 6)  # freeze + 2x(start+verdict) + close
