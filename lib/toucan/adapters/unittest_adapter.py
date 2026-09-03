"""stdlib unittest adapter.

Measurements come from the JSON report `toucan unittest-run` writes -- the
same loader and discovery as `python3 -m unittest discover`, plus a report,
because unittest has no machine-readable output of its own.
"""

import json
import os
import re
import subprocess

NAME = "unittest"

PROTECTED_PATHS = [
    "tests/**",
    "test/**",
    "**/test_*.py",
    "**/*_test.py",
    "pyproject.toml",
    "setup.cfg",
    "tox.ini",
    "Makefile",
    ".github/workflows/**",
    "requirements*.txt",
]

EXECUTION_EVIDENCE = (
    "A JSON report written by the toucan unittest runner carrying collected, "
    "executed, passed, failed and skipped counts plus the identities of "
    "failing, skipped and load-error targets; positive execution is "
    "established from the counts and the empty load-error list."
)

_IMPORT = re.compile(r"^\s*(?:import unittest\b|from unittest\b)", re.MULTILINE)


def _test_files(repo_root, directory):
    base = os.path.join(repo_root, directory)
    if not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base)):
        if (name.startswith("test") or name.endswith("_test.py")) and name.endswith(".py"):
            out.append(os.path.join(base, name))
    return out


def _imports_unittest(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return bool(_IMPORT.search(handle.read()))
    except OSError:
        return False


def probe(argv, cwd=None):
    """unittest ships with the interpreter; the probe proves exactly that."""
    interpreter = argv[0] if argv and argv[0] != "toucan" else "python3"
    if interpreter == "toucan":
        interpreter = "python3"
    try:
        completed = subprocess.run(
            [interpreter, "-c", "import unittest"],
            cwd=cwd, capture_output=True, text=True, timeout=30, shell=False,
        )
    except FileNotFoundError:
        return False, "%s is not on PATH" % interpreter
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "could not be started: %s" % exc
    if completed.returncode != 0:
        return False, (completed.stderr or "").strip().splitlines()[0:1] or "failed"
    return True, "stdlib unittest via %s" % interpreter


def detect(repo_root, verify=True):
    evidence = None
    for directory in ("tests", "test"):
        for path in _test_files(repo_root, directory):
            if _imports_unittest(path):
                evidence = (85, "%s imports unittest"
                            % os.path.relpath(path, repo_root), "strong", directory)
                break
        if evidence:
            break

    if evidence is None:
        for directory in ("tests", "test"):
            if os.path.isdir(os.path.join(repo_root, directory)):
                evidence = (
                    30,
                    "%s/ directory (weak: tests exist, but none read as "
                    "unittest)" % directory,
                    "weak",
                    directory,
                )
                break

    if evidence is None:
        return []

    confidence, label, strength, start_dir = evidence
    argv = ["toucan", "unittest-run", "-s", start_dir]

    runnable, detail = (True, "not verified")
    if verify:
        runnable, detail = probe(argv, cwd=repo_root)
        if not runnable:
            confidence = min(confidence, 5)

    return [
        {
            "adapter": NAME,
            "argv": argv,
            "cwd": ".",
            "timeout_seconds": 900,
            "confidence": confidence,
            "evidence": label,
            "evidence_strength": strength,
            "runnable": runnable,
            "runnable_detail": detail,
            "execution_evidence": EXECUTION_EVIDENCE,
        }
    ]


def protected_paths(repo_root=None):
    return list(PROTECTED_PATHS)


def measurement_args(report_path):
    """Adds the report. Same loader, same discovery, nothing selected out."""
    return ["--report", report_path]


def parse(result, report_path):
    if report_path and os.path.exists(report_path):
        try:
            with open(report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
        except (OSError, json.JSONDecodeError):
            report = None
        if report is not None:
            return {
                "source": "runner",
                "collected": report["collected"],
                "executed": report["executed"],
                "passed": report["passed"],
                "failed": report["failed"],
                "skipped": report["skipped"],
                "failing_targets": report["failing_targets"],
            }
    match = re.search(r"Ran (\d+) tests?", result.get("stderr", "") +
                      result.get("stdout", ""))
    return {
        "source": "parsed",
        "collected": int(match.group(1)) if match else None,
        "executed": None,
        "passed": None,
        "failed": None,
        "skipped": None,
        "failing_targets": [],
        "note": "no runner report was produced; counts are unavailable rather "
        "than guessed",
    }
