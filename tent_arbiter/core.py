"""Plan/run execution model -- see ../notes.org for the design discussion.

Every ``Marker`` builder method records a ``Step`` rather than acting on
it; nothing runs until ``Exercise.run()``. ``run()`` makes two passes over
the whole tree: every mechanical step first, in document order within each
``Marker``; only then every queued judgement step, one at a time.
"""

from dataclasses import dataclass
from typing import Callable, List, Optional, Union
import subprocess

from tent_pole.rubric import load_rubric_toml


@dataclass
class Result:
    out_of: float
    score: float
    feedback: str


@dataclass
class Question:
    question: str
    out_of: float


@dataclass
class Step:
    mechanical: bool
    action: Callable[["RunContext"], Optional[Union[Result, Question]]]
    ## The points this step can award, known up front from its own
    ## builder-method arguments -- None for a step that sets up ctx for a
    ## later step rather than scoring anything itself (e.g. python()).
    ## Letting Marker.max_score() read this directly means a Marker's
    ## total is known statically, without running anything -- needed for
    ## Exercise.check_consistent_with_rubric_toml below.
    out_of: Optional[float] = None


class RunContext:
    """Scratch space for one Marker's own steps to pass data to each other
    (e.g. ``match_stdout`` reading ``python()``'s ``completed_process``).

    One RunContext per Marker, never shared across Markers in the same
    Exercise. A judgement step's action is not actually called until
    ``Exercise.run()``'s second pass, by which point every Marker's
    mechanical steps -- across the *whole* Exercise, not just this Marker --
    have already run. A context shared Exercise-wide would, by then, hold
    whichever sibling Marker's data happened to run last in the first pass,
    not this Marker's own -- see test_two_run_markers_do_not_leak_context in
    tests/test_core.py, which is what pinned this down.
    """


class Marker:
    def __init__(self, criterion=None):
        ## Which tent-pole .rubric.toml criterion (by its own "id", not
        ## a Canvas id -- those aren't stable, see tent-pole's
        ## rubric.py) this Marker's results count towards. None means
        ## "not tied to a criterion", e.g. a Marker used standalone,
        ## outside Exercise.check_consistent_with_rubric_toml.
        self.criterion = criterion
        self.steps: List[Step] = []
        self.results: List[Result] = []

    def _step(self, mechanical, action, out_of=None):
        self.steps.append(Step(mechanical, action, out_of))
        return self

    def result(self, result):
        self.results.append(result)
        return self

    def max_score(self):
        """Total points this Marker can award, from its own steps'
        declared out_of values -- static, no step is actually run."""
        return sum(step.out_of for step in self.steps if step.out_of is not None)


class DirectoryMarker(Marker):
    """A Marker whose checks run against a submission *directory* --
    most student submissions pre-define their own entry-point filename
    (the assignment's own convention, e.g. "hello_world.py"), so a
    Marker is pointed at the directory once and each step says which
    file within it to act on, rather than a Marker being tied to one
    fixed file."""

    def __init__(self, directory, criterion=None):
        super().__init__(criterion=criterion)
        self.directory = directory


class RunMarker(DirectoryMarker):
    def python(self, entry_point, *args, **kwargs):
        def action(ctx):
            ctx.completed_process = subprocess.run(
                ["python3", entry_point, *args],
                capture_output=True,
                text=True,
                cwd=self.directory,
                **kwargs,
            )
            return None

        return self._step(True, action)

    def match_stdout(self, out_of, *matchers):
        """Score the script's stdout with the first of ``matchers`` (see
        tent_arbiter.matchers) that matches it. If none do, scores 0."""

        def action(ctx):
            stdout = ctx.completed_process.stdout
            for matcher in matchers:
                if matcher.matches(stdout):
                    return matcher.result(out_of)
            return Result(out_of=out_of, score=0, feedback="stdout did not match")

        return self._step(True, action, out_of=out_of)

    def ask_for_score(self, question, out_of):
        """``question`` may be a plain string, or a callable taking the
        Marker's own RunContext -- e.g. to quote the script's own stdout
        back in the question text. Either way it is not actually called
        until the second pass.
        """

        def action(ctx):
            text = question(ctx) if callable(question) else question
            return Question(text, out_of)

        return self._step(False, action, out_of=out_of)


class Exercise:
    def __init__(self, *markers):
        self.markers = list(markers)

    def run(self, ask_interactively):
        questions = []  # [(marker, step, ctx)], deferred to the second pass
        for marker in self.markers:
            ctx = RunContext()
            for step in marker.steps:
                if step.mechanical:
                    result = step.action(ctx)
                    if result is not None:
                        marker.result(result)
                else:
                    questions.append((marker, step, ctx))
        for marker, step, ctx in questions:
            question = step.action(ctx)
            marker.result(ask_interactively(question))
        return self

    def check_consistent_with_rubric_toml(self, path):
        """Cross-check this Exercise's own Markers against a tent-pole
        .rubric.toml's criteria -- the arbiter-side analogue of
        tent-pole's own points-drift linter (tent_pole/check.py), but
        catching drift between what arbiter actually scores and what's
        been defined (and pushed) as the Canvas-side rubric, rather than
        drift within the .rubric.toml alone.

        Static: reads every Marker's own declared out_of (via
        max_score()), never runs anything. Returns a list of plain-string
        problems -- empty means consistent -- rather than raising, so a
        caller can decide whether a mismatch is fatal.
        """
        parsed = load_rubric_toml(path)
        criteria = {c["id"]: c["points"] for c in parsed.get("criteria", [])}

        problems = []
        seen = set()
        for marker in self.markers:
            if marker.criterion is None:
                continue
            seen.add(marker.criterion)
            if marker.criterion not in criteria:
                problems.append(
                    "marker for {!r} has no matching criterion in {}".format(
                        marker.criterion, path
                    )
                )
                continue
            rubric_points = criteria[marker.criterion]
            marker_points = marker.max_score()
            if marker_points != rubric_points:
                problems.append(
                    "{!r}: marker scores out of {}, rubric criterion is out of {}".format(
                        marker.criterion, marker_points, rubric_points
                    )
                )

        for criterion_id in sorted(set(criteria) - seen):
            problems.append(
                "rubric criterion {!r} has no matching marker".format(criterion_id)
            )
        return problems
