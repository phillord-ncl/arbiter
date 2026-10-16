"""Finding things in a submission's own files.

Submissions are not laid out uniformly, so checks look for what they want
(by case-insensitive glob, anywhere under the project directory) rather
than assuming a fixed layout. Where the project directory is, is for the
Exercise's ``root`` to say, not for us to guess.
"""

import fnmatch
import os
import re

from arbiter import scripts

## Not the student's work, or not worth looking inside.
IGNORED_FILES = {".DS_Store", "Thumbs.db"}
IGNORED_DIRS = {"__MACOSX", "__pycache__"}


def _noise(name):
    return (
        name in IGNORED_FILES
        or name in IGNORED_DIRS
        or scripts.is_ours(name)
        or name.startswith("arb-results.")
    )


def walk(root):
    """Relative paths (always ``/``-separated) of the student's files:
    not hidden directories (``.git``, ``.venv``), virtualenvs, bytecode
    caches, or arbiter's own files."""
    for here, dirs, files in os.walk(root):
        dirs[:] = sorted(
            d
            for d in dirs
            if not d.startswith(".")
            and not _noise(d)
            and not os.path.exists(os.path.join(here, d, "pyvenv.cfg"))
        )
        for name in sorted(files):
            if _noise(name):
                continue
            rel = os.path.relpath(os.path.join(here, name), root)
            yield rel.replace(os.sep, "/")


def matches(rel, pattern):
    """Case-insensitive glob. A pattern with no ``/`` is matched against
    the file's own name wherever it is; with one, against the whole path.
    A leading ``/`` anchors the pattern to the project root, so
    ``/README.md`` matches only a top-level README.md."""
    rel, pattern = rel.lower(), pattern.lower()
    if pattern.startswith("/"):
        pattern = pattern[1:]
    elif "/" not in pattern:
        rel = rel.rsplit("/", 1)[-1]
    return fnmatch.fnmatchcase(rel, pattern)


def find(root, *patterns):
    """The student's files matching any of ``patterns``."""
    return [r for r in walk(root) if any(matches(r, p) for p in patterns)]


def read(root, rel, limit=2_000_000):
    """A file's text (undecodable bytes replaced), or '' if it cannot be
    read or is unreasonably big."""
    path = os.path.join(root, rel)
    try:
        if os.path.getsize(path) > limit:
            return ""
        with open(path, errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def unexpected_hidden(root, allowed=(".git", ".gitignore")):
    """Hidden files and directories (``.venv``, ``.idea``...) in ``root``
    that are not in ``allowed``."""
    return [
        n
        for n in sorted(os.listdir(root))
        if n.startswith(".") and n not in allowed and not _noise(n)
    ]


def word_count(text):
    return len(re.findall(r"\S+", text))
