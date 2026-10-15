"""The `arbiter` command -- loads an arb.py (the doit/dodo.py-style
convention: look for it in the current directory unless told otherwise),
calls its build(submission) to get an Exercise, checks it against its own
rubric if it names one, runs it, and prints the results. Everything an
individual arb.py used to do in its own __main__ block belongs here
instead, so an arb.py only ever defines the Exercise itself. An arb.toml
(see toml_exercise.py) does the same declaratively.
"""

import collections
import importlib.util
import glob
import os
import sys
import tomllib

import click

from .config import ConfigError, default_viewer, load_terminal, load_viewer
from .core import UNDECIDED_NOTE, RestartMarking, Result
from .dump import FILENAME, FORMATS, Dumper, load_previous
from .scripts import ScriptClash
from .toml_exercise import ArbTomlError, load_exercise


def _load_arb(path):
    spec = importlib.util.spec_from_file_location("arb", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _default_ask_interactively(question):
    if question.session is not None and question.session.task:
        click.echo("Task: {}".format(question.session.task))
    if question.undecided:
        click.echo(UNDECIDED_NOTE)
    session = question.session
    if session is not None and session.commands:
        click.echo(
            "In {}, you can run: {}".format(
                session.directory, ", ".join(session.commands)
            )
        )
    for item in question.context:
        click.echo("--- {}".format(item.title))
        if item.text is not None:
            click.echo(item.text)
        elif item.inline and item.path is not None:
            with open(item.path, errors="replace") as f:
                click.echo(f.read())
    previous = question.previous
    if previous is not None:
        click.echo(
            "Stored answer: {} -- {} (Enter keeps it)".format(
                previous.score, previous.feedback
            )
        )
    click.echo("(type 'restart' to mark this submission again from the start)")
    while True:
        answer = input(question.question)
        if answer.strip().lower() == "restart":
            raise RestartMarking()
        if previous is not None and not answer.strip():
            return Result(
                out_of=question.out_of, score=previous.score, feedback=previous.feedback
            )
        try:
            score = float(answer) if answer.strip() else 0.0
        except ValueError:
            score = None
        if score is not None and question.accepts(score):
            break
        click.echo("Please enter {}.".format(question.allowed()))
    return Result(out_of=question.out_of, score=score, feedback="marker-entered")


class Progress:
    """How far through a batch of submissions we are, for the TUI's panel."""

    LOG_LINES = 2

    def __init__(self, total):
        self.total = total
        self.done = 0
        self.log = collections.deque(maxlen=self.LOG_LINES)

    def note(self, line):
        self.log.append(line)

    def finished(self, name):
        self.done += 1
        self.note("{}: marked".format(name))

    def skipped(self, name):
        self.done += 1
        self.note("{}: already complete, skipped".format(name))


def _is_complete(submission):
    """True if the submission's results file says marking finished."""
    try:
        with open(os.path.join(submission, FILENAME + ".toml"), "rb") as f:
            return bool(tomllib.load(f).get("complete"))
    except (OSError, ValueError):
        return False


def _expand(paths, recursive):
    """The submissions named by ``paths``; with ``recursive`` each path is a
    directory whose (non-hidden) subdirectories are the submissions."""
    if not recursive:
        return [_find_submission(p) for p in paths]
    found = []
    for path in paths:
        if not os.path.isdir(path):
            raise click.UsageError("{} is not a directory".format(path))
        found += [
            os.path.join(path, d)
            for d in sorted(os.listdir(path))
            if not d.startswith(".") and os.path.isdir(os.path.join(path, d))
        ]
    return found


def _choose_ask(tui, progress=None):
    """The hook to answer questions with: the TUI if asked for, or if it is
    installed and we are in a terminal; otherwise plain prompts."""
    if tui is None:
        tui = sys.stdin.isatty() and sys.stdout.isatty()
        wanted = False
    else:
        wanted = tui
    if tui:
        try:
            from .tui import make_ask_interactively
        except ImportError:
            if wanted:
                raise click.ClickException(
                    "the terminal UI needs the tui extra: pip install 'arbiter[tui]'"
                )
            return _default_ask_interactively
        try:
            viewer = load_viewer() or default_viewer()
        except ConfigError as e:
            raise click.ClickException(str(e))
        try:
            terminal = load_terminal()
        except ConfigError as e:
            raise click.ClickException(str(e))
        return make_ask_interactively(viewer, terminal, progress)
    return _default_ask_interactively


def _find_arb():
    """arb.toml, else arb.py, else the one NAME.arb.toml / NAME.arb.py."""
    for name in ("arb.toml", "arb.py"):
        if os.path.exists(name):
            return name
    for pattern in ("*.arb.toml", "*.arb.py"):
        found = sorted(glob.glob(pattern))
        if len(found) == 1:
            return found[0]
        if found:
            raise click.UsageError(
                "more than one {} here ({}); choose with --arb".format(
                    pattern, ", ".join(found)
                )
            )
    raise click.UsageError(
        "no arb.toml, arb.py, *.arb.toml or *.arb.py in the current directory"
    )


def _find_submission(name):
    """NAME itself, else the one directory called NAME@..., else NAME..."""
    if os.path.isdir(name):
        return name
    for pattern in (glob.escape(name) + "@*", glob.escape(name) + "*"):
        found = sorted(d for d in glob.glob(pattern) if os.path.isdir(d))
        if len(found) == 1:
            return found[0]
        if found:
            raise click.UsageError(
                "{} matches more than one directory: {}".format(
                    name, ", ".join(found)
                )
            )
    return name


@click.command(
    help="Run an arb.py or arb.toml's Exercise against each SUBMISSION. With "
    "-r, each SUBMISSION is a directory of submissions instead."
)
@click.argument("submissions", nargs=-1, required=True)  # a directory, or a unique NAME@... / NAME...
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Each argument is a directory whose subdirectories are the "
         "submissions. Submissions already marked complete are skipped "
         "(unless --fresh).",
)
@click.option(
    "--arb",
    "arb_path",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the arb.py or arb.toml defining the Exercise (default: "
         "arb.toml, arb.py, or the one *.arb.toml / *.arb.py, in the "
         "current directory).",
)
@click.option(
    "--output",
    "output",
    default=None,
    type=click.Path(dir_okay=False),
    help="Where to write the TOML results (default: arb-results.toml in "
         "the submission directory). Extra formats go beside it.",
)
@click.option(
    "--also",
    "also",
    multiple=True,
    type=click.Choice([f for f in FORMATS if f != "toml"]),
    help="Also write results in this format (repeatable). TOML is always "
         "written.",
)
@click.option(
    "--root",
    "root",
    default=None,
    help="The student's project, a directory inside SUBMISSION, overriding "
         "the arb.toml's root (for an odd upload).",
)
@click.option(
    "--fresh",
    is_flag=True,
    help="Ignore answers stored in an earlier results file for this "
         "submission (by default they are shown, pre-filled).",
)
@click.option(
    "--tui/--no-tui",
    "tui",
    default=None,
    help="Answer questions in the terminal UI (needs the tui extra). "
         "Default: use it if installed and running in a terminal.",
)
def cli(submissions, recursive, arb_path, output, also, root, fresh, tui):
    arb_path = arb_path or _find_arb()
    found = _expand(submissions, recursive)
    if not found:
        raise click.ClickException("no submissions found")
    if output is not None and len(found) > 1:
        raise click.UsageError("--output needs exactly one submission")
    ## One submission named outright is marked again whatever its state;
    ## among several, the complete ones are skipped.
    batch = len(found) > 1 or recursive
    progress = Progress(len(found))
    chosen = []

    def choose():
        if not chosen:
            chosen.append(_choose_ask(tui, progress))
        return chosen[0]

    todo = []
    for submission in found:
        name = os.path.basename(os.path.abspath(submission))
        if batch and not fresh and _is_complete(submission):
            progress.skipped(name)
            click.echo("{}: already complete, skipped".format(name), err=True)
        else:
            todo.append(submission)

    ## The marker chose to stop (Ctrl-Q, Ctrl-C): answers so far are kept.
    try:
        for i, submission in enumerate(todo):
            name = os.path.basename(os.path.abspath(submission))
            _mark(submission, arb_path, output, also, root, fresh, choose, batch)
            progress.finished(name)
            if i + 1 < len(todo):
                upcoming = os.path.basename(os.path.abspath(todo[i + 1]))
                if not _confirm_next(chosen, name, upcoming, progress):
                    raise KeyboardInterrupt
    except KeyboardInterrupt:
        click.echo("Stopped. Answers so far are saved; run again to resume.",
                   err=True)
        sys.exit(1)


def _confirm_next(chosen, finished, upcoming, progress):
    """Pause between students so the marker can close the last one's
    terminals and viewer files. True to carry on."""
    hook = getattr(chosen[0], "next_student", None) if chosen else None
    if hook is not None:
        return hook(finished, upcoming, progress)
    if sys.stdin.isatty() and sys.stdout.isatty():
        return click.confirm(
            "{} done. Close their terminals and files. Next student, {}?".format(
                finished, upcoming
            ),
            default=True,
        )
    return True


def _mark(submission, arb_path, output, also, root, fresh, choose, batch):
    if arb_path.endswith(".toml"):
        try:
            exercise, rubric_toml = load_exercise(arb_path, submission, root)
        except ArbTomlError as e:
            raise click.ClickException("{}: {}".format(arb_path, e))
        ask_interactively = choose()
    else:
        module = _load_arb(arb_path)
        project_dir = os.path.join(submission, root) if root else submission
        exercise = module.build(project_dir)
        exercise.directory = project_dir
        rubric_toml = getattr(module, "RUBRIC_TOML", None)
        ask_interactively = getattr(module, "ask_interactively", None) or choose()

    if rubric_toml is not None:
        problems = exercise.check_consistent_with_rubric_toml(rubric_toml)
        if problems:
            raise click.ClickException(
                "{} is inconsistent with {}:\n{}".format(
                    arb_path, rubric_toml, "\n".join(problems)
                )
            )

    if rubric_toml is not None:
        exercise.apply_rubric(rubric_toml)

    base = os.path.join(submission, FILENAME)
    if output is not None:
        base = output[: -len(".toml")] if output.endswith(".toml") else output
    project = exercise.directory or submission
    if not os.path.isdir(project):
        raise click.ClickException(
            "no project directory {} (is {} one submission, and is the "
            "root right? see --root)".format(project, submission)
        )
    dumper = Dumper(base, submission, rubric_toml, also)
    try:
        previous = load_previous(base + ".toml")
    except (OSError, ValueError, KeyError) as e:
        raise click.ClickException(
            "cannot read the earlier results {}.toml ({}); remove it or use "
            "--fresh".format(base, e)
        )
    try:
        exercise.prepare(project)
    except ScriptClash as e:
        raise click.ClickException(str(e))
    label = os.path.basename(os.path.abspath(submission))
    # Write after every human answer, not just at the end, so a crash
    # mid-marking keeps what was already entered.
    exercise.run(
        ask_interactively=ask_interactively,
        checkpoint=dumper.write,
        label=label,
        directory=os.path.abspath(project),
        previous=None if fresh else previous,
    )
    dumper.write(exercise, complete=True)

    if batch:
        click.echo(
            "{}: {}/{}".format(label, exercise.score(), exercise.max_score()),
            err=True,
        )
        return
    for marker in exercise.markers:
        for result in marker.results:
            click.echo(
                "{}: {}/{} -- {}".format(
                    marker.criterion, result.score, result.out_of, result.feedback
                )
            )
    for path in dumper.paths():
        click.echo("results written to {}".format(path), err=True)
