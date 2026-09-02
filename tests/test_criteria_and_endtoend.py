"""The strictness ladder, and a full registration walkthrough via the CLI."""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from support import RepoCase  # noqa: E402
from toucan import baseline as baseline_mod, criteria  # noqa: E402

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_runner.py")
TOUCAN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "toucan"
)


class LadderTest(RepoCase):
    def ladder(self, failing=2, passing=2):
        oracle = {
            "argv": [sys.executable, FAKE, "--fail", str(failing),
                     "--pass", str(passing)],
            "cwd": ".",
            "timeout_seconds": 60,
            "adapter": "pytest",
            "execution_evidence": "JUnit XML report.",
        }
        return criteria.ladder(baseline_mod.capture(self.repo, oracle))

    def test_every_slot_is_always_present(self):
        candidates = self.ladder()
        self.assertEqual([c["slot"] for c in candidates], list(criteria.SLOTS))

    def test_slots_are_ordered_from_least_to_most_strict(self):
        candidates = self.ladder()
        runs = [c["required_runs"] for c in candidates]
        self.assertEqual(runs, sorted(runs))
        self.assertEqual(candidates[-1]["slot"], criteria.HARDENED)

    def test_narrow_candidate_names_the_failing_targets(self):
        candidates = self.ladder()
        self.assertIn("test_broken", candidates[0]["criterion"])

    def test_every_candidate_states_what_it_gives_up(self):
        for candidate in self.ladder():
            with self.subTest(slot=candidate["slot"]):
                self.assertTrue(candidate["gives_up"].strip())
                self.assertTrue(candidate["cost"].strip())

    def test_hardened_slot_requires_repeated_runs(self):
        candidates = {c["slot"]: c for c in self.ladder()}
        self.assertGreaterEqual(candidates[criteria.HARDENED]["required_runs"], 2)

    def test_no_candidate_permits_skips(self):
        self.assertTrue(all(c["allow_skips"] is False for c in self.ladder()))


class EndToEndTest(RepoCase):
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

    def test_full_registration_walkthrough(self):
        intent = "fix the broken sample tests, don't touch the tests directory"
        oracle = {
            "argv": [sys.executable, FAKE, "--fail", "2"],
            "cwd": ".",
            "timeout_seconds": 60,
            "adapter": "pytest",
            "execution_evidence": "JUnit XML report listing each test case.",
        }

        created = self.cli("spec", "init", "--slice-id", "s1", "--intent", intent)
        self.assertTrue(created["created"])
        self.assertEqual(created["intent"]["text"], intent)

        self.cli("spec", "set", "--slice-id", "s1", "--field", "oracle",
                 "--value", json.dumps(oracle), "--provenance", "detected",
                 "--evidence", "pytest.ini")
        self.cli("spec", "set", "--slice-id", "s1", "--field", "protected_paths",
                 "--value", json.dumps(["tests/**"]), "--provenance", "yours",
                 "--evidence", "don't touch the tests directory")
        self.cli("spec", "set", "--slice-id", "s1", "--field",
                 "approved_oracle_changes", "--value", "[]",
                 "--provenance", "yours", "--evidence", "none requested")

        # A criterion the model authored: inferred, and blocking.
        self.cli("spec", "set", "--slice-id", "s1", "--field", "criterion",
                 "--value", "the failing tests pass", "--provenance", "inferred")

        baseline = self.cli("baseline", "--slice-id", "s1")
        self.assertTrue(baseline["captured"])
        self.assertEqual(baseline["baseline"]["measurements"]["source"], "runner")
        self.assertEqual(baseline["baseline"]["measurements"]["failed"], 2)

        ladder = self.cli("criteria", "--slice-id", "s1")
        self.assertEqual(len(ladder["candidates"]), 4)
        chosen = ladder["candidates"][2]

        # Freezing is refused while the criterion is still the model's.
        self.cli("freeze", "--slice-id", "s1", expect=2)

        self.cli("spec", "ratify", "--slice-id", "s1", "--field", "criterion",
                 "--value", chosen["criterion"])
        self.cli("spec", "set", "--slice-id", "s1", "--field", "required_runs",
                 "--value", str(chosen["required_runs"]), "--provenance", "yours",
                 "--evidence", "implied by the ratified criterion")
        self.cli("spec", "set", "--slice-id", "s1", "--field", "allow_skips",
                 "--value", "false", "--provenance", "yours",
                 "--evidence", "implied by the ratified criterion")
        self.cli("spec", "set", "--slice-id", "s1", "--field",
                 "iteration_maximum", "--value", "5", "--provenance", "yours",
                 "--evidence", "chosen")

        report = self.cli("spec", "check", "--slice-id", "s1")
        self.assertTrue(report["sufficient"], report)
        self.assertTrue(report["ready_to_freeze"], report)

        frozen = self.cli("freeze", "--slice-id", "s1")
        self.assertTrue(frozen["frozen"])
        self.assertEqual(len(frozen["content_hash"]), 64)

        started = self.cli("attempt", "start", "--slice-id", "s1")
        self.assertEqual(started["iteration"], 1)

        status = self.cli("status")
        self.assertTrue(status["has_live_slice"])

        self.assertTrue(self.cli("ledger", "verify", "--slice-id", "s1")["intact"])

        shown = self.cli("spec", "show", "--slice-id", "s1")
        self.assertEqual(shown["intent"]["text"], intent)

    def test_registration_refuses_a_green_baseline(self):
        oracle = {
            "argv": [sys.executable, FAKE, "--fail", "0"],
            "cwd": ".", "timeout_seconds": 60, "adapter": "pytest",
            "execution_evidence": "JUnit XML report.",
        }
        self.cli("spec", "init", "--slice-id", "g", "--no-intent")
        self.cli("spec", "set", "--slice-id", "g", "--field", "oracle",
                 "--value", json.dumps(oracle), "--provenance", "detected",
                 "--evidence", "pytest.ini")
        self.cli("baseline", "--slice-id", "g", expect=2)

    def test_init_requires_an_explicit_intent_decision(self):
        self.cli("spec", "init", "--slice-id", "x", expect=2)


class CriticContractTest(EndToEndTest):
    """A specification registration accepted must not be INVALID-SPEC later.

    Registration and the critic share one predicate, so a frozen specification
    passing `spec check` is the structural guarantee the critic relies on.
    """

    def test_frozen_specification_satisfies_the_critics_check(self):
        self.test_full_registration_walkthrough()
        report = self.cli("spec", "check", "--slice-id", "s1")
        self.assertTrue(report["sufficient"], report)
        self.assertTrue(report["frozen"])
        self.assertEqual(report["missing"], [])
        self.assertEqual(report["ambiguous"], [])

    def test_check_reads_the_frozen_version_not_a_draft(self):
        self.test_full_registration_walkthrough()
        shown = self.cli("spec", "show", "--slice-id", "s1")
        self.assertIsNotNone(shown["frozen"])
        self.assertEqual(shown["frozen"]["version"], 1)
