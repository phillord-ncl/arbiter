# Running a submission by hand

Some questions can only be answered by running the student's program and
looking at it. `arbiter` helps in two ways.

## marker-* scripts

For an Exercise that uses them (its `arb.toml` declares a `[[script]]` or a
`python_version`, or a step has `venv = true`), `arbiter` writes a few scripts
into each submission directory before marking:

- `marker-python ARGS` runs the venv's Python.
- `marker-pip` sets the venv up; with arguments it runs `pip` in it.
- any more the Exercise declares.

Each script makes `marker-venv` if it is missing, installs
`requirements.txt` if there is one, then runs its command with the venv's own
interpreter. The first run waits for the install; later runs are quick. No
activation is needed, so any shell will do. On Windows the scripts are
`marker-python.cmd` and so on; in PowerShell type `.\marker-python`.

`marker-venv` is named so that it cannot be mistaken for a `.venv` the
student submitted. If the submission already has a file called `marker-...`
that is not `arbiter`'s, `arbiter` stops and writes nothing: sort it out
by hand.

## A terminal in the right place (Ctrl-T)

In the terminal UI, Ctrl-T opens a terminal in the submission directory.
Configure which one in `config.toml` (same place as the viewer, see
`viewer.md`):

```toml
[terminal]
open = "kitty --directory {dir}"
```

`{dir}` is the submission's full path. The terminal is also started with
that directory as its working directory, so one with no directory option
still opens in the right place. Which shell runs inside is the terminal's
business. With nothing configured, `arbiter` guesses: `$TERMINAL`, else
`xdg-terminal-exec` (the desktop's own choice), else the first of a few
common terminals on Linux, Terminal on macOS, `wt` (else
`cmd`) on Windows.
