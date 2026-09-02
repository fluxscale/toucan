"""pytest adapter.

Counts come from a JUnit XML report the runner writes itself, not from parsing
the terminal summary. The distinction is the difference between a measurement
and a language model's reading of one, and the critic's output contract
requires the difference be reported honestly.
"""

import os
import re
import shutil
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

_CONFIG_MARKERS = (
    ("pytest.ini", 95, "pytest.ini"),
    ("tox.ini", 60, "tox.ini"),
    ("setup.cfg", 60, "setup.cfg"),
)


def _pyproject_declares_pytest(repo_root):
    path = os.path.join(repo_root, "pyproject.toml")
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return "[tool.pytest" in handle.read()
    except OSError:
        return False


def _base_argv():
    """Prefer the console script; fall back to the module for odd PATHs."""
    if shutil.which("pytest"):
        return ["pytest", "-q"]
    return ["python3", "-m", "pytest", "-q"]


def detect(repo_root):
    """Return candidate oracles with the evidence that produced each."""
    candidates = []
    seen_evidence = []

    for filename, confidence, label in _CONFIG_MARKERS:
        if os.path.exists(os.path.join(repo_root, filename)):
            seen_evidence.append((confidence, label))

    if _pyproject_declares_pytest(repo_root):
        seen_evidence.append((95, "pyproject.toml [tool.pytest.ini_options]"))

    for directory in ("tests", "test"):
        if os.path.isdir(os.path.join(repo_root, directory)):
            seen_evidence.append((70, "%s/ directory" % directory))

    if os.path.exists(os.path.join(repo_root, "conftest.py")):
        seen_evidence.append((80, "conftest.py"))

    if not seen_evidence:
        return []

    confidence, label = max(seen_evidence)
    candidates.append(
        {
            "adapter": NAME,
            "argv": _base_argv(),
            "cwd": ".",
            "timeout_seconds": 900,
            "confidence": confidence,
            "evidence": label,
            "execution_evidence": EXECUTION_EVIDENCE,
        }
    )
    return candidates


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
