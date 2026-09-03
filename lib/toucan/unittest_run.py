"""Drive stdlib unittest discovery with a machine-readable report.

`unittest` produces no report a machine can trust, so this wrapper does: same
loader, same discovery, same result semantics, plus a JSON report naming every
outcome. It exists so that unittest measurements can carry source "runner"
instead of being a language model's reading of terminal prose.
"""

import json
import time
import unittest


def _identity(test):
    return test.id()


def run(start_dir, pattern="test*.py", top_level=None, report_path=None,
        verbosity=1, stream=None):
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir, pattern=pattern, top_level_dir=top_level)

    runner = unittest.TextTestRunner(verbosity=verbosity, stream=stream)
    started = time.monotonic()
    result = runner.run(suite)
    duration = round(time.monotonic() - started, 3)

    failing = sorted(
        [_identity(test) for test, _ in result.failures]
        + [_identity(test) for test, _ in result.errors]
    )
    skipped = sorted(_identity(test) for test, _ in result.skipped)
    load_errors = [t for t in failing if "_FailedTest" in t or "LoadTests" in t]

    report = {
        "runner": "unittest",
        "collected": result.testsRun,
        "executed": result.testsRun - len(result.skipped),
        "passed": result.testsRun
        - len(result.failures)
        - len(result.errors)
        - len(result.skipped),
        "failed": len(result.failures) + len(result.errors),
        "skipped": len(result.skipped),
        "failing_targets": failing,
        "skipped_targets": skipped,
        "load_errors": load_errors,
        "duration_seconds": duration,
    }
    if report_path:
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
    return 0 if result.wasSuccessful() else 1, report
