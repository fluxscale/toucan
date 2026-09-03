"""Detection, argument-array safety, and protected-path defaults."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from support import RepoCase  # noqa: E402
from toucan import adapters  # noqa: E402
from toucan.oracle import SHELL_CONSTRUCTS, argv_objection  # noqa: E402


def _by_adapter(candidates, name):
    matches = [c for c in candidates if c["adapter"] == name]
    assert len(matches) == 1, "expected exactly one %s candidate" % name
    return matches[0]


class DetectionTest(RepoCase):
    def test_detects_exactly_one_pytest_candidate(self):
        candidates = adapters.detect_all(self.repo)
        candidate = _by_adapter(candidates, "pytest")
        self.assertTrue(candidate["evidence"])

    def test_detection_names_its_evidence(self):
        candidate = _by_adapter(adapters.detect_all(self.repo), "pytest")
        self.assertIn("pytest.ini", candidate["evidence"])

    def test_reports_nothing_when_no_runner_is_present(self):
        empty = os.path.join(self.repo, "empty")
        os.makedirs(empty)
        self.assertEqual(adapters.detect_all(empty), [])

    def test_protected_paths_cover_tests_and_ci(self):
        paths = adapters.get("pytest").protected_paths(self.repo)
        self.assertIn("tests/**", paths)
        self.assertIn("**/conftest.py", paths)
        self.assertIn(".github/workflows/**", paths)

    def test_unknown_adapter_is_refused(self):
        with self.assertRaises(KeyError):
            adapters.get("nonexistent")


class ArgvSafetyTest(RepoCase):
    def test_accepts_a_plain_argument_array(self):
        self.assertIsNone(argv_objection(["pytest", "-q", "tests/test_a.py"]))

    def test_rejects_every_shell_construct(self):
        for construct in SHELL_CONSTRUCTS:
            with self.subTest(construct=construct):
                objection = argv_objection(["pytest", "-q" + construct])
                self.assertIsNotNone(objection)
                self.assertIn("shell", objection)

    def test_rejects_an_empty_array(self):
        self.assertIsNotNone(argv_objection([]))


class AmbiguousDetectionTest(RepoCase):
    """Detection must surface competition rather than resolve it silently."""

    def setUp(self):
        super().setUp()
        self._original = dict(adapters.ADAPTERS)

        class Rival:
            NAME = "rival"

            @staticmethod
            def detect(repo_root):
                return [{
                    "adapter": "rival",
                    "argv": ["rival-runner"],
                    "cwd": ".",
                    "timeout_seconds": 600,
                    "confidence": 90,
                    "evidence": "rival.toml",
                    "execution_evidence": "rival report",
                }]

            @staticmethod
            def protected_paths(repo_root=None):
                return ["spec/**"]

        adapters.ADAPTERS["rival"] = Rival
        self.addCleanup(self._restore)

    def _restore(self):
        adapters.ADAPTERS.clear()
        adapters.ADAPTERS.update(self._original)

    def test_competing_runners_both_surface(self):
        candidates = adapters.detect_all(self.repo)
        names = {c["adapter"] for c in candidates}
        self.assertIn("pytest", names)
        self.assertIn("rival", names)

    def test_candidates_are_ordered_by_confidence(self):
        candidates = adapters.detect_all(self.repo)
        confidences = [c["confidence"] for c in candidates]
        self.assertEqual(confidences, sorted(confidences, reverse=True))

    def test_each_candidate_names_its_own_evidence(self):
        for candidate in adapters.detect_all(self.repo):
            with self.subTest(adapter=candidate["adapter"]):
                self.assertTrue(candidate["evidence"])


class RunnabilityTest(RepoCase):
    """Recognising a runner is not the same as being able to run it."""

    def test_probe_reports_a_missing_command(self):
        from toucan.adapters import pytest_adapter

        runnable, detail = pytest_adapter.probe(["definitely-not-real-xyz"])
        self.assertFalse(runnable)
        self.assertIn("PATH", detail)

    def test_probe_reports_a_command_that_exits_non_zero(self):
        import sys as _sys
        from toucan.adapters import pytest_adapter

        runnable, _ = pytest_adapter.probe([_sys.executable, "-m", "nonexistent_mod"])
        self.assertFalse(runnable)

    def test_unrunnable_candidate_is_marked_and_floored(self):
        from toucan.adapters import pytest_adapter

        original = pytest_adapter._base_argv
        pytest_adapter._base_argv = lambda: ["definitely-not-real-xyz", "-q"]
        try:
            candidate = pytest_adapter.detect(self.repo)[0]
        finally:
            pytest_adapter._base_argv = original
        self.assertFalse(candidate["runnable"])
        self.assertLessEqual(candidate["confidence"], 5)
        self.assertIn("PATH", candidate["runnable_detail"])

    def test_unrunnable_candidates_sort_last(self):
        candidates = [
            {"adapter": "a", "confidence": 95, "runnable": False},
            {"adapter": "b", "confidence": 20, "runnable": True},
        ]
        ordered = sorted(
            candidates, key=lambda c: (not c.get("runnable", True), -c["confidence"])
        )
        self.assertEqual(ordered[0]["adapter"], "b")

    def test_verify_can_be_skipped(self):
        from toucan.adapters import pytest_adapter

        candidate = pytest_adapter.detect(self.repo, verify=False)[0]
        self.assertTrue(candidate["runnable"])
        self.assertEqual(candidate["runnable_detail"], "not verified")


class EvidenceStrengthTest(RepoCase):
    """A test directory is weak evidence; a config naming pytest is strong."""

    def _pytest(self):
        return _by_adapter(adapters.detect_all(self.repo), "pytest")

    def test_pytest_ini_is_strong_evidence(self):
        candidate = self._pytest()
        self.assertEqual(candidate["evidence_strength"], "strong")
        self.assertIn("pytest.ini", candidate["evidence"])

    def test_bare_test_directory_is_weak_evidence(self):
        os.remove(os.path.join(self.repo, "pytest.ini"))
        candidate = self._pytest()
        self.assertEqual(candidate["evidence_strength"], "weak")
        self.assertIn("weak", candidate["evidence"])

    def test_config_file_not_naming_pytest_is_not_evidence(self):
        os.remove(os.path.join(self.repo, "pytest.ini"))
        with open(os.path.join(self.repo, "tox.ini"), "w") as handle:
            handle.write("[testenv]\ncommands = nosetests\n")
        self.assertEqual(self._pytest()["evidence_strength"], "weak")

    def test_config_file_naming_pytest_is_strong_evidence(self):
        os.remove(os.path.join(self.repo, "pytest.ini"))
        with open(os.path.join(self.repo, "tox.ini"), "w") as handle:
            handle.write("[pytest]\naddopts = -q\n")
        self.assertEqual(self._pytest()["evidence_strength"], "strong")

    def test_pyproject_without_a_pytest_section_is_not_evidence(self):
        os.remove(os.path.join(self.repo, "pytest.ini"))
        with open(os.path.join(self.repo, "pyproject.toml"), "w") as handle:
            handle.write("[project]\nname = 'demo'\n")
        self.assertEqual(self._pytest()["evidence_strength"], "weak")
