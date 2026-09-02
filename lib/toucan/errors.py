"""Error types. Every refusal is an explicit, named condition."""


class ToucanError(Exception):
    """Base for every refusal Toucan makes deliberately."""

    exit_code = 1


class Refusal(ToucanError):
    """An operation was refused because a precondition was not met.

    Refusals are the mechanism by which ordering is enforced. They are not
    bugs and they are not recoverable by retrying the same call.
    """

    exit_code = 2


class NotFound(ToucanError):
    exit_code = 3


class Tampered(ToucanError):
    """Recorded content no longer matches its recorded hash."""

    exit_code = 4


class UnsupportedEnvironment(ToucanError):
    exit_code = 5
