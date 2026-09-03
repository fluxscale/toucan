"""Loop state, derived entirely from the ledger.

Nothing here is stored in a mutable field. Iteration, pending verdicts, budget
consumption, closure and stalling are all computed by replaying the
hash-chained ledger -- so the loop's control state inherits tamper-evidence
instead of trusting a counter somebody could edit.
"""

from . import ledger as ledger_mod
from . import spec as spec_mod
from .errors import Refusal

#: Verdicts that consume budget. BLOCKED and INVALID-SPEC do not, per the
#: critic contract: they are the environment's failures, not the attempt's.
CONSUMING = ("FAIL",)

STALL_DEFAULTS = {
    "metric": "failed",
    "direction": "decreasing",
    "window": 3,
    "epsilon": 0,
}

OUTCOMES = ("passed", "exhausted", "abandoned")


def replay(ledger_path):
    """Fold the ledger into the loop's control state."""
    state = {
        "attempts_started": 0,
        "verdicts": [],
        "pending_attempt": None,
        "consumed": 0,
        "closed": None,
        "last_verdict": None,
    }
    for record in ledger_mod.read(ledger_path):
        entry = record["entry"]
        event = entry.get("event")
        if event == "attempt_started":
            state["attempts_started"] += 1
            state["pending_attempt"] = state["attempts_started"]
        elif event == "verdict":
            state["verdicts"].append(entry)
            state["last_verdict"] = entry.get("verdict")
            state["pending_attempt"] = None
            if entry.get("verdict") in CONSUMING:
                state["consumed"] += 1
        elif event == "closed":
            state["closed"] = entry.get("outcome")
    return state


def stall_rule(spec):
    declared = spec_mod.get(spec, "stall")
    rule = dict(STALL_DEFAULTS)
    if isinstance(declared, dict):
        rule.update({k: declared[k] for k in STALL_DEFAULTS if k in declared})
        rule["declared"] = True
    else:
        rule["declared"] = False
    return rule


def _improved(direction, best, value, epsilon):
    if value is None or best is None:
        return False
    if direction == "decreasing":
        return value < best - epsilon
    return value > best + epsilon


def stall_report(spec, state):
    """Apply the stall rule to the FAIL-verdict measurement series.

    An unmeasurable window counts as stalled: a loop that cannot measure its
    own progress must not be an unbounded one.
    """
    rule = stall_rule(spec)
    series = [
        (v.get("measurements") or {}).get(rule["metric"])
        for v in state["verdicts"]
        if v.get("verdict") in CONSUMING
    ]

    window = rule["window"]
    stalled = False
    if len(series) >= window:
        head, tail = series[:-window], series[-window:]
        best = None
        for value in head:
            if value is not None and (
                best is None or _improved(rule["direction"], best, value, 0)
            ):
                best = value
        improved = False
        for value in tail:
            if _improved(rule["direction"], best, value, rule["epsilon"]):
                improved = True
            if value is not None and (
                best is None or _improved(rule["direction"], best, value, 0)
            ):
                best = value
        stalled = not improved

    return {"stalled": stalled, "rule": rule, "series": series}


def refuse_if_unstartable(spec, state):
    """The single choke point for starting an attempt."""
    if state["closed"]:
        raise Refusal(
            "slice is closed (%s); a closed slice takes no further attempts"
            % state["closed"]
        )
    if state["pending_attempt"] is not None:
        raise Refusal(
            "attempt %d has no recorded verdict; record it with `toucan "
            "verdict record` before starting another" % state["pending_attempt"]
        )
    if state["last_verdict"] == "PASS":
        raise Refusal(
            "the criterion already has a PASS verdict; close the slice rather "
            "than attempting further work against it"
        )
    maximum = spec_mod.get(spec, "iteration_maximum")
    if maximum is not None and state["consumed"] >= maximum:
        raise Refusal(
            "budget exhausted: %d failure verdict(s) against a maximum of %d. "
            "Close the slice as exhausted, or amend the budget -- visibly."
            % (state["consumed"], maximum)
        )
    report = stall_report(spec, state)
    if report["stalled"]:
        raise Refusal(
            "slice is stalled: metric %r has not improved (%s) across the "
            "last %d failure verdicts (series: %s). Close the slice as "
            "exhausted, or amend the approach -- visibly."
            % (
                report["rule"]["metric"],
                report["rule"]["direction"],
                report["rule"]["window"],
                report["series"],
            )
        )
