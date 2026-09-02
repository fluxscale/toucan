"""Freezing: hashing, ordering refusals, immutability, tamper detection."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from support import RepoCase  # noqa: E402
from toucan import baseline as baseline_mod, spec as spec_mod, store  # noqa: E402
from toucan.canonical import content_hash  # noqa: E402
from toucan.errors import Refusal, Tampered  # noqa: E402

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_runner.py")


class FreezeTest(RepoCase):
    def fake_oracle(self, failing=2):
        return {
            "argv": [sys.executable, FAKE, "--fail", str(failing)],
            "cwd": ".",
            "timeout_seconds": 60,
            "adapter": "pytest",
            "execution_evidence": "JUnit XML report listing each test case.",
        }

    def prepared(self, slice_id="demo"):
        document = self.complete_draft(slice_id)
        spec_mod.set_field(document, "oracle", self.fake_oracle(),
                           spec_mod.DETECTED, "pytest.ini")
        document["baseline"] = baseline_mod.capture(self.repo,
                                                    self.fake_oracle())
        store.save_draft(self.repo, document)
        return document

    def test_freeze_is_refused_without_a_baseline(self):
        self.complete_draft()
        with self.assertRaises(Refusal) as caught:
            store.freeze(self.repo, "demo", "abc123")
        self.assertIn("no baseline", str(caught.exception))

    def test_freeze_is_refused_while_a_field_is_unratified(self):
        document = self.prepared()
        document["fields"]["criterion"] = spec_mod.field("c", spec_mod.INFERRED)
        store.save_draft(self.repo, document)
        with self.assertRaises(Refusal) as caught:
            store.freeze(self.repo, "demo", "abc123")
        self.assertIn("inferred", str(caught.exception))

    def test_freeze_is_refused_when_a_required_field_is_missing(self):
        document = self.prepared()
        del document["fields"]["required_runs"]
        store.save_draft(self.repo, document)
        with self.assertRaises(Refusal):
            store.freeze(self.repo, "demo", "abc123")

    def test_freeze_records_hash_timestamp_and_base_sha(self):
        self.prepared()
        frozen = store.freeze(self.repo, "demo", "abc123")
        self.assertEqual(frozen["frozen"]["version"], 1)
        self.assertEqual(len(frozen["frozen"]["content_hash"]), 64)
        self.assertTrue(frozen["frozen"]["frozen_at"])
        self.assertEqual(frozen["frozen"]["base_sha"], "abc123")

    def test_freeze_removes_the_draft(self):
        self.prepared()
        store.freeze(self.repo, "demo", "abc123")
        self.assertFalse(os.path.exists(store.draft_path(self.repo, "demo")))

    def test_hash_changes_when_any_field_changes(self):
        self.prepared()
        frozen = store.freeze(self.repo, "demo", "abc123")
        original = frozen["frozen"]["content_hash"]
        altered = json.loads(json.dumps(frozen))
        altered["fields"]["criterion"]["value"] = "something weaker"
        self.assertNotEqual(original,
                            content_hash(spec_mod.hashable_view(altered)))

    def test_hash_covers_the_intent_text(self):
        self.prepared()
        frozen = store.freeze(self.repo, "demo", "abc123")
        altered = json.loads(json.dumps(frozen))
        altered["intent"]["text"] = "a different request entirely"
        self.assertNotEqual(frozen["frozen"]["content_hash"],
                            content_hash(spec_mod.hashable_view(altered)))

    def test_tampered_frozen_specification_fails_to_load(self):
        self.prepared()
        store.freeze(self.repo, "demo", "abc123")
        path = store.version_path(self.repo, "demo", 1)
        with open(path) as handle:
            document = json.load(handle)
        document["fields"]["criterion"]["value"] = "weakened after freezing"
        with open(path, "w") as handle:
            json.dump(document, handle)
        with self.assertRaises(Tampered):
            store.load_frozen(self.repo, "demo")

    def test_frozen_specification_refuses_in_place_edit(self):
        self.prepared()
        frozen = store.freeze(self.repo, "demo", "abc123")
        with self.assertRaises(Refusal):
            spec_mod.set_field(frozen, "criterion", "x", spec_mod.YOURS, "e")

    def test_freeze_writes_a_ledger_entry(self):
        self.prepared()
        store.freeze(self.repo, "demo", "abc123")
        from toucan import ledger as ledger_mod
        entries = ledger_mod.read(store.ledger_path(self.repo, "demo"))
        self.assertEqual(entries[0]["entry"]["event"], "frozen")
