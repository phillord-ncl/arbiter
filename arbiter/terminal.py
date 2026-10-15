"""Open a terminal in a directory, so a marker can run things by hand.

All arbiter promises is the working directory. ``[terminal] open`` in the
user's ``config.toml`` is a command with ``{dir}`` in it; whatever it
starts, the process is also launched with that directory as its cwd, so a
terminal with no directory option still opens in the right place. Which
shell runs inside is the terminal's own business.
"""

import os
import shlex
import shutil
import subprocess
import sys


class TerminalError(Exception):
    pass


def _system(platform=None):
    platform = platform or sys.platform
    if platform.startswith("win"):
        return "windows"
    return "darwin" if platform == "darwin" else "linux"


## xdg-terminal-exec starts the desktop's own choice of terminal, so it is
## tried before guessing by name.
LINUX_TERMINALS = (
    "xdg-terminal-exec",
    "x-terminal-emulator",
    "gnome-terminal",
    "konsole",
    "xfce4-terminal",
    "kitty",
    "alacritty",
    "xterm",
)


def default_command(system, which=shutil.which, environ=os.environ):
    """A best guess at a terminal for this platform, or None."""
    if system == "windows":
        if which("wt"):
            return ["wt", "-d", "{dir}"]
        return ["cmd", "/c", "start", "", "cmd", "/k"]
    if system == "darwin":
        return ["open", "-a", "Terminal", "{dir}"]
    if environ.get("TERMINAL"):
        return shlex.split(environ["TERMINAL"])
    for name in LINUX_TERMINALS:
        if which(name):
            if name == "xdg-terminal-exec":
                ## With no command it can start nothing visible (ptyxis
                ## just re-activates), so ask for a shell.
                return [name, environ.get("SHELL") or "sh"]
            return [name]
    return None


def open_terminal(
    directory,
    template=None,
    platform=None,
    popen=subprocess.Popen,
    which=shutil.which,
    environ=os.environ,
):
    """Start a terminal in ``directory`` without waiting for it; returns
    the command used. ``template`` is the configured command line (a
    string), else a platform default is guessed."""
    system = _system(platform)
    if template:
        words = shlex.split(template, posix=system != "windows")
    else:
        words = default_command(system, which, environ)
        if words is None:
            raise TerminalError(
                "no terminal found; set [terminal] open in config.toml "
                "(see docs/terminal.md)"
            )
    args = [w.replace("{dir}", directory) for w in words]
    try:
        popen(
            args,
            cwd=directory,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=system != "windows",
        )
    except OSError as e:
        raise TerminalError("cannot start {}: {}".format(args[0], e)) from None
    return args
