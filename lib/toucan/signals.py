"""Repository signals available for inferring intent.

Registration may draft a criterion from facts about the tree. It may not draft
one from the conversation, because the moment someone reaches for Toucan is
usually the moment the conversation is most contaminated by failed attempts.
When no repository signal exists, the correct behaviour is to ask.
"""

import os
import subprocess


def _git(repo_root, *args):
    try:
        completed = subprocess.run(
            ["git"] + list(args),
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def head_sha(repo_root):
    return _git(repo_root, "rev-parse", "HEAD")


def branch(repo_root):
    name = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    return None if name in (None, "HEAD") else name


def working_tree_changes(repo_root):
    """Every change from HEAD including untracked files.

    Untracked files are included because a new conftest.py is the most
    convenient place to put an oracle override, and a diff that omits them
    misses it entirely.
    """
    output = _git(repo_root, "status", "--porcelain=v1", "--untracked-files=all")
    if not output:
        return []
    return [line[3:] for line in output.splitlines() if len(line) > 3]


def recent_subjects(repo_root, count=5):
    output = _git(repo_root, "log", "--oneline", "-n", str(count), "--format=%s")
    return output.splitlines() if output else []


def collect(repo_root):
    """Signals that exist independently of any conversation."""
    changes = working_tree_changes(repo_root)
    return {
        "is_git_repo": os.path.isdir(os.path.join(repo_root, ".git")),
        "head_sha": head_sha(repo_root),
        "branch": branch(repo_root),
        "working_tree_changes": changes,
        "working_tree_dirty": bool(changes),
        "recent_commit_subjects": recent_subjects(repo_root),
    }


def independent_signal_present(signals, baseline=None):
    """Whether anything other than the transcript indicates intended work.

    A failing baseline is the strongest signal there is: it is a fact about the
    tree rather than an opinion about it.
    """
    if baseline and baseline.get("measurements", {}).get("failed"):
        return True
    if signals.get("working_tree_dirty"):
        return True
    name = signals.get("branch")
    if name and name not in ("main", "master", "develop", "trunk"):
        return True
    return False
