"""The judge instrument: reference gate, pairwise protocol, ingest/executed.

Written before the implementation existed: this file is the red baseline of
the slice that gated the judge instrument's own development.
"""

import hashlib
import json
import os
import stat
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from support import RepoCase  # noqa: E402
from toucan import artifacts, judge, reference, rubric  # noqa: E402
from toucan import spec as spec_mod, store  # noqa: E402
from toucan.errors import Refusal, Tampered  # noqa: E402
from toucan.sufficiency import evaluate  # noqa: E402

TOUCAN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "toucan"
)

DIMENSIONS = ["clarity", "completeness", "tone"]


def _write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


class JudgeCase(RepoCase):
    def setUp(self):
        super().setUp()
        self.reference_path = _write(
            os.path.join(self.repo, "reference.md"), "# The bar\n\nGood prose.\n"
        )
        self.candidate_path = _write(
            os.path.join(self.repo, "candidate.md"), "# Ours\n\nOur prose.\n"
        )

    def registered_reference(self, slice_id="judged"):
        return reference.register(
            self.repo, slice_id, self.reference_path, name="the bar"
        )

    def rubric_value(self, slot="unanimous", runs_required=3):
        chosen = [c for c in rubric.ladder(DIMENSIONS) if c["slot"] == slot][0]
        return {
            "dimensions": DIMENSIONS,
            "slot": chosen["slot"],
            "dims_required": chosen["dims_required"],
            "runs_required": max(chosen["runs_required"], runs_required),
        }

    def prepared(self, slice_id="judged", slot="unanimous"):
        ref = self.registered_reference(slice_id)
        document = spec_mod.new_spec(slice_id, "beat the bar")
        spec_mod.set_field(document, "reference", ref, spec_mod.YOURS, "supplied")
        spec_mod.set_field(document, "rubric", self.rubric_value(slot),
                           spec_mod.YOURS, "ratified")
        store.save_draft(self.repo, document)
        manifest = judge.prepare(self.repo, slice_id, self.candidate_path)
        return document, manifest

    def results_for(self, manifest, winner="candidate", dissent_run=None,
                    model="test-model"):
        """Blind results where `winner` takes every dimension, translated
        through each run's recorded order -- except `dissent_run`, where the
        other artifact wins everything."""
        runs = []
        for entry in manifest["runs"]:
            actual = winner
            if dissent_run is not None and entry["run"] == dissent_run:
                actual = "reference" if winner == "candidate" else "candidate"
            label = [k for k, v in entry["order"].items() if v == actual][0]
            runs.append({
                "run": entry["run"],
                "winners": {dim: label for dim in DIMENSIONS},
            })
        return {"judging_id": manifest["judging_id"], "model": model,
                "runs": runs}


class ArtifactStoreTest(JudgeCase):
    def test_storage_is_content_addressed(self):
        record = artifacts.store_artifact(self.repo, "judged", self.candidate_path)
        digest = hashlib.sha256(
            open(self.candidate_path, "rb").read()
        ).hexdigest()
        self.assertEqual(record["sha256"], digest)
        self.assertTrue(os.path.exists(record["stored_path"]))
        with open(record["stored_path"], "rb") as handle:
            self.assertEqual(
                hashlib.sha256(handle.read()).hexdigest(), digest
            )


class ReferenceGateTest(JudgeCase):
    def test_reference_is_fetched_and_hashed_at_registration(self):
        ref = self.registered_reference()
        digest = hashlib.sha256(
            open(self.reference_path, "rb").read()
        ).hexdigest()
        self.assertEqual(ref["content_hash"], digest)
        self.assertEqual(ref["name"], "the bar")
        self.assertTrue(ref["fetched_at"])

    def test_unfetchable_reference_is_refused(self):
        with self.assertRaises(Refusal):
            reference.register(self.repo, "judged",
                               os.path.join(self.repo, "missing.md"),
                               name="ghost")

    def test_moved_bar_is_refused_at_prepare(self):
        document, _ = self.prepared()
        ref = spec_mod.get(document, "reference")
        stored = os.path.join(self.repo, ref["artifact_path"])
        os.chmod(stored, stat.S_IWUSR | stat.S_IRUSR)
        _write(stored, "# A different bar entirely\n")
        with self.assertRaises(Tampered):
            judge.prepare(self.repo, "judged", self.candidate_path)


class RubricLadderTest(JudgeCase):
    def test_every_slot_is_always_present(self):
        candidates = rubric.ladder(DIMENSIONS)
        self.assertEqual([c["slot"] for c in candidates],
                         ["majority", "strong", "unanimous", "exacting"])

    def test_severity_is_monotonic(self):
        candidates = rubric.ladder(DIMENSIONS)
        dims = [c["dims_required"] for c in candidates]
        runs = [c["runs_required"] for c in candidates]
        self.assertEqual(dims, sorted(dims))
        self.assertEqual(runs, sorted(runs))
        self.assertEqual(dims[-1], len(DIMENSIONS))

    def test_no_slot_permits_fewer_than_three_runs(self):
        for candidate in rubric.ladder(DIMENSIONS):
            self.assertGreaterEqual(candidate["runs_required"], 3)


class PrepareTest(JudgeCase):
    def test_at_least_three_runs_are_prepared(self):
        _, manifest = self.prepared()
        self.assertGreaterEqual(len(manifest["runs"]), 3)

    def test_orders_are_recorded_per_run(self):
        _, manifest = self.prepared()
        for entry in manifest["runs"]:
            self.assertEqual(set(entry["order"].keys()), {"A", "B"})
            self.assertEqual(set(entry["order"].values()),
                             {"candidate", "reference"})

    def test_packets_carry_no_labels(self):
        _, manifest = self.prepared()
        for entry in manifest["runs"]:
            with open(os.path.join(self.repo, entry["packet_path"])) as handle:
                packet = handle.read()
            self.assertNotIn("candidate", packet)
            self.assertNotIn("reference", packet)

    def test_packets_carry_the_rubric_dimensions_only(self):
        _, manifest = self.prepared()
        entry = manifest["runs"][0]
        with open(os.path.join(self.repo, entry["packet_path"])) as handle:
            packet = json.load(handle)
        self.assertEqual(packet["dimensions"], DIMENSIONS)
        self.assertNotIn("intent", packet)
        self.assertNotIn("criterion", packet)


class IngestTest(JudgeCase):
    def test_unblinded_measurements_from_ingest(self):
        _, manifest = self.prepared()
        measurements = judge.ingest(self.repo, "judged",
                                    self.results_for(manifest))
        self.assertEqual(measurements["source"], "judge-ingested")
        self.assertTrue(measurements["criterion_met"])
        self.assertEqual(len(measurements["runs"]),
                         len(manifest["runs"]))
        for run in measurements["runs"]:
            self.assertEqual(run["dims_won"], len(DIMENSIONS))

    def test_one_dissenting_run_fails_the_criterion(self):
        _, manifest = self.prepared()
        measurements = judge.ingest(
            self.repo, "judged", self.results_for(manifest, dissent_run=2)
        )
        self.assertFalse(measurements["criterion_met"])
        outcomes = [run["criterion_met"] for run in measurements["runs"]]
        self.assertEqual(outcomes.count(False), 1)
        self.assertEqual(len(outcomes), len(manifest["runs"]))

    def test_a_tie_is_not_a_win(self):
        _, manifest = self.prepared()
        results = self.results_for(manifest)
        results["runs"][0]["winners"][DIMENSIONS[0]] = "tie"
        measurements = judge.ingest(self.repo, "judged", results)
        self.assertFalse(measurements["criterion_met"])

    def test_missing_run_is_refused(self):
        _, manifest = self.prepared()
        results = self.results_for(manifest)
        results["runs"] = results["runs"][:-1]
        with self.assertRaises(Refusal):
            judge.ingest(self.repo, "judged", results)

    def test_missing_dimension_is_refused(self):
        _, manifest = self.prepared()
        results = self.results_for(manifest)
        del results["runs"][0]["winners"][DIMENSIONS[0]]
        with self.assertRaises(Refusal):
            judge.ingest(self.repo, "judged", results)

    def test_unknown_label_is_refused(self):
        _, manifest = self.prepared()
        results = self.results_for(manifest)
        results["runs"][0]["winners"][DIMENSIONS[0]] = "ours"
        with self.assertRaises(Refusal):
            judge.ingest(self.repo, "judged", results)

    def test_ingest_records_what_was_not_verified(self):
        _, manifest = self.prepared()
        measurements = judge.ingest(self.repo, "judged",
                                    self.results_for(manifest))
        self.assertIn("model_reported", measurements)
        self.assertIn("not verified", measurements["verification_note"])


class ExecutedTest(JudgeCase):
    def stub_judge(self, pick="A"):
        script = _write(
            os.path.join(self.repo, "stub_judge.py"),
            "import json, sys\n"
            "packet = json.load(open(sys.argv[-1]))\n"
            "print(json.dumps({'winners': {d: %r for d in packet['dimensions']},"
            " 'model': 'stub-1'}))\n" % pick,
        )
        os.makedirs(os.path.join(self.repo, ".toucan"), exist_ok=True)
        _write(
            os.path.join(self.repo, ".toucan", "judge-config.json"),
            json.dumps({"judge_command": [sys.executable, script]}),
        )

    def test_executed_mode_marks_its_source(self):
        self.prepared()
        self.stub_judge()
        measurements = judge.run_executed(self.repo, "judged",
                                          self.candidate_path)
        self.assertEqual(measurements["source"], "judge-executed")
        self.assertEqual(len(measurements["runs"]), 3)

    def test_executed_without_configuration_is_refused(self):
        self.prepared()
        with self.assertRaises(Refusal) as caught:
            judge.run_executed(self.repo, "judged", self.candidate_path)
        self.assertIn("judge-config", str(caught.exception))

    def test_sources_never_collapse(self):
        _, manifest = self.prepared()
        ingested = judge.ingest(self.repo, "judged",
                                self.results_for(manifest))
        self.stub_judge()
        executed = judge.run_executed(self.repo, "judged", self.candidate_path)
        self.assertNotEqual(ingested["source"], executed["source"])


class JudgeSufficiencyTest(JudgeCase):
    def judge_draft(self, with_reference=True, with_rubric=True,
                    rubric_provenance=spec_mod.YOURS):
        document = spec_mod.new_spec("judged", "beat the bar")
        oracle = {
            "argv": ["toucan", "judge", "run", "--slice-id", "judged"],
            "cwd": ".", "timeout_seconds": 600, "adapter": "judge",
            "execution_evidence": "Judging manifest and per-run outcomes "
            "recorded by the runner.",
        }
        spec_mod.set_field(document, "oracle", oracle, spec_mod.DETECTED, "n/a")
        spec_mod.set_field(document, "criterion",
                           "candidate beats the reference per the rubric",
                           spec_mod.YOURS, "stated")
        for name, value in (
            ("protected_paths", []), ("approved_oracle_changes", []),
            ("required_runs", 3), ("allow_skips", False),
            ("iteration_maximum", 5),
        ):
            spec_mod.set_field(document, name, value, spec_mod.YOURS, "chosen")
        if with_reference:
            spec_mod.set_field(document, "reference",
                               self.registered_reference(),
                               spec_mod.YOURS, "supplied")
        if with_rubric:
            evidence = None if rubric_provenance == spec_mod.INFERRED else "r"
            spec_mod.set_field(document, "rubric", self.rubric_value(),
                               rubric_provenance, evidence)
        document["baseline"] = {"measurements": {"source": "judge-registration"}}
        return document

    def test_judge_slice_without_reference_is_insufficient(self):
        report = evaluate(self.judge_draft(with_reference=False))
        self.assertFalse(report["sufficient"])
        self.assertIn("reference", report["missing"])

    def test_judge_slice_without_rubric_is_insufficient(self):
        report = evaluate(self.judge_draft(with_rubric=False))
        self.assertFalse(report["sufficient"])
        self.assertIn("rubric", report["missing"])

    def test_complete_judge_slice_is_sufficient(self):
        report = evaluate(self.judge_draft())
        self.assertTrue(report["sufficient"], report)

    def test_inferred_rubric_blocks_freezing(self):
        report = evaluate(
            self.judge_draft(rubric_provenance=spec_mod.INFERRED)
        )
        self.assertTrue(report["sufficient"])
        self.assertIn("rubric", report["unratified"])
        self.assertFalse(report["ready_to_freeze"])

    def test_runner_oracles_do_not_require_a_reference(self):
        document = self.judge_draft()
        document["fields"]["oracle"]["value"]["adapter"] = "pytest"
        del document["fields"]["reference"]
        del document["fields"]["rubric"]
        document["baseline"] = {"measurements": {"failed": 1}}
        self.assertTrue(evaluate(document)["sufficient"])


class JudgeCliTest(JudgeCase):
    def cli(self, *args, expect=0):
        result = subprocess.run(
            [sys.executable, TOUCAN, "--repo", self.repo] + list(args),
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, expect,
                         result.stdout + result.stderr)
        payload = result.stdout or result.stderr
        return json.loads(payload) if payload.strip() else {}

    def test_rubric_ladder_via_cli(self):
        report = self.cli("rubric", "ladder", "--dimensions",
                          json.dumps(DIMENSIONS))
        self.assertEqual(len(report["candidates"]), 4)

    def test_judge_check_applies_the_registered_thresholds(self):
        _, manifest = self.prepared()
        judge.ingest(self.repo, "judged", self.results_for(manifest))
        report = self.cli("judge", "check", "--slice-id", "judged")
        self.assertTrue(report["criterion_met"])
        self.assertEqual(report["source"], "judge-ingested")
