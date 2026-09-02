"""Baseline capture.

Executing the oracle once at registration pays for itself three times: it
proves the argument array runs before any iteration budget is spent finding out
it does not, it records which targets fail by name so a later verdict can tell
`fixed` from `never ran`, and it pins a narrow criterion to a frozen set rather
than a moving target.
"""

import os
import tempfile

from . import adapters, oracle, signals
from .errors import Refusal
from .spec import utcnow


def capture(repo_root, oracle_spec):
    """Run the oracle and return a baseline record.

    Raises ``oracle.ExecutionFailure`` when the invocation cannot be executed,
    which is a different thing from the criterion failing and must not be
    recorded as a baseline.
    """
    adapter = adapters.get(oracle_spec["adapter"])
    cwd = os.path.join(repo_root, oracle_spec.get("cwd", "."))

    with tempfile.TemporaryDirectory(prefix="toucan-baseline-") as tmp:
        report_path = os.path.join(tmp, "report.xml")
        result = oracle.run(
            oracle_spec["argv"],
            cwd=cwd,
            timeout_seconds=oracle_spec["timeout_seconds"],
            extra_args=adapter.measurement_args(report_path),
        )
        measurements = adapter.parse(result, report_path)

    return {
        "captured_at": utcnow(),
        "base_sha": signals.head_sha(repo_root),
        "oracle": {
            "argv": oracle_spec["argv"],
            "cwd": oracle_spec.get("cwd", "."),
            "adapter": oracle_spec["adapter"],
            "exit_status": result["exit_status"],
            "duration_seconds": result["duration_seconds"],
        },
        "measurements": measurements,
        "evidence_excerpt": _excerpt(result),
    }


def _excerpt(result, limit=400):
    text = (result.get("stdout") or "").strip() or (result.get("stderr") or "").strip()
    tail = text.splitlines()[-3:]
    return "\n".join(tail)[:limit]


def require_actionable(baseline):
    """Refuse a baseline that leaves nothing for a criterion to prove.

    A fully passing oracle means any criterion drawn from it is already
    satisfied, and a criterion the tree already meets verifies nothing.
    """
    measurements = baseline.get("measurements", {})
    failed = measurements.get("failed")
    if failed is None:
        raise Refusal(
            "the baseline produced no usable counts, so there is nothing to "
            "anchor a criterion to. Supply an oracle whose output this adapter "
            "can measure."
        )
    if failed == 0:
        raise Refusal(
            "the oracle already passes on this tree. A criterion drawn from a "
            "green baseline is satisfied before any work is done. Supply a "
            "criterion the current tree does not already meet, or register a "
            "narrower oracle that does fail."
        )
    return baseline
