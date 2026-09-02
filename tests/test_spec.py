"""Field records, provenance, and serialisation."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from support import RepoCase  # noqa: E402
from toucan import spec as spec_mod, store  # noqa: E402
from toucan.errors import Refusal  # noqa: E402


class SpecModelTest(RepoCase):
    def test_round_trips_without_field_loss(self):
        document = self.complete_draft()
        reloaded = store.load_draft(self.repo, "demo")
        self.assertEqual(document["fields"], reloaded["fields"])
        self.assertEqual(document["intent"], reloaded["intent"])
        self.assertEqual(
            json.loads(json.dumps(document, sort_keys=True)),
            json.loads(json.dumps(reloaded, sort_keys=True)),
        )

    def test_intent_is_stored_verbatim(self):
        text = "fix the auth refresh bug, don't touch the tests"
        document = spec_mod.new_spec("s", text)
        self.assertTrue(document["intent"]["supplied"])
        self.assertEqual(document["intent"]["text"], text)

    def test_absent_intent_is_recorded_as_absent(self):
        document = spec_mod.new_spec("s", None)
        self.assertFalse(document["intent"]["supplied"])
        self.assertIsNone(document["intent"]["text"])

    def test_unknown_provenance_is_rejected(self):
        with self.assertRaises(Refusal):
            spec_mod.field("x", "probably")

    def test_inferred_field_cannot_cite_evidence(self):
        with self.assertRaises(Refusal):
            spec_mod.field("x", spec_mod.INFERRED, "pytest.ini")

    def test_unratified_lists_only_inferred_fields(self):
        document = spec_mod.new_spec("s", "t")
        spec_mod.set_field(document, "criterion", "c", spec_mod.INFERRED)
        spec_mod.set_field(document, "required_runs", 1, spec_mod.DETECTED, "x")
        self.assertEqual(spec_mod.unratified(document), ["criterion"])

    def test_ratifying_reclasses_to_yours(self):
        document = spec_mod.new_spec("s", "t")
        spec_mod.set_field(document, "criterion", "c", spec_mod.INFERRED)
        spec_mod.ratify(document, "criterion", "chosen")
        self.assertEqual(spec_mod.provenance_of(document, "criterion"),
                         spec_mod.YOURS)
        self.assertEqual(spec_mod.unratified(document), [])

    def test_ratifying_unknown_field_is_refused(self):
        document = spec_mod.new_spec("s", "t")
        with self.assertRaises(Refusal):
            spec_mod.ratify(document, "nonexistent", "x")
