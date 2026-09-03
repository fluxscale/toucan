"""The judge instrument.

The judge never decides a verdict. It produces measurements under a recorded
protocol -- blind pairwise, order randomised per run, rubric as the question
-- and a literal criterion is applied to what it produced. Two sources exist
and must never look alike: `judge-executed` (the runner invoked the judge and
captured its output) and `judge-ingested` (a harness supplied results, and the
runner verified their form, count and correspondence to the manifest -- not
their production).
"""

import json
import os
import secrets
import subprocess

from . import artifacts, spec as spec_mod, store
from .canonical import content_hash
from .errors import Refusal, Tampered
from .spec import utcnow

VALID_PICKS = ("A", "B", "tie")


def _judging_dir(repo_root, slice_id):
    return os.path.join(repo_root, ".toucan", "slices", slice_id, "judging")


def _load_spec(repo_root, slice_id):
    try:
        return store.load_frozen(repo_root, slice_id)
    except Exception:
        return store.load_draft(repo_root, slice_id)


def _require(document, name):
    value = spec_mod.get(document, name)
    if not isinstance(value, dict):
        raise Refusal(
            "slice has no %s; a judge slice registers one before judging" % name
        )
    return value


def prepare(repo_root, slice_id, candidate_path):
    """Stage a blind pairwise judging: packets, orders, manifest.

    Verifies the stored reference still matches its recorded hash first -- a
    bar that moved is a Tampered condition, not a judging input.
    """
    document = _load_spec(repo_root, slice_id)
    reference = _require(document, "reference")
    rubric = _require(document, "rubric")

    ok, detail = artifacts.verify_artifact(
        repo_root, reference["artifact_path"], reference["content_hash"]
    )
    if not ok:
        raise Tampered(
            "the reference no longer matches the hash recorded at registration "
            "(%s). The bar cannot move mid-slice; this is a finding, not an "
            "inconvenience." % detail
        )

    candidate = artifacts.store_artifact(repo_root, slice_id, candidate_path)
    runs_required = max(int(rubric.get("runs_required", 3)), 3)
    dimensions = list(rubric["dimensions"])

    judging_id = "j-" + secrets.token_hex(6)
    directory = os.path.join(_judging_dir(repo_root, slice_id), judging_id)
    os.makedirs(directory, exist_ok=True)

    runs = []
    for number in range(1, runs_required + 1):
        order = (
            {"A": "candidate", "B": "reference"}
            if secrets.choice((True, False))
            else {"A": "reference", "B": "candidate"}
        )
        by_role = {
            "candidate": candidate["artifact_path"],
            "reference": reference["artifact_path"],
        }
        packet = {
            "dimensions": dimensions,
            "question": "For each dimension, which artifact better satisfies "
            "it: A, B, or tie?",
            "artifacts": {"A": by_role[order["A"]], "B": by_role[order["B"]]},
        }
        packet_path = os.path.join(directory, "packet-run%d.json" % number)
        with open(packet_path, "w", encoding="utf-8") as handle:
            json.dump(packet, handle, indent=2)
        runs.append(
            {
                "run": number,
                "order": order,
                "packet_path": os.path.relpath(packet_path, repo_root),
            }
        )

    manifest = {
        "judging_id": judging_id,
        "slice_id": slice_id,
        "created_at": utcnow(),
        "candidate_hash": candidate["sha256"],
        "reference_hash": reference["content_hash"],
        "rubric_hash": content_hash(rubric),
        "dims_required": int(rubric["dims_required"]),
        "dims_total": len(dimensions),
        "dimensions": dimensions,
        "runs_required": runs_required,
        "runs": runs,
    }
    with open(
        os.path.join(directory, "manifest.json"), "w", encoding="utf-8"
    ) as handle:
        json.dump(manifest, handle, indent=2)
    return manifest


def _load_manifest(repo_root, slice_id, judging_id):
    path = os.path.join(
        _judging_dir(repo_root, slice_id), judging_id, "manifest.json"
    )
    if not os.path.exists(path):
        raise Refusal(
            "unknown judging id %r for slice %r" % (judging_id, slice_id)
        )
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _unblind(manifest, run_results, source, model):
    """Validate blind results against the manifest; produce measurements.

    A tie is not a win. Any run below the registered dimension threshold
    fails the whole criterion -- a mean would hide exactly the split decision
    that most needs seeing, so every run's outcome is recorded individually.
    """
    expected = {entry["run"]: entry for entry in manifest["runs"]}
    supplied = {run.get("run"): run for run in run_results or []}
    if sorted(supplied) != sorted(expected):
        raise Refusal(
            "results cover runs %s but the manifest requires runs %s; every "
            "prepared run must be judged, exactly once"
            % (sorted(k for k in supplied if k is not None), sorted(expected))
        )

    dimensions = manifest["dimensions"]
    dims_required = manifest["dims_required"]
    records = []
    for number in sorted(expected):
        entry = expected[number]
        winners = supplied[number].get("winners") or {}
        missing = [d for d in dimensions if d not in winners]
        if missing:
            raise Refusal(
                "run %d is missing a pick for dimension(s): %s"
                % (number, ", ".join(missing))
            )
        unknown = [d for d in winners if d not in dimensions]
        if unknown:
            raise Refusal(
                "run %d picks unknown dimension(s): %s"
                % (number, ", ".join(unknown))
            )
        bad = [d for d, pick in winners.items() if pick not in VALID_PICKS]
        if bad:
            raise Refusal(
                "run %d has picks outside %s for: %s"
                % (number, "/".join(VALID_PICKS), ", ".join(bad))
            )
        candidate_label = [
            label for label, role in entry["order"].items() if role == "candidate"
        ][0]
        dims_won = sum(
            1 for d in dimensions if winners[d] == candidate_label
        )
        records.append(
            {
                "run": number,
                "order": entry["order"],
                "dims_won": dims_won,
                "dims_total": len(dimensions),
                "criterion_met": dims_won >= dims_required,
                "picks": {d: winners[d] for d in dimensions},
            }
        )

    measurements = {
        "source": source,
        "judging_id": manifest["judging_id"],
        "candidate_hash": manifest["candidate_hash"],
        "reference_hash": manifest["reference_hash"],
        "rubric_hash": manifest["rubric_hash"],
        "model_reported": model,
        "dims_required": dims_required,
        "dims_total": len(dimensions),
        "runs_required": manifest["runs_required"],
        "runs": records,
        "criterion_met": all(r["criterion_met"] for r in records),
        "recorded_at": utcnow(),
    }
    if source == "judge-ingested":
        measurements["verification_note"] = (
            "the runner verified form, run count, dimensions and manifest "
            "correspondence; the production of these judgements was not "
            "verified"
        )
    return measurements


def _persist(repo_root, slice_id, judging_id, measurements):
    path = os.path.join(
        _judging_dir(repo_root, slice_id), judging_id, "measurements.json"
    )
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(measurements, handle, indent=2)
    latest = os.path.join(_judging_dir(repo_root, slice_id), "latest.json")
    with open(latest, "w", encoding="utf-8") as handle:
        json.dump(measurements, handle, indent=2)
    return measurements


def ingest(repo_root, slice_id, results):
    """Record harness-supplied blind results. Verifies form, not production."""
    judging_id = results.get("judging_id")
    if not judging_id:
        raise Refusal("results carry no judging_id")
    manifest = _load_manifest(repo_root, slice_id, judging_id)
    measurements = _unblind(
        manifest,
        results.get("runs"),
        "judge-ingested",
        results.get("model") or "unreported",
    )
    return _persist(repo_root, slice_id, judging_id, measurements)


def run_executed(repo_root, slice_id, candidate_path):
    """Prepare and judge in one step, with the runner invoking the judge.

    Requires explicit configuration: .toucan/judge-config.json with a
    judge_command argument array. Each packet path is appended to it; the
    command must print one JSON object with winners (and optionally model).
    """
    config_path = os.path.join(repo_root, ".toucan", "judge-config.json")
    if not os.path.exists(config_path):
        raise Refusal(
            "executed judging requires explicit configuration at "
            ".toucan/judge-config.json with a judge_command argument array; "
            "without it, prepare packets with `toucan judge prepare` and "
            "record results with `toucan judge ingest`"
        )
    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    command = config.get("judge_command")
    if not isinstance(command, list) or not command:
        raise Refusal("judge-config.json must carry judge_command as an array")

    manifest = prepare(repo_root, slice_id, candidate_path)
    run_results = []
    models = set()
    for entry in manifest["runs"]:
        packet = os.path.join(repo_root, entry["packet_path"])
        try:
            completed = subprocess.run(
                command + [packet],
                cwd=repo_root, capture_output=True, text=True,
                timeout=600, shell=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise Refusal("judge command failed on run %d: %s"
                          % (entry["run"], exc))
        if completed.returncode != 0:
            raise Refusal(
                "judge command exited %d on run %d: %s"
                % (completed.returncode, entry["run"],
                   (completed.stderr or "").strip()[:200])
            )
        try:
            output = json.loads(completed.stdout)
        except json.JSONDecodeError:
            raise Refusal(
                "judge command produced non-JSON output on run %d" % entry["run"]
            )
        models.add(output.get("model") or "unreported")
        run_results.append({"run": entry["run"],
                            "winners": output.get("winners")})

    measurements = _unblind(
        manifest, run_results, "judge-executed",
        sorted(models)[0] if len(models) == 1 else sorted(models),
    )
    return _persist(repo_root, slice_id, manifest["judging_id"], measurements)


def latest_measurements(repo_root, slice_id):
    path = os.path.join(_judging_dir(repo_root, slice_id), "latest.json")
    if not os.path.exists(path):
        raise Refusal(
            "no judging has been recorded for slice %r" % slice_id
        )
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)
