"""Command line interface.

Every subcommand emits JSON on stdout. This is a machine interface consumed by
the registration skill; the skill is responsible for rendering it for a human.

Refusals exit non-zero with a JSON body naming the condition, so a caller that
skipped a step gets an error rather than a plausible-looking success.
"""

import argparse
import json
import os
import sys

from . import adapters, baseline as baseline_mod, criteria, ledger as ledger_mod
from . import signals as signals_mod, spec as spec_mod, store
from .errors import Refusal, ToucanError
from .oracle import ExecutionFailure
from .sufficiency import evaluate

MIN_PYTHON = (3, 8)


def emit(payload, stream=None):
    json.dump(payload, stream or sys.stdout, indent=2, ensure_ascii=False)
    (stream or sys.stdout).write("\n")


def repo_root(args):
    root = os.path.abspath(args.repo)
    if not os.path.isdir(root):
        raise Refusal("repository path does not exist: %s" % root)
    return root


# --------------------------------------------------------------------------
# commands


def cmd_doctor(args):
    ok = sys.version_info >= MIN_PYTHON
    emit(
        {
            "python_version": ".".join(str(p) for p in sys.version_info[:3]),
            "python_supported": ok,
            "minimum_python": ".".join(str(p) for p in MIN_PYTHON),
            "adapters": sorted(adapters.ADAPTERS),
            "ok": ok,
        }
    )
    return 0 if ok else 5


def cmd_detect(args):
    root = repo_root(args)
    candidates = adapters.detect_all(root)
    usable = adapters.runnable(candidates)
    preferred = usable[0] if usable else (candidates[0] if candidates else None)

    payload = {
        "candidates": candidates,
        "runnable_candidates": usable,
        "ambiguous": len(usable) > 1,
        "protected_paths": (
            adapters.get(preferred["adapter"]).protected_paths(root)
            if preferred
            else []
        ),
    }

    if not candidates:
        payload["refusal"] = (
            "no recognised runner configuration was found. Toucan does not "
            "guess an oracle; supply the invocation as an argument array."
        )
    elif not usable:
        blocked = "; ".join(
            "%s (%s): %s"
            % (c["adapter"], " ".join(c["argv"]), c.get("runnable_detail", "unknown"))
            for c in candidates
        )
        payload["refusal"] = (
            "a runner was recognised but none of the detected invocations can "
            "be started, so none of them is an oracle: %s. Supply an "
            "invocation that runs in this tree as it stands." % blocked
        )
    elif any(c.get("evidence_strength") == "weak" for c in usable):
        payload["caution"] = (
            "the strongest evidence is weak: a test directory shows tests "
            "exist, not which runner runs them. Confirm the invocation rather "
            "than presenting it as established."
        )

    emit(payload)
    return 0 if usable or not candidates else 2


def cmd_signals(args):
    root = repo_root(args)
    found = signals_mod.collect(root)
    found["independent_signal_present"] = signals_mod.independent_signal_present(found)
    if not found["independent_signal_present"]:
        found["guidance"] = (
            "No transcript-independent signal of intended work. Ask the human "
            "what they want rather than drafting a criterion from conversation."
        )
    emit(found)
    return 0


def cmd_spec_init(args):
    root = repo_root(args)
    if args.intent is not None and args.no_intent:
        raise Refusal("pass either --intent or --no-intent, not both")
    if args.intent is None and not args.no_intent:
        raise Refusal(
            "pass --intent TEXT to record the human's own words verbatim, or "
            "--no-intent to record that none were supplied"
        )
    existing = store.latest_version(root, args.slice_id)
    if existing is not None:
        raise Refusal(
            "slice %r already has a frozen specification (v%d). Use `toucan "
            "amend` to change it, or choose a different slice id."
            % (args.slice_id, existing)
        )
    document = spec_mod.new_spec(args.slice_id, args.intent)
    store.save_draft(root, document)
    emit({"created": True, "slice_id": args.slice_id, "intent": document["intent"]})
    return 0


def _parse_value(raw):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def cmd_spec_set(args):
    root = repo_root(args)
    document = store.load_draft(root, args.slice_id)
    spec_mod.set_field(
        document,
        args.field,
        _parse_value(args.value),
        args.provenance,
        args.evidence,
    )
    store.save_draft(root, document)
    emit({"slice_id": args.slice_id, "field": args.field,
          "record": document["fields"][args.field]})
    return 0


def cmd_spec_ratify(args):
    root = repo_root(args)
    document = store.load_draft(root, args.slice_id)
    spec_mod.ratify(document, args.field, _parse_value(args.value), args.evidence)
    store.save_draft(root, document)
    emit(
        {
            "slice_id": args.slice_id,
            "field": args.field,
            "record": document["fields"][args.field],
            "still_unratified": spec_mod.unratified(document),
        }
    )
    return 0


def cmd_spec_show(args):
    root = repo_root(args)
    try:
        document = store.load_frozen(root, args.slice_id)
    except ToucanError:
        document = store.load_draft(root, args.slice_id)
    emit(document)
    return 0


def cmd_spec_check(args):
    root = repo_root(args)
    try:
        document = store.load_frozen(root, args.slice_id)
    except ToucanError:
        document = store.load_draft(root, args.slice_id)
    report = evaluate(document)
    report["frozen"] = spec_mod.is_frozen(document)
    emit(report)
    return 0 if report["sufficient"] else 2


def cmd_baseline(args):
    root = repo_root(args)
    document = store.load_draft(root, args.slice_id)
    oracle_spec = spec_mod.get(document, "oracle")
    if not oracle_spec:
        raise Refusal(
            "slice %r has no oracle. Set one before capturing a baseline."
            % args.slice_id
        )
    try:
        record = baseline_mod.capture(root, oracle_spec)
    except ExecutionFailure as exc:
        emit(
            {
                "captured": False,
                "reason": exc.reason,
                "detail": exc.detail,
                "guidance": "The oracle was not observed to execute, so no "
                "baseline was recorded and the specification cannot be frozen. "
                "Return the oracle invocation to ratification.",
            }
        )
        return 2
    if not args.allow_green:
        baseline_mod.require_actionable(record)
    document["baseline"] = record
    store.save_draft(root, document)
    emit({"captured": True, "baseline": record})
    return 0


def cmd_criteria(args):
    root = repo_root(args)
    document = store.load_draft(root, args.slice_id)
    if document.get("baseline") is None:
        raise Refusal(
            "slice %r has no baseline. Criterion candidates are built from "
            "recorded baseline facts, not invented." % args.slice_id
        )
    emit(
        {
            "slice_id": args.slice_id,
            "slots": list(criteria.SLOTS),
            "candidates": criteria.ladder(document["baseline"]),
        }
    )
    return 0


def cmd_freeze(args):
    root = repo_root(args)
    base_sha = args.base_sha or signals_mod.head_sha(root)
    if not base_sha:
        raise Refusal(
            "no baseline commit is available. Toucan needs an immutable "
            "comparison point; initialise a git repository or pass --base-sha."
        )
    document = store.freeze(root, args.slice_id, base_sha)
    emit(
        {
            "frozen": True,
            "slice_id": args.slice_id,
            "version": document["frozen"]["version"],
            "content_hash": document["frozen"]["content_hash"],
            "frozen_at": document["frozen"]["frozen_at"],
            "base_sha": document["frozen"]["base_sha"],
        }
    )
    return 0


def cmd_status(args):
    root = repo_root(args)
    slices = store.list_slices(root)
    live = [s for s in slices if s.get("state") == "live"]
    emit({"slices": slices, "live": live, "has_live_slice": bool(live)})
    return 0


def cmd_attempt_start(args):
    root = repo_root(args)
    document = store.load_frozen(root, args.slice_id)
    iteration = document["frozen"].get("iteration", 0) + 1
    maximum = spec_mod.get(document, "iteration_maximum")
    if maximum is not None and iteration > maximum:
        raise Refusal(
            "slice %r has exhausted its budget of %d iterations"
            % (args.slice_id, maximum)
        )
    ledger_mod.append(
        store.ledger_path(root, args.slice_id),
        {
            "event": "attempt_started",
            "iteration": iteration,
            "version": document["frozen"]["version"],
            "content_hash": document["frozen"]["content_hash"],
        },
    )
    emit(
        {
            "started": True,
            "slice_id": args.slice_id,
            "iteration": iteration,
            "iteration_maximum": maximum,
            "criterion": spec_mod.get(document, "criterion"),
        }
    )
    return 0


def cmd_amend(args):
    root = repo_root(args)
    updates = {}
    for assignment in args.set or []:
        if "=" not in assignment:
            raise Refusal("--set expects FIELD=JSON, got %r" % assignment)
        name, raw = assignment.split("=", 1)
        updates[name] = spec_mod.field(
            _parse_value(raw), spec_mod.YOURS, "amended by human"
        )
    if not updates:
        raise Refusal("an amendment must change at least one field")
    document = store.amend(root, args.slice_id, updates, args.justification,
                           args.at_iteration)
    emit(
        {
            "amended": True,
            "slice_id": args.slice_id,
            "version": document["frozen"]["version"],
            "previous_version": document["frozen"]["previous_version"],
            "content_hash": document["frozen"]["content_hash"],
            "changes": document["frozen"]["amendment"]["changes"],
        }
    )
    return 0


def cmd_unittest_run(args):
    """The oracle argv for unittest slices. Not a query -- it runs tests."""
    from . import unittest_run

    status, report = unittest_run.run(
        args.start_dir,
        pattern=args.pattern,
        top_level=args.top_level,
        report_path=args.report,
        stream=sys.stderr,
    )
    print(
        "%d run, %d failed, %d skipped in %.2fs"
        % (report["collected"], report["failed"], report["skipped"],
           report["duration_seconds"])
    )
    return status


def cmd_ledger_append(args):
    root = repo_root(args)
    entry = json.loads(args.entry)
    record = ledger_mod.append(store.ledger_path(root, args.slice_id), entry)
    emit({"appended": True, "record": record})
    return 0


def cmd_ledger_read(args):
    root = repo_root(args)
    emit({"entries": ledger_mod.read(store.ledger_path(root, args.slice_id))})
    return 0


def cmd_ledger_verify(args):
    root = repo_root(args)
    count = ledger_mod.verify(store.ledger_path(root, args.slice_id))
    emit({"intact": True, "entries": count})
    return 0


# --------------------------------------------------------------------------
# parser


def build_parser():
    parser = argparse.ArgumentParser(
        prog="toucan",
        description="Register, baseline and freeze verifiable slice specifications.",
    )
    parser.add_argument("--repo", default=".", help="repository root (default: .)")
    sub = parser.add_subparsers(dest="command", required=True)

    def with_slice(p):
        p.add_argument("--slice-id", required=True)
        return p

    sub.add_parser("doctor", help="report interpreter and adapter availability").set_defaults(func=cmd_doctor)
    sub.add_parser("detect", help="candidate oracles from repository evidence").set_defaults(func=cmd_detect)
    sub.add_parser("signals", help="transcript-independent signals of intended work").set_defaults(func=cmd_signals)
    sub.add_parser("status", help="slices and their state").set_defaults(func=cmd_status)

    spec_parser = sub.add_parser("spec", help="draft specification operations")
    spec_sub = spec_parser.add_subparsers(dest="spec_command", required=True)

    init = with_slice(spec_sub.add_parser("init", help="start a draft"))
    init.add_argument("--intent", help="the human's own words, stored verbatim")
    init.add_argument("--no-intent", action="store_true",
                      help="record that no intent text was supplied")
    init.set_defaults(func=cmd_spec_init)

    setter = with_slice(spec_sub.add_parser("set", help="set a field"))
    setter.add_argument("--field", required=True)
    setter.add_argument("--value", required=True, help="JSON, or a bare string")
    setter.add_argument("--provenance", required=True,
                        choices=list(spec_mod.PROVENANCE_CLASSES))
    setter.add_argument("--evidence", default=None)
    setter.set_defaults(func=cmd_spec_set)

    ratify = with_slice(spec_sub.add_parser("ratify", help="record a human's choice"))
    ratify.add_argument("--field", required=True)
    ratify.add_argument("--value", required=True)
    ratify.add_argument("--evidence", default="ratified by human")
    ratify.set_defaults(func=cmd_spec_ratify)

    with_slice(spec_sub.add_parser("show")).set_defaults(func=cmd_spec_show)
    with_slice(spec_sub.add_parser("check", help="the sufficiency predicate")).set_defaults(func=cmd_spec_check)

    base = with_slice(sub.add_parser("baseline", help="run the oracle and record it"))
    base.add_argument("--allow-green", action="store_true",
                      help="permit a baseline with no failing targets")
    base.set_defaults(func=cmd_baseline)

    with_slice(sub.add_parser("criteria", help="the strictness ladder")).set_defaults(func=cmd_criteria)

    freeze = with_slice(sub.add_parser("freeze", help="freeze the draft"))
    freeze.add_argument("--base-sha", default=None)
    freeze.set_defaults(func=cmd_freeze)

    attempt = sub.add_parser("attempt", help="attempt lifecycle")
    attempt_sub = attempt.add_subparsers(dest="attempt_command", required=True)
    with_slice(attempt_sub.add_parser("start")).set_defaults(func=cmd_attempt_start)

    amend = with_slice(sub.add_parser("amend", help="supersede a frozen version"))
    amend.add_argument("--set", action="append", metavar="FIELD=JSON")
    amend.add_argument("--justification", required=True)
    amend.add_argument("--at-iteration", type=int, required=True)
    amend.set_defaults(func=cmd_amend)

    urun = sub.add_parser(
        "unittest-run",
        help="run stdlib unittest discovery with a machine-readable report",
    )
    urun.add_argument("-s", "--start-dir", default=".")
    urun.add_argument("-p", "--pattern", default="test*.py")
    urun.add_argument("--top-level", default=None)
    urun.add_argument("--report", default=None)
    urun.set_defaults(func=cmd_unittest_run)

    led = sub.add_parser("ledger", help="durable failure memory")
    led_sub = led.add_subparsers(dest="ledger_command", required=True)
    append = with_slice(led_sub.add_parser("append"))
    append.add_argument("--entry", required=True, help="JSON object")
    append.set_defaults(func=cmd_ledger_append)
    with_slice(led_sub.add_parser("read")).set_defaults(func=cmd_ledger_read)
    with_slice(led_sub.add_parser("verify")).set_defaults(func=cmd_ledger_verify)

    return parser


def main(argv=None):
    if sys.version_info < MIN_PYTHON:
        emit(
            {
                "error": "unsupported_environment",
                "message": "Toucan requires Python %s or newer; found %s."
                % (".".join(map(str, MIN_PYTHON)),
                   ".".join(map(str, sys.version_info[:3]))),
            },
            sys.stderr,
        )
        return 5
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ToucanError as exc:
        emit({"error": type(exc).__name__.lower(), "message": str(exc)}, sys.stderr)
        return exc.exit_code
