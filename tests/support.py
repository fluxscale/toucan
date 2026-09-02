"""Fixture helpers: throwaway git repositories with a real pytest suite."""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))

from toucan import spec as spec_mod  # noqa: E402

PASSING_SUITE = '''
def test_one():
    assert 1 == 1


def test_two():
    assert 2 == 2
'''

FAILING_SUITE = '''
def test_one():
    assert 1 == 1


def test_two():
    assert 2 == 2


def test_broken():
    assert 1 == 2


def test_also_broken():
    raise ValueError("boom")
'''


def git(cwd, *args):
    return subprocess.run(
        ["git"] + list(args), cwd=cwd, capture_output=True, text=True, check=True
    )


class RepoCase(unittest.TestCase):
    """Base case providing a temporary git repository."""

    suite_source = FAILING_SUITE

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="toucan-test-")
        self.repo = self._tmp.name
        os.makedirs(os.path.join(self.repo, "tests"), exist_ok=True)
        with open(os.path.join(self.repo, "tests", "test_sample.py"), "w") as handle:
            handle.write(self.suite_source)
        with open(os.path.join(self.repo, "pytest.ini"), "w") as handle:
            handle.write("[pytest]\n")
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "fixture")
        self.addCleanup(self._tmp.cleanup)

    def oracle(self, timeout=120, argv=None):
        return {
            "argv": argv or [sys.executable, "-m", "pytest", "-q"],
            "cwd": ".",
            "timeout_seconds": timeout,
            "adapter": "pytest",
            "execution_evidence": "JUnit XML report listing each test case.",
        }

    def complete_draft(self, slice_id="demo", intent="fix the broken tests"):
        """A draft with every required field ratified, ready for a baseline."""
        from toucan import store

        document = spec_mod.new_spec(slice_id, intent)
        spec_mod.set_field(document, "oracle", self.oracle(), spec_mod.DETECTED,
                           "pytest.ini")
        spec_mod.set_field(document, "criterion", "all tests pass with no skips",
                           spec_mod.YOURS, "stated by human")
        spec_mod.set_field(document, "protected_paths", ["tests/**"],
                           spec_mod.DETECTED, "pytest defaults")
        spec_mod.set_field(document, "approved_oracle_changes", [], spec_mod.YOURS,
                           "none requested")
        spec_mod.set_field(document, "required_runs", 1, spec_mod.YOURS, "chosen")
        spec_mod.set_field(document, "allow_skips", False, spec_mod.YOURS, "chosen")
        spec_mod.set_field(document, "iteration_maximum", 5, spec_mod.YOURS, "chosen")
        store.save_draft(self.repo, document)
        return document
