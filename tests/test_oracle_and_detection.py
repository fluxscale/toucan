"""Detection, argument-array safety, and protected-path defaults."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from support import RepoCase  # noqa: E402
from toucan import adapters  # noqa: E402
from toucan.oracle import SHELL_CONSTRUCTS, argv_objection  # noqa: E402


class DetectionTest(RepoCase):
    def test_detects_a_single_unambiguous_runner(self):
        candidates = adapters.detect_all(self.repo)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["adapter"], "pytest")
        self.assertTrue(candidates[0]["evidence"])

    def test_detection_names_its_evidence(self):
        candidate = adapters.detect_all(self.repo)[0]
        self.assertIn(candidate["evidence"], ("pytest.ini", "tests/ directory",
                                              "conftest.py", "tox.ini",
                                              "setup.cfg"))

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
        self.assertEqual(len(candidates), 2)
        self.assertEqual({c["adapter"] for c in candidates}, {"pytest", "rival"})

    def test_candidates_are_ordered_by_confidence(self):
        candidates = adapters.detect_all(self.repo)
        confidences = [c["confidence"] for c in candidates]
        self.assertEqual(confidences, sorted(confidences, reverse=True))

    def test_each_candidate_names_its_own_evidence(self):
        for candidate in adapters.detect_all(self.repo):
            with self.subTest(adapter=candidate["adapter"]):
                self.assertTrue(candidate["evidence"])
