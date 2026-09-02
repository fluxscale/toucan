"""The strictness ladder.

The slots are fixed by this module, not chosen by a model. That is the whole
point: a model asked to propose criteria can propose four weak ones and a human
will ratify one while feeling like its author. It cannot suppress the strict
options when the slots are mandated here and filled from recorded baseline
facts.
"""

NARROW = "narrow"
MODULE = "module"
BROAD = "broad"
HARDENED = "hardened"

SLOTS = (NARROW, MODULE, BROAD, HARDENED)


def _target_groups(failing_targets):
    groups = []
    for target in failing_targets:
        group = target.split("::")[0] if "::" in target else target
        if group and group not in groups:
            groups.append(group)
    return groups


def ladder(baseline):
    """Build one candidate per slot from the recorded baseline.

    Every candidate names what it gives up, because a set of options that hides
    which one is weakest has concealed the only thing worth deciding.
    """
    measurements = baseline.get("measurements", {})
    failing = measurements.get("failing_targets") or []
    failed = measurements.get("failed") or 0
    collected = measurements.get("collected")
    duration = baseline.get("oracle", {}).get("duration_seconds")
    groups = _target_groups(failing)

    def cost(multiplier=1.0):
        if duration is None:
            return "unknown"
        return "~%.0fs" % (duration * multiplier)

    candidates = []

    if failing:
        listed = ", ".join(failing[:3]) + ("" if len(failing) <= 3 else ", ...")
        narrow_text = (
            "The %d target(s) failing at baseline pass: %s" % (failed, listed)
        )
    else:
        narrow_text = (
            "The targets failing at baseline pass (identities unavailable from "
            "this adapter's output)"
        )
    candidates.append(
        {
            "slot": NARROW,
            "criterion": narrow_text,
            "gives_up": "Permits collateral breakage anywhere else in the suite.",
            "cost": cost(),
            "required_runs": 1,
            "allow_skips": False,
        }
    )

    if groups:
        group_text = ", ".join(groups[:2]) + ("" if len(groups) <= 2 else ", ...")
        module_criterion = (
            "Every target in %s passes, with no skips" % group_text
        )
    else:
        module_criterion = "Every target in the failing module passes, with no skips"
    candidates.append(
        {
            "slot": MODULE,
            "criterion": module_criterion,
            "gives_up": "Does not detect regressions outside the failing module.",
            "cost": cost(),
            "required_runs": 1,
            "allow_skips": False,
        }
    )

    total = "all %d" % collected if collected else "every"
    candidates.append(
        {
            "slot": BROAD,
            "criterion": (
                "%s registered target(s) pass under the full oracle, with no "
                "skips and no new skips relative to baseline" % total
            ),
            "gives_up": "Nothing in coverage; costs a full suite run per attempt.",
            "cost": cost(),
            "required_runs": 1,
            "allow_skips": False,
        }
    )

    candidates.append(
        {
            "slot": HARDENED,
            "criterion": (
                "%s registered target(s) pass under the full oracle across two "
                "consecutive runs, with no skips and no retries" % total
            ),
            "gives_up": "Nothing; costs twice the full suite per attempt.",
            "cost": cost(2.0),
            "required_runs": 2,
            "allow_skips": False,
        }
    )

    return candidates
