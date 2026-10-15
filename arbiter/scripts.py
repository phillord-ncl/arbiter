"""Wrapper scripts that run things in a per-submission venv.

arbiter writes a few small scripts into the submission directory; a marker
opens a terminal there and types ``marker-python ...``. Each script makes
``marker-venv`` if it is missing, installs ``requirements.txt`` if there is
one (both near no-ops once done), then runs its command with the venv's own
interpreter, so nothing needs activating and any shell will do. The venv is
named ``marker-venv`` rather than ``.venv`` so it cannot be mistaken for one
the student submitted. Scripts are POSIX ``sh`` or Windows ``.cmd``.
"""

import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import List, Optional

VENV = "marker-venv"
TAG = "arbiter-generated"


class ScriptClash(Exception):
    """Something we would write already exists and is not ours."""


@dataclass
class Script:
    name: str
    ## Run in the venv; the first word is looked up in the venv's own
    ## scripts directory, so ``["python", "app.py"]`` runs the venv python.
    command: List[str]
    ## With no arguments, only set the venv up (``marker-pip`` is a pre-warm).
    bare_is_bootstrap: bool = False


BUILTIN = [
    Script("marker-python", ["python"]),
    Script("marker-pip", ["pip"], bare_is_bootstrap=True),
]


def is_windows():
    return os.name == "nt"


def interpreter(python_version=None, windows=None):
    """The command that makes a venv: ``python3`` / ``py -3``, or for a
    version, ``python3.14`` / ``py -3.14``. The Windows script falls back to
    plain ``python`` when there is no ``py`` launcher."""
    windows = is_windows() if windows is None else windows
    if windows:
        return ["py", "-" + (python_version or "3")]
    return ["python" + (python_version or "3")]


def filename(name, windows=None):
    windows = is_windows() if windows is None else windows
    return name + ".cmd" if windows else name


def script_path(directory, name, windows=None):
    return os.path.join(directory, filename(name, windows))


def render(script, python_version=None, windows=None):
    windows = is_windows() if windows is None else windows
    make = interpreter(python_version, windows)
    word, *rest = script.command
    if windows:
        bin_dir = VENV + "\\Scripts\\"
        py = bin_dir + "python.exe"
        run = bin_dir + word + ".exe"
        lines = [
            "@echo off",
            "rem {}: {}".format(TAG, script.name),
            'cd /d "%~dp0"',
            "if not exist {} (".format(py),
            "    where py >nul 2>nul",
            "    if errorlevel 1 (",
            "        python -m venv {}".format(VENV),
            "    ) else (",
            "        {} -m venv {}".format(subprocess.list2cmdline(make), VENV),
            "    )",
            "    if errorlevel 1 exit /b 1",
            ")",
            "if exist requirements.txt (",
            "    {} -m pip install -q -r requirements.txt".format(py),
            "    if errorlevel 1 exit /b 1",
            ")",
        ]
        call = subprocess.list2cmdline([run, *rest]) + " %*"
        if script.bare_is_bootstrap:
            lines += ["if not \"%~1\"==\"\" {}".format(call), "exit /b 0"]
        else:
            lines.append(call)
        return "\r\n".join(lines) + "\r\n"
    run = "{}/bin/{}".format(VENV, word)
    lines = [
        "#!/bin/sh",
        "# {}: {}".format(TAG, script.name),
        "set -e",
        'cd "$(dirname "$0")"',
        "if [ ! -x {}/bin/python ]; then".format(VENV),
        "    {} -m venv {}".format(" ".join(shlex.quote(w) for w in make), VENV),
        "fi",
        "if [ -f requirements.txt ]; then",
        "    {}/bin/python -m pip install -q -r requirements.txt".format(VENV),
        "fi",
    ]
    call = "exec " + " ".join(shlex.quote(w) for w in [run, *rest]) + ' "$@"'
    if script.bare_is_bootstrap:
        lines += ["if [ $# -gt 0 ]; then", "    " + call, "fi"]
    else:
        lines.append(call)
    return "\n".join(lines) + "\n"


def _ours(path):
    try:
        with open(path, errors="replace") as f:
            return any(TAG in line for line in [f.readline() for _ in range(3)])
    except OSError:
        return False


def clashes(directory, scripts, windows=None):
    """Paths in ``directory`` that exist and are not arbiter's own."""
    found = []
    for script in scripts:
        path = script_path(directory, script.name, windows)
        if os.path.lexists(path) and not _ours(path):
            found.append(path)
    venv = os.path.join(directory, VENV)
    if os.path.lexists(venv) and not os.path.exists(os.path.join(venv, "pyvenv.cfg")):
        found.append(venv)
    return found


def write_scripts(directory, scripts, python_version=None, windows=None):
    """Write ``scripts`` into ``directory`` and return their paths. Raises
    ``ScriptClash`` and writes nothing if any name is already taken by
    something that is not ours."""
    found = clashes(directory, scripts, windows)
    if found:
        raise ScriptClash(
            "cannot write marker scripts, these already exist and are not "
            "arbiter's: " + ", ".join(found)
        )
    paths = []
    for script in scripts:
        path = script_path(directory, script.name, windows)
        with open(path, "w", newline="") as f:
            f.write(render(script, python_version, windows))
        os.chmod(path, 0o755)
        paths.append(path)
    return paths


def is_ours(name):
    """True for a name arbiter creates in a submission, which listings of
    the student's own files should skip."""
    return name == VENV or name.startswith("marker-")
