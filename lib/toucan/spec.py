"""The slice specification: field records, provenance, and serialisation.

Provenance is a property of every field rather than a note in prose, because
the rule that matters -- interrogate only what the model invented -- is then a
filter over data instead of an instruction a model has to remember.
"""

import copy
import datetime

from .errors import Refusal

SCHEMA_VERSION = 2

YOURS = "yours"
DETECTED = "detected"
INFERRED = "inferred"
PROVENANCE_CLASSES = (YOURS, DETECTED, INFERRED)

#: Fields the critic's invocation contract requires before it can reach a
#: verdict without inventing or repairing the contract.
REQUIRED_FIELDS = (
    "criterion",
    "oracle",
    "protected_paths",
    "approved_oracle_changes",
    "required_runs",
    "allow_skips",
    "iteration_maximum",
)


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def field(value, provenance, evidence=None):
    """Build a field record.

    ``evidence`` names the human phrase or repository file the value came
    from. An inferred field has no evidence by definition.
    """
    if provenance not in PROVENANCE_CLASSES:
        raise Refusal(
            "unknown provenance %r (expected one of %s)"
            % (provenance, ", ".join(PROVENANCE_CLASSES))
        )
    if provenance == INFERRED and evidence:
        raise Refusal("an inferred field cannot cite evidence; it had none")
    return {"value": value, "provenance": provenance, "evidence": evidence}


def new_spec(slice_id, intent_text=None):
    """Create an unfrozen draft specification.

    Absent intent is recorded as absent. Substituting a generated description
    would destroy the one uncontaminated, human-authored input in the system.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "slice_id": slice_id,
        "created_at": utcnow(),
        "intent": (
            {"supplied": True, "text": intent_text}
            if intent_text is not None
            else {"supplied": False, "text": None}
        ),
        "fields": {},
        "baseline": None,
        "frozen": None,
        "history": [],
    }


def set_field(spec, name, value, provenance, evidence=None):
    """Set a field on an unfrozen specification."""
    require_unfrozen(spec)
    spec["fields"][name] = field(value, provenance, evidence)
    return spec


def ratify(spec, name, value, evidence="ratified by human"):
    """Record a human's selection or entry for a field.

    A ratified field is reclassed to ``yours``: the human chose the value, so
    the model is no longer its author.
    """
    require_unfrozen(spec)
    if name not in spec["fields"]:
        raise Refusal("cannot ratify unknown field %r" % name)
    spec["fields"][name] = field(value, YOURS, evidence)
    return spec


def get(spec, name, default=None):
    record = spec["fields"].get(name)
    return default if record is None else record["value"]


def provenance_of(spec, name):
    record = spec["fields"].get(name)
    return None if record is None else record["provenance"]


def unratified(spec):
    """Field names still classed ``inferred``.

    Registration cannot terminate while any remain: every one is a value the
    model put in the human's mouth.
    """
    return sorted(
        name
        for name, record in spec["fields"].items()
        if record["provenance"] == INFERRED
    )


def is_frozen(spec):
    return spec.get("frozen") is not None


def require_unfrozen(spec):
    if is_frozen(spec):
        raise Refusal(
            "specification is frozen; changes must go through `toucan amend`, "
            "which creates a new version and records it in the ledger"
        )


def hashable_view(spec):
    """The document that the content hash commits to.

    Excludes the hash itself and the mutable history log, and includes
    everything a later reader must be able to prove was fixed before the first
    attempt: intent, every field, and the baseline.
    """
    view = {
        "schema_version": spec["schema_version"],
        "slice_id": spec["slice_id"],
        "intent": spec["intent"],
        "fields": copy.deepcopy(spec["fields"]),
        "baseline": copy.deepcopy(spec["baseline"]),
    }
    frozen = spec.get("frozen")
    if frozen is not None:
        view["frozen"] = {
            "version": frozen["version"],
            "frozen_at": frozen["frozen_at"],
            "base_sha": frozen["base_sha"],
            "previous_hash": frozen.get("previous_hash"),
        }
    return view
