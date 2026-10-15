# arbiter

A tool for marking programming assignments. You describe the marking scheme
once, in an `arb.toml` (or, for anything it cannot say, an `arb.py`). Then
`arbiter` takes each student's submission through it. It runs their code and
scores the output, does mechanical checks (is there a README, how many
commits), and asks you about the parts that need judgement. It writes the
results to a file as it goes, so a marking session can be stopped and resumed.

**This is a work in progress.** It is in active development, has been tried
on few courses and platforms, and its interface and file formats may change
without notice.

## Installing

`arbiter` needs Python 3.12 or later and [pipx](https://pipx.pypa.io/).

```
pipx install "arbiter[tui] @ git+https://github.com/phillord-ncl/arbiter.git"
```

Keep the quotes. Drop `[tui]` for the plain command line version without the
terminal UI. To upgrade later, run the same command with `--force`.

## Using it

```
arbiter --arb arb.toml path/to/submission
```

With no `--arb`, arbiter looks in the current directory for an `arb.toml` or
`arb.py`. See `examples/` for small working schemes, and `docs/` for the
available checks, how to resume a session, and how to configure the terminal
and the viewer used to look at students' files.
