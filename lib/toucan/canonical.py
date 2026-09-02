"""Canonical serialisation and hashing.

The content hash is what makes "frozen before the attempt" checkable rather
than asserted, so the bytes that get hashed must be reproducible from the
same logical document regardless of key order or formatting.
"""

import hashlib
import json


def canonical_bytes(obj):
    """Serialise to the exact bytes used as hashing input."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def content_hash(obj):
    """Return the sha256 hex digest of the canonical serialisation."""
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def pretty(obj):
    """Human-readable serialisation for files people will read."""
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
