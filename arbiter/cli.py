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
import tempfile
import tomllib

import click

from .config import ConfigError, default_viewer, load_terminal, load_viewer
from .core import UNDECIDED_NOTE, GoBack, RestartMarking, Result
from .dump import FILENAME, FORMATS, Dumper, load_previous
from .scripts import ScriptClash
from .toml_exercise import ArbTomlError, load_exercise
from .unpack import UnpackError, gather_canvas, unpack


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
    if session is not None and session.position > 1:
        click.echo("(type 'back' to return to the previous question)")
    if question.feedback_only:
        click.echo(question.question)
        while True:
            feedback = input("Feedback: ").strip()
            if not question.feedback_problem(0, feedback):
                return Result(
                    out_of=0, score=0, feedback=feedback or question.default_feedback(0)
                )
            click.echo("Feedback is required.")
    while True:
        answer = input(question.question)
        if answer.strip().lower() == "restart":
            raise RestartMarking()
        if answer.strip().lower() == "back":
            raise GoBack()
        if previous is not None and not answer.strip():
            return Result(
                out_of=question.out_of, score=previous.score, feedback=previous.feedback
            )
        try:
            score = float(answer) if answer.strip() else 0.0
        except ValueError:
            score = None
        if score is None or not question.accepts(score):
            click.echo("Please enter {}.".format(question.allowed()))
            continue
        feedback = ""
        if question.full_feedback and question.is_full(score):
            feedback = input("Feedback [{}]: ".format(question.full_feedback)).strip()
        elif question.require_feedback and not question.is_full(score):
            while not feedback:
                feedback = input("Feedback (required): ").strip()
        return Result(
            out_of=question.out_of,
            score=score,
            feedback=feedback or question.default_feedback(score),
        )


def _mark_good_ask(question):
    """Answer every question with full marks and its full-marks feedback."""
    score = question.out_of
    if not question.accepts(score):
        score = max(question.choices)
    return Result(
        out_of=question.out_of, score=score, feedback=question.default_feedback(score)
    )


def _mark_bad_ask(question):
    """Answer every question with the lowest allowed score."""
    score = min(question.choices) if question.choices is not None else 0
    return Result(
        out_of=question.out_of, score=score, feedback=question.default_feedback(score)
    )


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
    "-r, each SUBMISSION is a directory of submissions instead.\n\n"
    "\b\nSubcommands (arbiter COMMAND --help for each):\n"
    "  unpack  Unpack uploads (zip, tar, or a Canvas download) into\n"
    "          submissions ready to mark."
)
@click.argument("submissions", nargs=-1)  # a directory, or a unique NAME@... / NAME...
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
@click.option(
    "--mark-good",
    "mark_good",
    is_flag=True,
    help="Answer every question with full marks and its full-marks feedback, "
         "without asking, to check what a perfect submission is told. "
         "With no submission, runs on an empty project and prints the "
         "answers, writing nothing. With one, implies --fresh and "
         "overwrites its results: use a copy.",
)
@click.option(
    "--mark-bad",
    "mark_bad",
    is_flag=True,
    help="Answer every question with its lowest allowed score (zero, or the "
         "worst choice) and no feedback, without asking. With no submission, "
         "runs on an empty project and prints the answers, writing "
         "nothing. With one, implies --fresh and overwrites its results: "
         "use a copy.",
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="Show every question as a marker would see it, with no submission: "
         "nothing is run or written and answers are thrown away. For "
         "writing an arb file.",
)
def cli(
    submissions, recursive, arb_path, output, also, root, fresh, tui, dry_run, mark_good,
    mark_bad,
):
    arb_path = arb_path or _find_arb()
    if dry_run:
        if submissions:
            raise click.UsageError("--dry-run takes no submission")
        _dry_run(arb_path, root, tui)
        return
    if mark_good and mark_bad:
        raise click.UsageError("--mark-good and --mark-bad are exclusive")
    auto = _mark_good_ask if mark_good else _mark_bad_ask if mark_bad else None
    if auto and not submissions:
        _dry_run(arb_path, root, tui, auto)
        return
    if not submissions:
        raise click.UsageError("Missing argument 'SUBMISSIONS...'.")
    found = _expand(submissions, recursive)
    if not found:
        raise click.ClickException("no submissions found")
    if output is not None and len(found) > 1:
        raise click.UsageError("--output needs exactly one submission")
    ## One submission named outright is marked again whatever its state;
    ## among several, the complete ones are skipped.
    batch = len(found) > 1 or recursive
    if auto:
        fresh = True
    progress = Progress(len(found))
    chosen = []

    def choose():
        if not chosen:
            chosen.append(auto or _choose_ask(tui, progress))
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
            done = getattr(chosen[0], "student_done", None) if chosen else None
            if done is not None:
                done(submission)
            if i + 1 < len(todo):
                upcoming = os.path.basename(os.path.abspath(todo[i + 1]))
                if not auto and not _confirm_next(
                    chosen, name, upcoming, progress
                ):
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


def _dry_run(arb_path, root, tui, auto=None):
    """Walk the whole scheme on an empty project in a temporary directory,
    so an arb file's author sees what a marker will. The student's code is
    never run, and no results or scripts are written. With ``auto``, that
    hook answers the questions and the results are printed."""
    with tempfile.TemporaryDirectory(prefix="arbiter-dry-run-") as tmp:
        if arb_path.endswith(".toml"):
            try:
                exercise, rubric_toml = load_exercise(arb_path, tmp, root)
            except ArbTomlError as e:
                raise click.ClickException("{}: {}".format(arb_path, e))
            ask_interactively = auto or _choose_ask(tui)
        else:
            module = _load_arb(arb_path)
            project_dir = os.path.join(tmp, root) if root else tmp
            os.makedirs(project_dir, exist_ok=True)
            exercise = module.build(project_dir)
            exercise.directory = project_dir
            rubric_toml = getattr(module, "RUBRIC_TOML", None)
            ask_interactively = (
                auto or getattr(module, "ask_interactively", None) or _choose_ask(tui)
            )
        if rubric_toml is not None:
            exercise.apply_rubric(rubric_toml)
        project = exercise.directory or tmp
        os.makedirs(project, exist_ok=True)
        exercise.dry_run = True
        try:
            exercise.run(
                ask_interactively=ask_interactively,
                label="dry run",
                directory=os.path.abspath(project),
            )
        except KeyboardInterrupt:
            click.echo("Dry run stopped.", err=True)
            sys.exit(1)
        if auto:
            for marker in exercise.markers:
                for result in marker.results:
                    click.echo(
                        "{}: {}/{} -- {}".format(
                            marker.criterion, result.score, result.out_of,
                            result.feedback,
                        )
                    )
    click.echo("Dry run: nothing was written.", err=True)


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


@click.command(name="unpack")
@click.argument("submissions", nargs=-1, required=True)
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Each argument is a directory whose subdirectories are the "
         "submissions.",
)
@click.option(
    "--canvas",
    "canvas_out",
    default=None,
    type=click.Path(file_okay=False),
    help="The single argument is a Canvas bulk download, the "
         "submissions.zip or its unpacked directory (files named "
         "NAME_USERID_SUBMISSIONID_FILE). Make one directory "
         "per student in this directory, then unpack each.",
)
@click.option(
    "--into",
    default="project",
    show_default=True,
    help="The directory to make in each submission (the arb.toml's root).",
)
@click.option(
    "--force",
    is_flag=True,
    help="Replace the directory if it already exists (by default it is "
         "left alone).",
)
def unpack_cmd(submissions, recursive, canvas_out, into, force):
    """Make a project directory in each SUBMISSION from the files the
    student uploaded.

    An archive (zip or tar) is unpacked, whether it holds one directory, the
    files loose at the top, or directories nested pointlessly; a submission
    of plain files has them copied. The originals are kept."""
    failed = 0
    if canvas_out is not None:
        if len(submissions) != 1 or recursive:
            raise click.UsageError("--canvas takes one download directory")
        try:
            found = gather_canvas(submissions[0], canvas_out)
        except UnpackError as e:
            raise click.ClickException(str(e))
    else:
        found = _expand(submissions, recursive)
    for submission in found:
        name = os.path.basename(os.path.abspath(submission))
        try:
            click.echo("{}: {}".format(name, unpack(submission, into, force)))
        except UnpackError as e:
            failed += 1
            click.echo("{}: {}".format(name, e), err=True)
    if failed:
        raise click.ClickException("{} submission(s) not unpacked".format(failed))


def main():
    """The ``arbiter`` command: ``arbiter unpack ...``, else marking."""
    if sys.argv[1:2] == ["unpack"]:
        unpack_cmd(sys.argv[2:], prog_name="arbiter unpack")
    else:
        cli()
