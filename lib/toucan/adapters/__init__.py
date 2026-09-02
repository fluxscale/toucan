"""Ecosystem adapters.

An adapter knows three things a generic runner cannot: how to recognise its
runner in a repository, how to obtain counts the runner itself produced rather
than counts parsed out of prose, and what positively demonstrates that the
registered targets actually executed.

Coverage outside the registered adapters is deliberately absent rather than
approximated. Detection that guesses would produce a specification that looks
identical to a sound one.
"""

from . import pytest_adapter

ADAPTERS = {
    pytest_adapter.NAME: pytest_adapter,
}


def get(name):
    if name not in ADAPTERS:
        raise KeyError(
            "no adapter named %r; registered adapters: %s"
            % (name, ", ".join(sorted(ADAPTERS)))
        )
    return ADAPTERS[name]


def detect_all(repo_root):
    """Every candidate oracle any adapter recognises, best evidence first."""
    candidates = []
    for adapter in ADAPTERS.values():
        candidates.extend(adapter.detect(repo_root))
    candidates.sort(key=lambda c: -c["confidence"])
    return candidates
