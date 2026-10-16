"""User-level configuration -- see ../plans/tui.md.

``config.toml`` in the platform's per-user config directory. Today it only
says how to view a submission's files::

    [viewer]
    open = "emacsclient -n {file}"
    close = "..."          # optional
    close_dir = "..."      # optional: close everything under {dir}

With no config (or no ``[viewer]``) the viewer is VS Code on Windows if it
is installed (see ``default_viewer``); otherwise there is no external viewer
and the UI shows files itself. ``[terminal]`` says how to open a terminal in a
submission::

    [terminal]
    open = "kitty --directory {dir}"

With none, a platform default is guessed (see terminal.py).
"""

import json
import os
import re
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
    close_dir: Optional[str] = None
    ## Start ``open`` without waiting for it to exit, for programs (a plain
    ## ``emacs``) that stay running as the viewer itself.
    detach: bool = False
    ## Files opened and not yet closed, so a student's can be closed at the end.
    opened: list = field(default_factory=list, repr=False, compare=False)

    def _run(self, template, path, key="{file}", detach=False):
        args = [a.replace(key, path) for a in _command(template)]
        if detach:
            subprocess.Popen(
                args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        else:
            subprocess.run(args, check=False, stdout=subprocess.DEVNULL)

    def open_file(self, path):
        self._run(self.open, path, detach=self.detach)
        if path not in self.opened:
            self.opened.append(path)

    def close_file(self, path):
        if self.close is not None:
            self._run(self.close, path)
        if path in self.opened:
            self.opened.remove(path)

    def close_all(self, directory=None):
        """Close the student's files: everything under ``directory`` if
        there is a ``close_dir`` command, which also catches files opened
        outside arbiter; otherwise those arbiter opened, if there is a
        ``close`` command."""
        if self.close_dir is not None and directory is not None:
            self._run(self.close_dir, os.path.abspath(directory), "{dir}")
            self.opened.clear()
            return
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
    return Viewer(
        viewer["open"],
        viewer.get("close"),
        viewer.get("close_dir"),
        bool(viewer.get("detach", False)),
    )


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


_EMACS_CLOSE = (
    "emacsclient --eval '(let ((b (find-buffer-visiting \"{file}\"))) "
    "(when b (kill-buffer b)))'"
)
_EMACS_CLOSE_DIR = (
    "emacsclient --eval '(dolist (b (buffer-list)) "
    "(let ((f (buffer-file-name b))) (when (and f "
    "(string-prefix-p \"{dir}/\" f) (not (buffer-modified-p b))) "
    "(kill-buffer b))))'"
)

## Viewer choices offered by the TUI's "Configure viewer", in menu order.
VIEWER_CHOICES = ("emacsclient", "emacs", "vscode", "pycharm")

VIEWER_LABELS = {
    "emacsclient": "Emacsclient (uses your running Emacs server)",
    "emacs": "Emacs (starts Emacs for the files)",
    "vscode": "Visual Studio Code",
    "pycharm": "PyCharm",
}


def preset_viewer(name, platform=None):
    """The ``Viewer`` for one of ``VIEWER_CHOICES`` on ``platform``.

    Commands are shell-free, so the Windows launchers are the ``.cmd`` or
    ``.exe`` names; Emacs's close commands quote with single quotes, which
    Windows splitting would not strip, so Windows Emacs gets no close."""
    platform = platform or sys.platform
    windows = platform.startswith("win")
    if name == "emacs":
        ## Each file starts an Emacs of its own, which cannot be closed from
        ## here, so no close commands.
        if windows:
            return Viewer("runemacs.exe {file}", detach=True)
        if platform == "darwin":
            return Viewer("open -a Emacs {file}")
        return Viewer("emacs {file}", detach=True)
    if name == "emacsclient":
        if windows:
            return Viewer("emacsclientw.exe --no-wait {file}")
        return Viewer("emacsclient --no-wait {file}", _EMACS_CLOSE, _EMACS_CLOSE_DIR)
    if name == "vscode":
        code = "code.cmd" if windows else "code"
        return Viewer(code + " --reuse-window {file}")
    if name == "pycharm":
        if windows:
            return Viewer("pycharm.cmd {file}")
        if platform == "darwin":
            return Viewer("open -a PyCharm {file}")
        return Viewer("pycharm {file}")
    raise ValueError("unknown viewer: {}".format(name))


def _toml_string(text):
    ## JSON's string escapes are valid TOML basic-string escapes.
    return json.dumps(text)


def save_viewer(name, path=None, platform=None):
    """Make ``name`` (one of ``VIEWER_CHOICES``, or None to remove it) the
    configured ``[viewer]`` in the config file, keeping everything else in
    it, and return the new ``Viewer`` (None for None)."""
    path = path or default_path()
    try:
        with open(path) as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        lines = []
    kept, skipping = [], False
    for line in lines:
        header = re.match(r"\s*\[", line)
        if header:
            skipping = re.match(r"\s*\[\s*viewer\s*\]", line) is not None
        if not skipping:
            kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    viewer = preset_viewer(name, platform) if name else None
    if viewer is not None:
        if kept:
            kept.append("")
        kept.append("[viewer]")
        for key in ("open", "close", "close_dir"):
            value = getattr(viewer, key)
            if value is not None:
                kept.append("{} = {}".format(key, _toml_string(value)))
        if viewer.detach:
            kept.append("detach = true")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(kept) + "\n" if kept else "")
    return viewer
