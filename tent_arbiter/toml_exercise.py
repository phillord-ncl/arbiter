"""Build an ``Exercise`` from an ``arb.toml`` instead of an ``arb.py``.

A declarative alternative for the common case -- run a script, score its
output with matchers, ask a human about the rest. Anything it cannot say
still needs an ``arb.py``. Layout::

    rubric = "greeting.rubric.toml"      # optional, relative to this file

    [[marker]]
    criterion = "correctness"            # a .rubric.toml criterion id

    [[marker.step]]
    type = "python"                      # entry point, in the submission
    entry_point = "greeting.py"
    args = ["Ada"]                       # optional

    [[marker.step]]
    type = "match_stdout"
    out_of = 10
    [[marker.step.match]]                # tried in order, first wins
    type = "exact"                       # exact|substring|regexp|always
    match = "Hello, Ada!\\n"
    feedback = "Correct"
    score = 10

    [[marker.step]]
    type = "ask_for_score"
    or_else = true                       # only if nothing above decided
    question = "It printed:\\n{stdout}\\n-- score out of 10? "
    out_of = 10

A question may use ``{stdout}`` and ``{stderr}`` (from the marker's own
``python`` step; empty if there was none) and ``{file}``, the contents of
the step's optional ``file`` (in the submission).
"""

import os
import tomllib

from tent_arbiter.core import Exercise, RunMarker
from tent_arbiter.matchers import Always, Exact, RegexpAny, SubString


class ArbTomlError(Exception):
    pass


def _matcher(spec, where):
    kind = spec.get("type")
    try:
        if kind == "always":
            return Always(spec["feedback"], spec["score"])
        classes = {"exact": Exact, "substring": SubString, "regexp": RegexpAny}
        if kind not in classes:
            raise ArbTomlError(
                "{}: unknown match type {!r} (want one of exact, substring, "
                "regexp, always)".format(where, kind)
            )
        return classes[kind](spec["match"], spec["feedback"], spec["score"])
    except KeyError as e:
        raise ArbTomlError("{}: missing {}".format(where, e)) from None


def _question(spec, directory):
    template = spec["question"]
    path = spec.get("file")

    def question(ctx):
        process = getattr(ctx, "completed_process", None)
        text = ""
        if path is not None:
            with open(os.path.join(directory, path)) as f:
                text = f.read()
        return template.format(
            stdout=process.stdout if process else "",
            stderr=process.stderr if process else "",
            file=text,
        )

    return question


def _add_step(marker, spec, where, directory):
    kind = spec.get("type")
    if spec.get("or_else", False):
        marker.or_else()
    try:
        if kind == "python":
            marker.python(spec["entry_point"], *spec.get("args", []))
        elif kind == "match_stdout":
            matchers = [
                _matcher(m, "{} match {}".format(where, i + 1))
                for i, m in enumerate(spec.get("match", []))
            ]
            marker.match_stdout(spec["out_of"], *matchers)
        elif kind == "ask_for_score":
            marker.ask_for_score(_question(spec, directory), spec["out_of"])
        else:
            raise ArbTomlError(
                "{}: unknown step type {!r} (want one of python, "
                "match_stdout, ask_for_score)".format(where, kind)
            )
    except KeyError as e:
        raise ArbTomlError("{}: missing {}".format(where, e)) from None


def load_exercise(path, submission_dir):
    """Return ``(exercise, rubric_path)``; ``rubric_path`` is None if the
    file names no rubric."""
    with open(path, "rb") as f:
        data = tomllib.load(f)

    markers = []
    for i, spec in enumerate(data.get("marker", [])):
        where = "marker {}".format(i + 1)
        marker = RunMarker(submission_dir, criterion=spec.get("criterion"))
        for j, step in enumerate(spec.get("step", [])):
            _add_step(marker, step, "{} step {}".format(where, j + 1), submission_dir)
        markers.append(marker)
    if not markers:
        raise ArbTomlError("{} defines no [[marker]]".format(path))

    rubric = data.get("rubric")
    if rubric is not None:
        rubric = os.path.join(os.path.dirname(os.path.abspath(path)), rubric)
    return Exercise(*markers), rubric
