"""The sufficiency predicate.

One implementation, two callers. Registration uses it to decide whether it may
freeze; the critic uses it to decide whether to return INVALID-SPEC. Because
the check is shared, registration cannot terminate on a specification the
critic would later reject -- which makes an INVALID-SPEC verdict structurally
unreachable, and therefore a meaningful alarm if one ever fires.
"""

from . import spec as spec_mod
from .oracle import argv_objection

_POSITIVE_INT = "must be an integer of at least 1"


def _check_oracle(value):
    problems = []
    if not isinstance(value, dict):
        return ["oracle must be an object with argv, cwd, timeout_seconds and adapter"]
    argv = value.get("argv")
    if not isinstance(argv, list) or not argv:
        problems.append("oracle.argv must be a non-empty argument array")
    elif not all(isinstance(a, str) for a in argv):
        problems.append("oracle.argv must contain only strings")
    else:
        objection = argv_objection(argv)
        if objection:
            problems.append("oracle.argv %s" % objection)
    if not isinstance(value.get("cwd"), str) or not value.get("cwd"):
        problems.append("oracle.cwd must be a path")
    timeout = value.get("timeout_seconds")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
        problems.append("oracle.timeout_seconds " + _POSITIVE_INT)
    if not isinstance(value.get("adapter"), str) or not value.get("adapter"):
        problems.append("oracle.adapter must name the adapter that runs it")
    if not isinstance(value.get("execution_evidence"), str) or not value.get(
        "execution_evidence"
    ):
        problems.append(
            "oracle.execution_evidence must state how successful execution is "
            "positively recognised for this adapter"
        )
    return problems


def _check_positive_int(name, value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return ["%s %s" % (name, _POSITIVE_INT)]
    return []


def evaluate(spec):
    """Return a report on whether ``spec`` is sufficient to act on.

    ``missing`` lists required fields absent entirely. ``ambiguous`` lists
    fields present but unusable. ``unratified`` lists fields the model authored
    that no human has yet accepted -- sufficient for the critic to judge, but
    not sufficient for registration to freeze.
    """
    missing = []
    ambiguous = []

    for name in spec_mod.REQUIRED_FIELDS:
        if name not in spec.get("fields", {}):
            missing.append(name)

    fields = spec.get("fields", {})

    if "criterion" in fields:
        criterion = fields["criterion"]["value"]
        if not isinstance(criterion, str) or not criterion.strip():
            ambiguous.append("criterion must be a concrete observable claim")

    if "oracle" in fields:
        ambiguous.extend(_check_oracle(fields["oracle"]["value"]))

    for name in ("required_runs", "iteration_maximum"):
        if name in fields:
            ambiguous.extend(_check_positive_int(name, fields[name]["value"]))

    if "allow_skips" in fields and not isinstance(fields["allow_skips"]["value"], bool):
        ambiguous.append("allow_skips must be true or false, not left open")

    for name in ("protected_paths", "approved_oracle_changes"):
        if name in fields and not isinstance(fields[name]["value"], list):
            ambiguous.append("%s must be a list, even when empty" % name)

    oracle_value = fields.get("oracle", {}).get("value")         if "oracle" in fields else None
    if isinstance(oracle_value, dict) and oracle_value.get("adapter") == "judge":
        reference = fields.get("reference", {}).get("value")             if "reference" in fields else None
        if not isinstance(reference, dict):
            missing.append("reference")
        elif not reference.get("content_hash") or not reference.get("name"):
            ambiguous.append(
                "reference must carry a name and the content hash recorded at "
                "registration"
            )
        rubric_value = fields.get("rubric", {}).get("value")             if "rubric" in fields else None
        if not isinstance(rubric_value, dict):
            missing.append("rubric")
        else:
            if not rubric_value.get("dimensions"):
                ambiguous.append("rubric must name at least one dimension")
            runs = rubric_value.get("runs_required")
            if not isinstance(runs, int) or runs < 3:
                ambiguous.append(
                    "rubric.runs_required must be at least 3: a "
                    "nondeterministic instrument carries a stricter standard"
                )
            dims = rubric_value.get("dims_required")
            if not isinstance(dims, int) or dims < 1:
                ambiguous.append("rubric.dims_required " + _POSITIVE_INT)

    if not spec.get("slice_id"):
        missing.append("slice_id")

    if spec.get("baseline") is None:
        missing.append("baseline")

    report = {
        "slice_id": spec.get("slice_id"),
        "missing": sorted(set(missing)),
        "ambiguous": sorted(set(ambiguous)),
        "unratified": spec_mod.unratified(spec),
    }
    report["sufficient"] = not report["missing"] and not report["ambiguous"]
    report["ready_to_freeze"] = report["sufficient"] and not report["unratified"]
    return report
