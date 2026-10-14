"""The `tent-arbiter` command -- loads an arb.py (the doit/dodo.py-style
convention: look for it in the current directory unless told otherwise),
calls its build(submission) to get an Exercise, checks it against its own
rubric if it names one, runs it, and prints the results. Everything an
individual arb.py used to do in its own __main__ block belongs here
instead, so an arb.py only ever defines the Exercise itself. An arb.toml
(see toml_exercise.py) does the same declaratively.
"""

import importlib.util
import os
import sys

import click

from .config import ConfigError, load_viewer
from .core import Result
from .dump import FILENAME, FORMATS, Dumper
from .toml_exercise import ArbTomlError, load_exercise


def _load_arb(path):
    spec = importlib.util.spec_from_file_location("arb", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _default_ask_interactively(question):
    for item in question.context:
        click.echo("--- {}".format(item.title))
        if item.text is not None:
            click.echo(item.text)
    answer = input(question.question)
    score = float(answer) if answer.strip() else 0.0
    return Result(out_of=question.out_of, score=score, feedback="marker-entered")


def _choose_ask(tui):
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
                    "the terminal UI needs the tui extra: pip install 'tent-arbiter[tui]'"
                )
            return _default_ask_interactively
        try:
            viewer = load_viewer()
        except ConfigError as e:
            raise click.ClickException(str(e))
        return make_ask_interactively(viewer)
    return _default_ask_interactively


def _find_arb():
    for name in ("arb.toml", "arb.py"):
        if os.path.exists(name):
            return name
    raise click.UsageError("no arb.toml or arb.py in the current directory")


@click.command(help="Run an arb.py or arb.toml's Exercise against one submission.")
@click.argument("submission")
@click.option(
    "--arb",
    "arb_path",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to the arb.py or arb.toml defining the Exercise (default: "
         "arb.toml, else arb.py, in the current directory).",
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
    "--tui/--no-tui",
    "tui",
    default=None,
    help="Answer questions in the terminal UI (needs the tui extra). "
         "Default: use it if installed and running in a terminal.",
)
def cli(submission, arb_path, output, also, tui):
    arb_path = arb_path or _find_arb()
    if arb_path.endswith(".toml"):
        try:
            exercise, rubric_toml = load_exercise(arb_path, submission)
        except ArbTomlError as e:
            raise click.ClickException("{}: {}".format(arb_path, e))
        ask_interactively = _choose_ask(tui)
    else:
        module = _load_arb(arb_path)
        exercise = module.build(submission)
        rubric_toml = getattr(module, "RUBRIC_TOML", None)
        ask_interactively = getattr(module, "ask_interactively", None) or _choose_ask(
            tui
        )

    if rubric_toml is not None:
        problems = exercise.check_consistent_with_rubric_toml(rubric_toml)
        if problems:
            raise click.ClickException(
                "{} is inconsistent with {}:\n{}".format(
                    arb_path, rubric_toml, "\n".join(problems)
                )
            )

    base = os.path.join(submission, FILENAME)
    if output is not None:
        base = output[: -len(".toml")] if output.endswith(".toml") else output
    dumper = Dumper(base, submission, rubric_toml, also)
    # Write after every human answer, not just at the end, so a crash
    # mid-marking keeps what was already entered.
    exercise.run(
        ask_interactively=ask_interactively,
        checkpoint=dumper.write,
        label=os.path.basename(os.path.abspath(submission)),
    )
    dumper.write(exercise, complete=True)

    for marker in exercise.markers:
        for result in marker.results:
            click.echo(
                "{}: {}/{} -- {}".format(
                    marker.criterion, result.score, result.out_of, result.feedback
                )
            )
    for path in dumper.paths():
        click.echo("results written to {}".format(path), err=True)
