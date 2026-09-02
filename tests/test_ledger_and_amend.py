"""Hash-chained ledger, amendment versioning, and attempt ordering."""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from support import RepoCase  # noqa: E402
from toucan import baseline as baseline_mod, ledger as ledger_mod  # noqa: E402
from toucan import spec as spec_mod, store  # noqa: E402
from toucan.errors import Refusal, Tampered  # noqa: E402

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_runner.py")
TOUCAN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "toucan"
)


class LedgerTest(RepoCase):
    def path(self):
        return store.ledger_path(self.repo, "demo")

    def test_appends_form_a_chain(self):
        ledger_mod.append(self.path(), {"event": "one"})
        ledger_mod.append(self.path(), {"event": "two"})
        entries = ledger_mod.read(self.path())
        self.assertEqual(entries[1]["prev_hash"], entries[0]["hash"])
        self.assertEqual(ledger_mod.verify(self.path()), 2)

    def test_modified_entry_breaks_verification(self):
        ledger_mod.append(self.path(), {"event": "one"})
        ledger_mod.append(self.path(), {"event": "two"})
        entries = ledger_mod.read(self.path())
        entries[0]["entry"]["event"] = "rewritten"
        with open(self.path(), "w") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
        with self.assertRaises(Tampered) as caught:
            ledger_mod.verify(self.path())
        self.assertIn("modified", str(caught.exception))

    def test_removed_entry_breaks_verification(self):
        for index in range(3):
            ledger_mod.append(self.path(), {"event": index})
        entries = ledger_mod.read(self.path())
        del entries[1]
        with open(self.path(), "w") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
        with self.assertRaises(Tampered):
            ledger_mod.verify(self.path())

    def test_empty_ledger_verifies(self):
        self.assertEqual(ledger_mod.verify(self.path()), 0)


class AmendTest(RepoCase):
    def fake_oracle(self):
        return {
            "argv": [sys.executable, FAKE, "--fail", "2"],
            "cwd": ".",
            "timeout_seconds": 60,
            "adapter": "pytest",
            "execution_evidence": "JUnit XML report listing each test case.",
        }

    def frozen(self):
        document = self.complete_draft()
        spec_mod.set_field(document, "oracle", self.fake_oracle(),
                           spec_mod.DETECTED, "pytest.ini")
        document["baseline"] = baseline_mod.capture(self.repo, self.fake_oracle())
        store.save_draft(self.repo, document)
        return store.freeze(self.repo, "demo", "abc123")

    def test_amendment_creates_a_new_version(self):
        self.frozen()
        amended = store.amend(
            self.repo, "demo",
            {"criterion": spec_mod.field("narrower", spec_mod.YOURS, "chosen")},
            "the original criterion covered an unrelated module", 2,
        )
        self.assertEqual(amended["frozen"]["version"], 2)
        self.assertEqual(amended["frozen"]["previous_version"], 1)

    def test_amendment_never_mutates_the_prior_version(self):
        original = self.frozen()
        original_hash = original["frozen"]["content_hash"]
        store.amend(self.repo, "demo",
                    {"criterion": spec_mod.field("narrower", spec_mod.YOURS, "c")},
                    "justified", 2)
        reloaded = store.load_frozen(self.repo, "demo", 1)
        self.assertEqual(reloaded["frozen"]["content_hash"], original_hash)
        self.assertEqual(reloaded["fields"]["criterion"]["value"],
                         "all tests pass with no skips")

    def test_amendment_records_the_difference_and_the_iteration(self):
        self.frozen()
        amended = store.amend(
            self.repo, "demo",
            {"criterion": spec_mod.field("narrower", spec_mod.YOURS, "c")},
            "scope was wrong", 3,
        )
        amendment = amended["frozen"]["amendment"]
        self.assertEqual(amendment["justification"], "scope was wrong")
        self.assertEqual(amended["frozen"]["iteration"], 3)
        changed = [c["field"] for c in amendment["changes"]]
        self.assertIn("criterion", changed)

    def test_amendment_without_justification_is_refused(self):
        self.frozen()
        with self.assertRaises(Refusal):
            store.amend(self.repo, "demo",
                        {"criterion": spec_mod.field("x", spec_mod.YOURS, "c")},
                        "   ", 2)

    def test_required_runs_escalates_after_a_recorded_failure(self):
        self.frozen()
        ledger_mod.append(store.ledger_path(self.repo, "demo"),
                          {"event": "verdict", "verdict": "FAIL", "iteration": 1})
        amended = store.amend(
            self.repo, "demo",
            {"criterion": spec_mod.field("narrower", spec_mod.YOURS, "c")},
            "criterion was too broad", 2,
        )
        self.assertGreaterEqual(spec_mod.get(amended, "required_runs"), 2)

    def test_required_runs_stays_at_one_without_a_recorded_failure(self):
        self.frozen()
        amended = store.amend(
            self.repo, "demo",
            {"criterion": spec_mod.field("narrower", spec_mod.YOURS, "c")},
            "clarified", 1,
        )
        self.assertEqual(spec_mod.get(amended, "required_runs"), 1)


class AttemptOrderingTest(RepoCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, TOUCAN, "--repo", self.repo] + list(args),
            capture_output=True, text=True,
        )

    def test_attempt_cannot_start_without_a_frozen_specification(self):
        self.complete_draft()
        result = self.run_cli("attempt", "start", "--slice-id", "demo")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no frozen specification", result.stderr)

    def test_spec_check_exits_non_zero_when_insufficient(self):
        self.complete_draft()
        result = self.run_cli("spec", "check", "--slice-id", "demo")
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertIn("baseline", report["missing"])

    def test_doctor_reports_the_interpreter(self):
        result = self.run_cli("doctor")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(json.loads(result.stdout)["ok"])
