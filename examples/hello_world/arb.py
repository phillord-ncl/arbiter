"""Worked example: a two-criterion Exercise -- one mechanical, one
judgement -- for the "print Hello World" task, checked against
hello_world.rubric.toml before it runs.

Run it against the correct submission (from this directory, so
tent-arbiter finds this file by its default arb.py convention):

    poetry run tent-arbiter submissions/correct/hello_world.py

...and against the broken one, to see the mechanical check actually
fail (it will still ask the style question -- the two are independent
criteria, each scored on its own):

    poetry run tent-arbiter submissions/broken/hello_world.py

tent-arbiter calls build() below with the submission path, checks the
result against RUBRIC_TOML, runs it, and prints each Marker's results
-- all of which used to be this file's own __main__ block.
"""
import os

from tent_arbiter.core import Exercise, RunMarker


RUBRIC_TOML = os.path.join(os.path.dirname(__file__), "hello_world.rubric.toml")


def build(submission_path):
    # "correctness" -- mechanical: run the submission, check its stdout
    # exactly. .python() and .match_stdout() only record Steps here;
    # nothing actually runs until exercise.run() below.
    correctness = RunMarker(submission_path, criterion="correctness")
    correctness.python().match_stdout(
        "Hello World\n", score_out_of=10, score_matches=10, score_does_not_match=0
    )

    # "style" -- judgement, deferred until run()'s second pass. Its own
    # .python() step re-runs the same submission under its own
    # RunContext -- never shared with "correctness"'s, see notes.org --
    # purely so the question below can quote its own stdout.
    style = RunMarker(submission_path, criterion="style")
    style.python().ask_for_score(
        lambda ctx: "Style, given stdout {!r} -- score out of 2? ".format(
            ctx.completed_process.stdout
        ),
        out_of=2,
    )

    return Exercise(correctness, style)
