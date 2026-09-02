"""Durable failure memory, hash-chained.

The ledger lives inside the tree the implementer can write to. The chain does
not prevent an entry being rewritten; it makes a rewrite detectable, which is
the honest guarantee available at this cost.
"""

import json
import os

from .canonical import content_hash
from .errors import Tampered
from .spec import utcnow

GENESIS = "0" * 64


def _record_hash(seq, prev_hash, entry):
    return content_hash({"seq": seq, "prev_hash": prev_hash, "entry": entry})


def read(path):
    if not os.path.exists(path):
        return []
    records = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def append(path, entry):
    """Append an entry committing to every entry before it."""
    records = read(path)
    verify(path)
    seq = len(records) + 1
    prev_hash = records[-1]["hash"] if records else GENESIS
    stamped = dict(entry)
    stamped.setdefault("recorded_at", utcnow())
    record = {
        "seq": seq,
        "prev_hash": prev_hash,
        "entry": stamped,
        "hash": _record_hash(seq, prev_hash, stamped),
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record


def verify(path):
    """Raise if any entry was rewritten, removed, or reordered."""
    records = read(path)
    expected_prev = GENESIS
    for index, record in enumerate(records, start=1):
        if record.get("seq") != index:
            raise Tampered(
                "ledger entry %d carries sequence %r; entries were reordered or "
                "removed" % (index, record.get("seq"))
            )
        if record.get("prev_hash") != expected_prev:
            raise Tampered(
                "ledger entry %d does not follow its predecessor; history was "
                "rewritten" % index
            )
        recomputed = _record_hash(index, record["prev_hash"], record["entry"])
        if recomputed != record.get("hash"):
            raise Tampered(
                "ledger entry %d does not match its own hash; its content was "
                "modified after it was written" % index
            )
        expected_prev = record["hash"]
    return len(records)
