"""User-level configuration -- see ../plans/tui.md.

``config.toml`` in the platform's per-user config directory. Today it only
says how to view a submission's files::

    [viewer]
    open = "emacsclient -n {file}"
    close = "..."          # optional

With no config (or no ``[viewer]``) there is no external viewer and the UI
shows files itself.
"""

import os
import shlex
import subprocess
import tomllib
from dataclasses import dataclass
from typing import Optional

import click


class ConfigError(Exception):
    pass


def default_path():
    return os.path.join(click.get_app_dir("tent-arbiter"), "config.toml")


def _command(template):
    return shlex.split(template, posix=os.name != "nt")


@dataclass
class Viewer:
    """Shell-free commands to open and (optionally) close a file; ``{file}``
    in a command is replaced by the file's path, whatever it contains."""

    open: str
    close: Optional[str] = None

    def _run(self, template, path):
        args = [a.replace("{file}", path) for a in _command(template)]
        subprocess.run(args, check=False, stdout=subprocess.DEVNULL)

    def open_file(self, path):
        self._run(self.open, path)

    def close_file(self, path):
        if self.close is not None:
            self._run(self.close, path)


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
