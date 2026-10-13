"""Worked example: a two-criterion Exercise -- one mechanical, one
judgement -- for the "print Hello World" task, checked against
hello_world.rubric.toml before it runs.

Run it against the correct submission:

    poetry run python examples/hello_world/arb.py \\
        examples/hello_world/submissions/correct/hello_world.py

...and against the broken one, to see the mechanical check actually
fail (it will still ask the style question -- the two are independent
criteria, each scored on its own):

    poetry run python examples/hello_world/arb.py \\
        examples/hello_world/submissions/broken/hello_world.py
"""
import os
import sys

from tent_arbiter.core import Exercise, Result, RunMarker


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


def ask_interactively(question):
    answer = input(question.question)
    score = float(answer) if answer.strip() else 0.0
    return Result(out_of=question.out_of, score=score, feedback="marker-entered")


if __name__ == "__main__":
    exercise = build(sys.argv[1])

    # Static -- reads the Markers' own declared out_of values, runs
    # nothing. Catches drift between what this script actually scores
    # and what the rubric says, before wasting anyone's time running it.
    problems = exercise.check_consistent_with_rubric_toml(RUBRIC_TOML)
    if problems:
        sys.exit("Inconsistent with {}:\n{}".format(RUBRIC_TOML, "\n".join(problems)))

    exercise.run(ask_interactively=ask_interactively)

    for marker in exercise.markers:
        for result in marker.results:
            print(
                "{}: {}/{} -- {}".format(
                    marker.criterion, result.score, result.out_of, result.feedback
                )
            )
