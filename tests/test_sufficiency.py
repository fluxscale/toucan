"""The predicate shared by registration and the critic."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from support import RepoCase  # noqa: E402
from toucan import spec as spec_mod  # noqa: E402
from toucan.sufficiency import evaluate  # noqa: E402


class SufficiencyTest(RepoCase):
    def _with_baseline(self):
        document = self.complete_draft()
        document["baseline"] = {"measurements": {"failed": 2}}
        return document

    def test_accepts_a_fully_populated_specification(self):
        report = evaluate(self._with_baseline())
        self.assertTrue(report["sufficient"], report)
        self.assertTrue(report["ready_to_freeze"], report)

    def test_rejects_each_required_field_when_missing(self):
        for name in spec_mod.REQUIRED_FIELDS:
            with self.subTest(field=name):
                document = self._with_baseline()
                del document["fields"][name]
                report = evaluate(document)
                self.assertFalse(report["sufficient"])
                self.assertIn(name, report["missing"])

    def test_rejects_missing_baseline(self):
        document = self.complete_draft()
        report = evaluate(document)
        self.assertFalse(report["sufficient"])
        self.assertIn("baseline", report["missing"])

    def test_rejects_empty_criterion(self):
        document = self._with_baseline()
        document["fields"]["criterion"]["value"] = "   "
        report = evaluate(document)
        self.assertFalse(report["sufficient"])

    def test_rejects_shell_construct_in_argv(self):
        document = self._with_baseline()
        document["fields"]["oracle"]["value"]["argv"] = ["pytest -q | tee log"]
        report = evaluate(document)
        self.assertFalse(report["sufficient"])
        self.assertTrue(any("shell" in a for a in report["ambiguous"]), report)

    def test_rejects_zero_required_runs(self):
        document = self._with_baseline()
        document["fields"]["required_runs"]["value"] = 0
        self.assertFalse(evaluate(document)["sufficient"])

    def test_rejects_non_boolean_skip_policy(self):
        document = self._with_baseline()
        document["fields"]["allow_skips"]["value"] = "maybe"
        self.assertFalse(evaluate(document)["sufficient"])

    def test_sufficient_but_unratified_is_not_ready_to_freeze(self):
        document = self._with_baseline()
        document["fields"]["criterion"] = spec_mod.field("c", spec_mod.INFERRED)
        report = evaluate(document)
        self.assertTrue(report["sufficient"])
        self.assertFalse(report["ready_to_freeze"])
        self.assertEqual(report["unratified"], ["criterion"])
