"""User-level configuration -- see ../plans/tui.md.

``config.toml`` in the platform's per-user config directory. Today it only
says how to view a submission's files::

    [viewer]
    open = "emacsclient -n {file}"
    close = "..."          # optional

With no config (or no ``[viewer]``) the viewer is VS Code on Windows if it
is installed (see ``default_viewer``); otherwise there is no external viewer
and the UI shows files itself. ``[terminal]`` says how to open a terminal in a
submission::

    [terminal]
    open = "kitty --directory {dir}"

With none, a platform default is guessed (see terminal.py).
"""

import os
import shlex
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from typing import Optional

import click


class ConfigError(Exception):
    pass


def default_path():
    return os.path.join(click.get_app_dir("arbiter"), "config.toml")


def _command(template):
    return shlex.split(template, posix=os.name != "nt")


@dataclass
class Viewer:
    """Shell-free commands to open and (optionally) close a file; ``{file}``
    in a command is replaced by the file's path, whatever it contains."""

    open: str
    close: Optional[str] = None
    ## Files opened and not yet closed, so a student's can be closed at the end.
    opened: list = field(default_factory=list, repr=False, compare=False)

    def _run(self, template, path):
        args = [a.replace("{file}", path) for a in _command(template)]
        subprocess.run(args, check=False, stdout=subprocess.DEVNULL)

    def open_file(self, path):
        self._run(self.open, path)
        if path not in self.opened:
            self.opened.append(path)

    def close_file(self, path):
        if self.close is not None:
            self._run(self.close, path)
        if path in self.opened:
            self.opened.remove(path)

    def close_all(self):
        """Close every file opened since the last time (if there is a close
        command)."""
        for path in list(self.opened):
            self.close_file(path)
        self.opened.clear()


def load_viewer(path=None):
    """The configured ``Viewer``, or None if there is none."""
    path = path or default_path()
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError("{}: {}".format(path, e)) from None
    viewer = data.get("viewer")
    if viewer is None:
        return None
    if "open" not in viewer:
        raise ConfigError("{}: [viewer] needs an 'open' command".format(path))
    return Viewer(viewer["open"], viewer.get("close"))


def default_viewer(platform=None, which=shutil.which):
    """The viewer to use when none is configured: VS Code on Windows, if
    it is on the PATH. Elsewhere, or without it, None."""
    platform = platform or sys.platform
    if platform.startswith("win") and which("code.cmd"):
        return Viewer("code.cmd --reuse-window {file}")
    return None


def load_terminal(path=None):
    """The configured terminal command line (a string), or None."""
    path = path or default_path()
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError("{}: {}".format(path, e)) from None
    terminal = data.get("terminal")
    if terminal is None:
        return None
    if "open" not in terminal:
        raise ConfigError("{}: [terminal] needs an 'open' command".format(path))
    return terminal["open"]
