"""The reference gate.

A judge slice's bar is fetched once, at registration, and content-hashed --
so the thing the criterion compares against provably cannot move mid-slice.
No bar, no judge slice: the refusal has the same finality as a missing
runnable oracle.
"""

import os
import urllib.error
import urllib.request

from . import artifacts
from .errors import Refusal
from .spec import utcnow

_MAX_BYTES = 10 * 1024 * 1024


def _fetch(location):
    if location.startswith(("http://", "https://")):
        try:
            with urllib.request.urlopen(location, timeout=60) as response:
                return response.read(_MAX_BYTES + 1)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise Refusal(
                "reference could not be fetched from %s: %s. A bar the judge "
                "cannot obtain would make the comparison a hallucination."
                % (location, exc)
            )
    if not os.path.isfile(location):
        raise Refusal(
            "reference does not exist: %s. A judge slice requires a named, "
            "fetchable, comparable bar; without one there is no terminal "
            "criterion, only momentum." % location
        )
    with open(location, "rb") as handle:
        return handle.read(_MAX_BYTES + 1)


def register(repo_root, slice_id, location, name):
    """Fetch the bar, hash it, and store it as a slice artifact."""
    if not name or not name.strip():
        raise Refusal("a reference must be named -- a category is not a bar")
    content = _fetch(location)
    if len(content) > _MAX_BYTES:
        raise Refusal("reference exceeds the %d MB limit" % (_MAX_BYTES // 2**20))

    staging = os.path.join(
        repo_root, ".toucan", "slices", slice_id, "reference.fetch"
    )
    os.makedirs(os.path.dirname(staging), exist_ok=True)
    with open(staging, "wb") as handle:
        handle.write(content)
    stored = artifacts.store_artifact(repo_root, slice_id, staging)
    os.remove(staging)

    return {
        "name": name,
        "location": location,
        "content_hash": stored["sha256"],
        "artifact_path": stored["artifact_path"],
        "fetched_at": utcnow(),
    }
