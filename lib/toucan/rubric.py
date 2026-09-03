"""The rubric severity ladder.

Same structural guarantee as the criterion ladder: the slots are mandated
here, filled with the slice's dimensions, and the strict end cannot be
suppressed by whoever drafts the options.
"""

MIN_RUNS = 3

SLOTS = ("majority", "strong", "unanimous", "exacting")


def ladder(dimensions):
    """One candidate per severity slot for the given rubric dimensions."""
    total = len(dimensions)
    majority = total // 2 + 1
    strong = max(total - 1, majority)
    return [
        {
            "slot": "majority",
            "dims_required": majority,
            "runs_required": MIN_RUNS,
            "description": "candidate wins %d of %d dimensions in every run"
            % (majority, total),
            "gives_up": "permits losing %d dimension(s) outright" % (total - majority),
        },
        {
            "slot": "strong",
            "dims_required": strong,
            "runs_required": MIN_RUNS,
            "description": "candidate wins %d of %d dimensions in every run"
            % (strong, total),
            "gives_up": "permits losing one dimension" if strong < total
            else "nothing in coverage",
        },
        {
            "slot": "unanimous",
            "dims_required": total,
            "runs_required": MIN_RUNS,
            "description": "candidate wins every dimension in every run",
            "gives_up": "nothing; a single lost dimension fails the criterion",
        },
        {
            "slot": "exacting",
            "dims_required": total,
            "runs_required": 5,
            "description": "candidate wins every dimension in every one of 5 runs",
            "gives_up": "nothing; costs five judgings per verification",
        },
    ]
