"""Oracle execution.

The oracle is an argument array executed without a shell. This is not a
stylistic preference: a shell string is an injection surface in a document
assembled partly from repository content, and the whole point of the artifact
is that it does exactly one thing that a later reader can verify.
"""

import subprocess
import time

#: Characters that only have meaning to a shell. Their presence means the
#: value was written expecting shell interpretation, which is precisely what
#: will not happen -- so the value is wrong even when it looks right.
SHELL_CONSTRUCTS = (";", "|", "&", "`", "$(", ">", "<", "\n", "\r", "&&", "||")


def argv_objection(argv):
    """Return why ``argv`` is unusable as an argument array, or None."""
    if not argv:
        return "must not be empty"
    for element in argv:
        for construct in SHELL_CONSTRUCTS:
            if construct in element:
                return (
                    "must not contain shell constructs; found %r in %r. Express "
                    "the invocation as separate arguments instead."
                    % (construct, element)
                )
    return None


class ExecutionFailure(Exception):
    """The oracle could not be executed, as distinct from failing."""

    def __init__(self, reason, detail=None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def run(argv, cwd, timeout_seconds, extra_args=()):
    """Execute the oracle without a shell and return the raw result.

    ``extra_args`` carries adapter reporting flags appended at run time. They
    are applied identically at baseline and at verification, and they only add
    reporting -- they never change which targets run.
    """
    objection = argv_objection(list(argv))
    if objection:
        raise ExecutionFailure("oracle.argv %s" % objection)

    command = list(argv) + list(extra_args)
    if command[0] == "toucan":
        import os as _os
        import sys as _sys

        _entry = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.dirname(
                _os.path.abspath(__file__)))), "bin", "toucan")
        command[0:1] = [_sys.executable, _entry]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
    except FileNotFoundError:
        raise ExecutionFailure(
            "oracle command not found: %r" % command[0],
            "The invocation could not be started. Toucan does not install "
            "dependencies; supply an invocation that runs in this tree as it "
            "stands.",
        )
    except PermissionError as exc:
        raise ExecutionFailure("oracle command is not executable: %s" % exc)
    except subprocess.TimeoutExpired:
        raise ExecutionFailure(
            "oracle exceeded its %ds timeout" % timeout_seconds,
            "A timeout is not a failing criterion; it is an unusable oracle. "
            "Raise the timeout or narrow the invocation.",
        )

    return {
        "argv": command,
        "cwd": cwd,
        "exit_status": completed.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "timed_out": False,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
