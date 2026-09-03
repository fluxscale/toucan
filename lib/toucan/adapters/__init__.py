"""Ecosystem adapters.

An adapter knows three things a generic runner cannot: how to recognise its
runner in a repository, how to obtain counts the runner itself produced rather
than counts parsed out of prose, and what positively demonstrates that the
registered targets actually executed.

Coverage outside the registered adapters is deliberately absent rather than
approximated. Detection that guesses would produce a specification that looks
identical to a sound one.
"""

from . import pytest_adapter, unittest_adapter

ADAPTERS = {
    pytest_adapter.NAME: pytest_adapter,
    unittest_adapter.NAME: unittest_adapter,
}


def get(name):
    if name not in ADAPTERS:
        raise KeyError(
            "no adapter named %r; registered adapters: %s"
            % (name, ", ".join(sorted(ADAPTERS)))
        )
    return ADAPTERS[name]


def detect_all(repo_root):
    """Every candidate oracle any adapter recognises, best evidence first.

    A candidate that cannot be started sorts last regardless of how strong its
    evidence was. Recognising a runner is not the same as being able to run it,
    and only the second one makes an oracle.
    """
    candidates = []
    for adapter in ADAPTERS.values():
        candidates.extend(adapter.detect(repo_root))
    candidates.sort(key=lambda c: (not c.get("runnable", True), -c["confidence"]))
    return candidates


def runnable(candidates):
    return [c for c in candidates if c.get("runnable", True)]
