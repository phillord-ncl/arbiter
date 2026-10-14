"""Mechanical checks on a submission's files and git history.

Each check returns ``(ok, message)``: ``ok`` true if it passed, and
``message`` says what it found, whichever way it went. ``DirectoryMarker``
turns one into a scoring step -- pass scores full marks; anything else is
*undecided*, so it scores nothing unless an ``or_else()`` step (usually a
human question) follows, which is shown the message. None of them ever
award a zero on their own judgement that a person might overturn.
"""

import os
import re
import subprocess

from arbiter import submission


def file_exists(root, patterns):
    found = submission.find(root, *patterns)
    if found:
        return True, "found {}".format(", ".join(found))
    return False, "no file matching {}".format(" or ".join(patterns))


def file_contains(root, patterns, regexp):
    """True if a file matching ``patterns`` has text matching ``regexp``
    (case-insensitive)."""
    files = submission.find(root, *patterns)
    if not files:
        return False, "no file matching {}".format(" or ".join(patterns))
    for rel in files:
        if re.search(regexp, submission.read(root, rel), re.IGNORECASE | re.MULTILINE):
            return True, "{} matches /{}/".format(rel, regexp)
    return False, "{} does not match /{}/".format(", ".join(files), regexp)


def files_match(root, patterns, regexp):
    """True if any file matching ``patterns`` has a line matching ``regexp``."""
    files = submission.find(root, *patterns)
    for rel in files:
        if re.search(regexp, submission.read(root, rel), re.MULTILINE):
            return True, "{} matches /{}/".format(rel, regexp)
    return False, "no line matches /{}/ in {} file(s) matching {}".format(
        regexp, len(files), " or ".join(patterns)
    )


def word_count(root, patterns, low, high, tolerance):
    files = submission.find(root, *patterns)
    if not files:
        return False, "no file matching {}".format(" or ".join(patterns))
    count = sum(submission.word_count(submission.read(root, r)) for r in files)
    wanted = "{} to {}".format(low, high)
    if tolerance:
        wanted += " (+/- {:g}%)".format(tolerance * 100)
    message = "{} has {} words, wanted {}".format(", ".join(files), count, wanted)
    return low * (1 - tolerance) <= count <= high * (1 + tolerance), message


def _git(root, *args):
    """``(returncode, stdout)`` of git run in ``root``, or None if there is
    no git or it could not be run. Never looks above ``root`` for a
    repository."""
    env = dict(os.environ, GIT_CEILING_DIRECTORIES=os.path.dirname(os.path.abspath(root)))
    try:
        run = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            text=True,
            errors="replace",
            env=env,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return run.returncode, run.stdout


def has_git(root):
    return os.path.exists(os.path.join(root, ".git"))


def git_commit_count(root, at_least):
    if not has_git(root):
        return False, "no .git directory"
    result = _git(root, "rev-list", "--count", "--all")
    if result is None or result[0] != 0:
        return False, "could not read the git history"
    count = int(result[1].strip() or 0)
    return count >= at_least, "{} commit(s), wanted at least {}".format(count, at_least)


def git_log_matches(root, regexp, messages, diffs):
    """True if any commit's message and/or changed lines match ``regexp``
    (case-insensitive extended regexp, as git understands it)."""
    if not has_git(root):
        return False, "no .git directory"
    where = []
    if messages:
        where.append(("--grep=" + regexp, "message"))
    if diffs:
        where.append(("-G" + regexp, "diff"))
    for option, what in where:
        result = _git(
            root, "log", "--all", "--regexp-ignore-case", "-E", "--format=%h", option
        )
        if result is None or result[0] != 0:
            return False, "could not read the git history"
        if result[1].strip():
            return True, "commit {} {} matches /{}/".format(
                result[1].split()[0], what, regexp
            )
    return False, "no commit {} matches /{}/".format(
        " or ".join(what for _, what in where), regexp
    )
