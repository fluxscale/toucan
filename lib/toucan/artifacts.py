"""Content-addressed artifact storage under .toucan/.

The pair a judge compared must be provable after the fact, so artifacts are
stored by the hash of their bytes and referenced by it everywhere.
"""

import hashlib
import os
import shutil

from .errors import Refusal


def artifacts_dir(repo_root, slice_id):
    return os.path.join(repo_root, ".toucan", "slices", slice_id, "artifacts")


def store_artifact(repo_root, slice_id, path):
    """Store a copy of ``path`` addressed by its content hash."""
    if not os.path.isfile(path):
        raise Refusal("artifact does not exist or is not a file: %s" % path)
    with open(path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    directory = artifacts_dir(repo_root, slice_id)
    os.makedirs(directory, exist_ok=True)
    stored_path = os.path.join(directory, digest)
    if not os.path.exists(stored_path):
        shutil.copyfile(path, stored_path)
    return {
        "sha256": digest,
        "stored_path": stored_path,
        "artifact_path": os.path.relpath(stored_path, repo_root),
    }


def verify_artifact(repo_root, artifact_path, expected_hash):
    """Prove stored bytes still match the recorded hash."""
    path = os.path.join(repo_root, artifact_path)
    if not os.path.exists(path):
        return False, "artifact missing: %s" % artifact_path
    with open(path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    if digest != expected_hash:
        return False, "artifact %s does not match its recorded hash" % artifact_path
    return True, digest
