"""Marking script for the "print Hello World" assignment.

Run it against a submission directory (from here, so tent-arbiter
finds this file by its default arb.py convention):

    poetry run tent-arbiter submissions/correct

...and against the broken one, to see the mechanical check fail (the
style question is still asked -- each criterion is scored on its own):

    poetry run tent-arbiter submissions/broken
"""
import os

from tent_arbiter.core import Exercise, RunMarker
from tent_arbiter.matchers import Exact, SubString


# tent-arbiter reads this before running the Exercise below, and
# refuses to run it if a RunMarker's criterion/points don't match a
# criterion actually defined here.
RUBRIC_TOML = os.path.join(os.path.dirname(__file__), "hello_world.rubric.toml")

# The assignment specifies this as the filename a submission must use
# for its entry point, so every submission directory has one.
ENTRY_POINT = "hello_world.py"


def build(submission_dir):
    """One RunMarker per rubric criterion, each scoring its own slice
    of the submission in submission_dir. A RunMarker builds up a list
    of steps to perform; nothing actually runs until the Exercise
    returned here is run."""

    # Correctness is checked mechanically: run the entry point and
    # compare its stdout exactly.
    correctness = RunMarker(submission_dir, criterion="correctness")
    correctness.python(ENTRY_POINT).match_stdout(
        10,
        Exact("Hello World\n", "Your program outputs Hello World as required", 10),
        SubString("Hello", "Part of the output is right", 5),
        Exact("Goodbye World\n", "Your program output the wrong thing", 0),
    ).or_else().ask_for_score(
        # Quote what the program actually printed, so the marker can see
        # why the matchers could not decide.
        lambda ctx: "No expected output matched. The program printed:\n{}\n"
        "-- score out of 10? ".format(ctx.completed_process.stdout),
        10,
    )

    # Style (comments, naming, structure) can't be checked
    # mechanically, so this asks a human marker instead, quoting the
    # entry point's own source so they don't have to go find it
    # themselves. No .python() step is needed here -- judging style
    # doesn't require running anything.
    style = RunMarker(submission_dir, criterion="style")
    source_path = os.path.join(submission_dir, ENTRY_POINT)
    style.ask_for_score(
        lambda ctx: "Style, given source:\n{}\n-- score out of 2? ".format(
            open(source_path).read()
        ),
        out_of=2,
    )

    return Exercise(correctness, style)
