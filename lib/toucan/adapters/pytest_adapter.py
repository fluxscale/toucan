"""pytest adapter.

Counts come from a JUnit XML report the runner writes itself, not from parsing
the terminal summary. The distinction is the difference between a measurement
and a language model's reading of one, and the critic's output contract
requires the difference be reported honestly.
"""

import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ElementTree

NAME = "pytest"

#: Test, fixture, runner, build and CI paths for a Python project. Changes
#: here are what "weakening the oracle" looks like in practice.
PROTECTED_PATHS = [
    "tests/**",
    "test/**",
    "**/conftest.py",
    "**/test_*.py",
    "**/*_test.py",
    "pytest.ini",
    "tox.ini",
    "setup.cfg",
    "pyproject.toml",
    "noxfile.py",
    "Makefile",
    ".github/workflows/**",
    "requirements*.txt",
    "poetry.lock",
    "uv.lock",
]

EXECUTION_EVIDENCE = (
    "A JUnit XML report written by pytest itself listing each registered test "
    "case, with the collected count matching the expected targets and no "
    "target reported as skipped or deselected unless skips are permitted."
)

#: Files whose content names pytest directly. A file merely existing is not
#: evidence; `tox.ini` in a project that runs nose says nothing about pytest.
_CONFIG_MARKERS = (
    ("pytest.ini", 95, "pytest.ini", None),
    ("pyproject.toml", 95, "pyproject.toml [tool.pytest.ini_options]",
     ("[tool.pytest",)),
    ("setup.cfg", 90, "setup.cfg [tool:pytest]", ("[tool:pytest]",)),
    ("tox.ini", 90, "tox.ini [pytest]", ("[pytest]", "[tool:pytest]")),
)

#: A directory of tests says tests exist. It does not say pytest runs them.
#: Kept as evidence because pytest does collect unittest cases, but weak, and
#: labelled so that a human confirming the oracle can see it is an assumption.
_WEAK_DIRECTORY_CONFIDENCE = 35


def _file_contains(path, markers):
    if not os.path.exists(path):
        return False
    if markers is None:
        return True
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.read()
    except OSError:
        return False
    return any(marker in content for marker in markers)


def _base_argv():
    """Prefer the console script; fall back to the module for odd PATHs."""
    if shutil.which("pytest"):
        return ["pytest", "-q"]
    return ["python3", "-m", "pytest", "-q"]


def probe(argv, cwd=None):
    """Establish that this invocation can actually start pytest.

    Detection that proposes an unrunnable oracle wastes a human's attention on
    ratifying an invocation that was never viable, and only fails at baseline
    once they have already answered questions about it. Asking the candidate
    for its version is cheap, read-only, and settles the question up front.
    """
    command = [part for part in argv if part != "-q"] + ["--version"]
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
            shell=False,
        )
    except FileNotFoundError:
        return False, "%s is not on PATH" % argv[0]
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "could not be started: %s" % exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        return False, detail[0] if detail else "exited %d" % completed.returncode
    version = (completed.stdout or completed.stderr or "").strip().splitlines()
    return True, version[0] if version else "available"


def detect(repo_root, verify=True):
    """Return candidate oracles with the evidence that produced each.

    Each candidate carries ``runnable``. A candidate that cannot start is not
    silently dropped -- the human is told pytest was recognised and why the
    invocation will not work -- but its confidence is floored so it cannot be
    presented as the detected oracle.
    """
    seen_evidence = []

    for filename, confidence, label, markers in _CONFIG_MARKERS:
        if _file_contains(os.path.join(repo_root, filename), markers):
            seen_evidence.append((confidence, label, "strong"))

    if os.path.exists(os.path.join(repo_root, "conftest.py")):
        seen_evidence.append((80, "conftest.py", "strong"))

    for directory in ("tests", "test"):
        if os.path.isdir(os.path.join(repo_root, directory)):
            seen_evidence.append(
                (_WEAK_DIRECTORY_CONFIDENCE,
                 "%s/ directory (weak: tests exist, but nothing names pytest)"
                 % directory,
                 "weak")
            )

    if not seen_evidence:
        return []

    confidence, label, strength = max(seen_evidence)
    argv = _base_argv()

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
    """Reporting flags appended at run time.

    These add a machine-readable report. They do not select, deselect, or
    otherwise change which targets run, and they are applied identically at
    baseline and at verification.
    """
    return ["--junit-xml=%s" % report_path, "-o", "junit_family=xunit2"]


_SUMMARY = re.compile(
    r"(?P<count>\d+)\s+(?P<label>passed|failed|error|errors|skipped|xfailed|xpassed|deselected)"
)


def _parse_terminal(stdout):
    counts = {}
    for match in _SUMMARY.finditer(stdout or ""):
        label = match.group("label")
        label = "error" if label == "errors" else label
        counts[label] = counts.get(label, 0) + int(match.group("count"))
    return counts


def parse(result, report_path):
    """Extract measurements, preferring the runner's own report.

    Returns ``source`` of ``"runner"`` when the JUnit report was produced, and
    ``"parsed"`` when the counts came from reading terminal output. A null
    count is a usable signal; an invented one is not.
    """
    if report_path and os.path.exists(report_path):
        try:
            tree = ElementTree.parse(report_path)
        except ElementTree.ParseError:
            tree = None
        if tree is not None:
            root = tree.getroot()
            suites = (
                [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
            )
            collected = failed = errored = skipped = 0
            failing = []
            for suite in suites:
                for case in suite.iter("testcase"):
                    collected += 1
                    identity = "%s::%s" % (
                        case.get("classname") or "",
                        case.get("name") or "",
                    )
                    identity = identity.strip(":")
                    if case.find("failure") is not None:
                        failed += 1
                        failing.append(identity)
                    elif case.find("error") is not None:
                        errored += 1
                        failing.append(identity)
                    elif case.find("skipped") is not None:
                        skipped += 1
            return {
                "source": "runner",
                "collected": collected,
                "executed": collected - skipped,
                "passed": collected - failed - errored - skipped,
                "failed": failed + errored,
                "skipped": skipped,
                "failing_targets": sorted(failing),
            }

    counts = _parse_terminal(result.get("stdout", "") + result.get("stderr", ""))
    if not counts:
        return {
            "source": "parsed",
            "collected": None,
            "executed": None,
            "passed": None,
            "failed": None,
            "skipped": None,
            "failing_targets": [],
            "note": "no JUnit report was produced and the terminal output could "
            "not be parsed; counts are unavailable rather than guessed",
        }
    passed = counts.get("passed", 0)
    failed = counts.get("failed", 0) + counts.get("error", 0)
    skipped = counts.get("skipped", 0)
    return {
        "source": "parsed",
        "collected": passed + failed + skipped,
        "executed": passed + failed,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "failing_targets": [],
        "note": "counts were read from terminal output rather than a runner "
        "report; target identities are unavailable",
    }
