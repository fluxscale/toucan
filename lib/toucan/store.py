"""On-disk layout under .toucan/ and the freeze / amend operations.

Ordering is enforced here by refusal rather than by the sequence of steps in a
prompt. A caller that skipped the baseline gets an error, not a
plausible-looking success.
"""

import json
import os

from . import ledger as ledger_mod
from . import spec as spec_mod
from .canonical import content_hash, pretty
from .errors import NotFound, Refusal, Tampered
from .sufficiency import evaluate

STATE_DIR = ".toucan"


def state_root(repo_root):
    return os.path.join(repo_root, STATE_DIR)


def slice_dir(repo_root, slice_id):
    return os.path.join(state_root(repo_root), "slices", slice_id)


def draft_path(repo_root, slice_id):
    return os.path.join(slice_dir(repo_root, slice_id), "draft.json")


def version_path(repo_root, slice_id, version):
    return os.path.join(slice_dir(repo_root, slice_id), "spec.v%d.json" % version)


def ledger_path(repo_root, slice_id):
    return os.path.join(slice_dir(repo_root, slice_id), "ledger.jsonl")


def _write(path, document):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(pretty(document))


def save_draft(repo_root, spec):
    spec_mod.require_unfrozen(spec)
    _write(draft_path(repo_root, spec["slice_id"]), spec)
    return spec


def load_draft(repo_root, slice_id):
    path = draft_path(repo_root, slice_id)
    if not os.path.exists(path):
        raise NotFound(
            "no draft for slice %r. Start one with `toucan spec init`." % slice_id
        )
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def latest_version(repo_root, slice_id):
    directory = slice_dir(repo_root, slice_id)
    if not os.path.isdir(directory):
        return None
    versions = []
    for name in os.listdir(directory):
        if name.startswith("spec.v") and name.endswith(".json"):
            try:
                versions.append(int(name[len("spec.v") : -len(".json")]))
            except ValueError:
                continue
    return max(versions) if versions else None


def load_frozen(repo_root, slice_id, version=None):
    """Load a frozen specification and verify it against its own hash."""
    if version is None:
        version = latest_version(repo_root, slice_id)
    if version is None:
        raise NotFound("slice %r has no frozen specification" % slice_id)
    path = version_path(repo_root, slice_id, version)
    if not os.path.exists(path):
        raise NotFound("slice %r has no version %d" % (slice_id, version))
    with open(path, "r", encoding="utf-8") as handle:
        document = json.load(handle)
    recorded = document["frozen"]["content_hash"]
    recomputed = content_hash(spec_mod.hashable_view(document))
    if recorded != recomputed:
        raise Tampered(
            "frozen specification %s v%d does not match its recorded hash. It "
            "was modified after freezing and is not authoritative."
            % (slice_id, version)
        )
    return document


def list_slices(repo_root):
    """Every slice with its state, for the live-slice branch of registration."""
    base = os.path.join(state_root(repo_root), "slices")
    if not os.path.isdir(base):
        return []
    out = []
    for slice_id in sorted(os.listdir(base)):
        version = latest_version(repo_root, slice_id)
        entry = {"slice_id": slice_id, "frozen_version": version}
        if version is None:
            entry["state"] = "draft"
            try:
                draft = load_draft(repo_root, slice_id)
                entry["criterion"] = spec_mod.get(draft, "criterion")
                entry["intent"] = draft["intent"]
            except NotFound:
                entry["state"] = "empty"
        else:
            document = load_frozen(repo_root, slice_id, version)
            entry["criterion"] = spec_mod.get(document, "criterion")
            entry["intent"] = document["intent"]
            entry["iteration"] = document["frozen"].get("iteration", 0)
            entry["iteration_maximum"] = spec_mod.get(document, "iteration_maximum")
            entry["state"] = document["frozen"].get("state", "live")
        out.append(entry)
    return out


def freeze(repo_root, slice_id, base_sha):
    """Freeze the draft. Refuses unless everything it commits to is present."""
    draft = load_draft(repo_root, slice_id)
    spec_mod.require_unfrozen(draft)

    if draft.get("baseline") is None:
        raise Refusal(
            "cannot freeze %r: no baseline has been recorded. Run `toucan "
            "baseline` first -- a specification whose oracle has never been "
            "observed to execute is not one the critic can trust." % slice_id
        )

    report = evaluate(draft)
    if not report["sufficient"]:
        raise Refusal(
            "cannot freeze %r: specification is insufficient.\n  missing: %s\n"
            "  ambiguous: %s"
            % (
                slice_id,
                ", ".join(report["missing"]) or "none",
                "; ".join(report["ambiguous"]) or "none",
            )
        )
    if report["unratified"]:
        raise Refusal(
            "cannot freeze %r: %s still classed `inferred`. Every value the "
            "model authored must be ratified by a human before it is frozen."
            % (slice_id, ", ".join(report["unratified"]))
        )

    version = (latest_version(repo_root, slice_id) or 0) + 1
    previous_hash = None
    if version > 1:
        previous_hash = load_frozen(repo_root, slice_id, version - 1)["frozen"][
            "content_hash"
        ]

    draft["frozen"] = {
        "version": version,
        "frozen_at": spec_mod.utcnow(),
        "base_sha": base_sha,
        "previous_version": version - 1 if version > 1 else None,
        "previous_hash": previous_hash,
        "iteration": 0,
        "state": "live",
    }
    draft["frozen"]["content_hash"] = content_hash(spec_mod.hashable_view(draft))

    _write(version_path(repo_root, slice_id, version), draft)
    os.remove(draft_path(repo_root, slice_id))

    ledger_mod.append(
        ledger_path(repo_root, slice_id),
        {
            "event": "frozen",
            "version": version,
            "content_hash": draft["frozen"]["content_hash"],
            "base_sha": base_sha,
            "criterion": spec_mod.get(draft, "criterion"),
            "required_runs": spec_mod.get(draft, "required_runs"),
        },
    )
    return draft


def diff_fields(previous, current):
    """Field-level difference between two specification versions."""
    changes = []
    names = sorted(set(previous["fields"]) | set(current["fields"]))
    for name in names:
        before = previous["fields"].get(name)
        after = current["fields"].get(name)
        if before == after:
            continue
        changes.append(
            {
                "field": name,
                "before": None if before is None else before["value"],
                "after": None if after is None else after["value"],
            }
        )
    return changes


def amend(repo_root, slice_id, updates, justification, iteration):
    """Create a new frozen version. Never mutates the version it supersedes.

    Amendment after an attempt has been observed is the one path by which a
    criterion can be weakened invisibly, so it is loud: a new hash, a recorded
    difference, and a ledger entry naming the iteration it happened at.
    """
    current = load_frozen(repo_root, slice_id)

    if not justification or not justification.strip():
        raise Refusal("an amendment requires a justification")

    amended = json.loads(json.dumps(current))
    amended["frozen"] = None
    amended["intent"] = current["intent"]

    for name, record in updates.items():
        amended["fields"][name] = record

    failures = [
        entry
        for entry in ledger_mod.read(ledger_path(repo_root, slice_id))
        if entry["entry"].get("event") == "verdict"
        and entry["entry"].get("verdict") == "FAIL"
    ]
    if failures:
        current_runs = spec_mod.get(amended, "required_runs") or 1
        if current_runs < 2:
            amended["fields"]["required_runs"] = spec_mod.field(
                2,
                spec_mod.DETECTED,
                "escalated: the criterion failed on a previous iteration, so a "
                "single clean run cannot distinguish a fix from a coin flip",
            )

    changes = diff_fields(current, amended)
    version = current["frozen"]["version"] + 1
    amended["frozen"] = {
        "version": version,
        "frozen_at": spec_mod.utcnow(),
        "base_sha": current["frozen"]["base_sha"],
        "previous_version": current["frozen"]["version"],
        "previous_hash": current["frozen"]["content_hash"],
        "iteration": iteration,
        "state": "live",
        "amendment": {"justification": justification, "changes": changes},
    }
    amended["frozen"]["content_hash"] = content_hash(spec_mod.hashable_view(amended))

    _write(version_path(repo_root, slice_id, version), amended)
    ledger_mod.append(
        ledger_path(repo_root, slice_id),
        {
            "event": "amended",
            "version": version,
            "at_iteration": iteration,
            "justification": justification,
            "changes": changes,
            "content_hash": amended["frozen"]["content_hash"],
        },
    )
    return amended
