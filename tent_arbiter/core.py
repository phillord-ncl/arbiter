"""Plan/run execution model -- see ../notes.org for the design discussion.

Every ``Marker`` builder method records a ``Step`` rather than acting on
it; nothing runs until ``Exercise.run()``. ``run()`` makes two passes over
the whole tree: every mechanical step first, in document order within each
``Marker``; only then every queued judgement step, one at a time.
"""

from dataclasses import dataclass
from typing import Callable, List, Optional, Union
import subprocess


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
    def __init__(self):
        self.steps: List[Step] = []
        self.results: List[Result] = []

    def _step(self, mechanical, action):
        self.steps.append(Step(mechanical, action))
        return self

    def result(self, result):
        self.results.append(result)
        return self


class FileMarker(Marker):
    def __init__(self, filename):
        super().__init__()
        self.filename = filename


class RunMarker(FileMarker):
    def python(self, *args, **kwargs):
        def action(ctx):
            ctx.completed_process = subprocess.run(
                ["python3", self.filename, *args],
                capture_output=True,
                text=True,
                **kwargs,
            )
            return None

        return self._step(True, action)

    def match_stdout(self, match, score_out_of, score_matches, score_does_not_match):
        def action(ctx):
            ok = ctx.completed_process.stdout == match
            return Result(
                out_of=score_out_of,
                score=score_matches if ok else score_does_not_match,
                feedback=f"stdout {'matches' if ok else 'does not match'} {match!r}",
            )

        return self._step(True, action)

    def ask_for_score(self, question, out_of):
        """``question`` may be a plain string, or a callable taking the
        Marker's own RunContext -- e.g. to quote the script's own stdout
        back in the question text. Either way it is not actually called
        until the second pass.
        """

        def action(ctx):
            text = question(ctx) if callable(question) else question
            return Question(text, out_of)

        return self._step(False, action)


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
