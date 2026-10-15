"""Plan/run execution model.

Every ``Marker`` builder method records a ``Step`` rather than acting on
it; nothing runs until ``Exercise.run()``. ``run()`` makes two passes over
the whole tree: every mechanical step first, in document order within each
``Marker``; only then every queued judgement step, one at a time.
"""

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple, Union
import os
import subprocess

from arbiter import checks, submission
from arbiter import scripts as marker_scripts
from tent_pole.rubric import load_rubric_toml


@dataclass
class Result:
    out_of: float
    score: float
    feedback: str
    decided_by: str = "mechanical"
    ## Set on a human answer: which question it answers, so a later run can
    ## find it again (see Exercise.run). None for a mechanical result.
    question_id: Optional[str] = None


class RestartMarking(Exception):
    """Raised by an ask hook to throw away this attempt's results and mark
    the submission again from the start (after the marker has edited it,
    say). Answers already given come back as the stored ones."""


UNDECIDED_NOTE = "(The automatic checks could not decide this one.)"


@dataclass
class ContextItem:
    """One titled block shown alongside a question: literal ``text``, or
    the ``path`` of a file for a viewer to display."""

    title: str
    text: Optional[str] = None
    path: Optional[str] = None
    ## A file the plain prompt should print in full (one a step chose to
    ## show), not just offer to a viewer.
    inline: bool = False


@dataclass
class Session:
    """Where a marking session has got to, for a UI to show alongside a
    question. ``label`` is whatever names the submission (for now its
    directory name); ``score`` is the marks awarded so far and ``out_of``
    the most the whole Exercise can award."""

    label: str
    criterion: Optional[str]
    score: float
    out_of: float
    position: int
    total: int
    ## (criterion, Result) for everything marked so far, automatic or
    ## human, in the order it was decided.
    marked: List[Tuple[Optional[str], Result]] = field(default_factory=list)
    ## What the student was asked: this criterion's task text, and the
    ## whole assignment's description. Either may be None.
    task: Optional[str] = None
    assignment: Optional[str] = None
    ## The submission directory, and the marker-* commands that can be run
    ## in it (empty if the Exercise uses none).
    directory: Optional[str] = None
    commands: List[str] = field(default_factory=list)


@dataclass
class Question:
    question: str
    out_of: float
    context: List[ContextItem] = field(default_factory=list)
    ## Set by Exercise.run just before the question is asked, not by the
    ## step that builds it -- a step knows nothing of the wider session.
    session: Optional[Session] = None
    ## True when the automatic checks could not decide and this question
    ## took over (a step after or_else()); a UI may mention it, quietly.
    undecided: bool = False
    ## The only scores a marker may enter (e.g. 0, 0.5, 1) -- None means
    ## any number from 0 to ``out_of``. A deduction is just a scale that
    ## goes below zero, e.g. choices of (0, -1) with an out_of of 0.
    choices: Optional[List[float]] = None
    ## What the marker answered to this question on an earlier attempt or
    ## run, if anything, for a UI to show and pre-fill. Only set if it is
    ## still an acceptable answer.
    previous: Optional[Result] = None

    def accepts(self, score):
        if self.choices is not None:
            return score in self.choices
        return 0 <= score <= self.out_of

    def allowed(self):
        """What may be entered, as text for a prompt."""
        if self.choices is not None:
            return "one of " + ", ".join(format(c, "g") for c in self.choices)
        return "a number from 0 to {}".format(format(self.out_of, "g"))


class _Undecided:
    """What a scoring step's action returns when it could not decide."""

    def __repr__(self):
        return "UNDECIDED"


UNDECIDED = _Undecided()


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
    ## Set by Marker.or_else(): this step runs only if the scoring step
    ## before it returned UNDECIDED, and is its alternative, not an
    ## addition, so max_score() counts the pair once.
    fallback: bool = False
    ## What a step that returned UNDECIDED scores if no fallback follows --
    ## a Result, or a function of the Marker's RunContext that makes one.
    undecided_result: Optional[Union[Result, Callable[["RunContext"], Result]]] = None


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

    def __init__(self):
        ## What the mechanical checks found, in words, for a human question
        ## after them to show.
        self.notes = []
        ## What the show_* steps chose to put in front of a human question.
        self.shown = []


class Marker:
    def __init__(self, criterion=None, title=None, task=None, part=None, formative=False):
        ## Which part of the assignment this Marker belongs to, for
        ## subtotals; None means not in any part.
        self.part = part
        ## A formative Marker is recorded and shown but counts for nothing:
        ## it adds nothing to the Exercise's score or total available.
        self.formative = formative
        ## A human-readable name for what this Marker marks, shown to
        ## whoever is marking; ``criterion`` stays the stable id.
        self.title = title
        ## What the student was asked, for this Marker. Explicit, or
        ## filled in from the rubric by Exercise.apply_rubric.
        self.task = task
        self.rubric_title = None
        self.rubric_task = None
        ## Which tent-pole .rubric.toml criterion (by its own "id", not
        ## a Canvas id -- those aren't stable, see tent-pole's
        ## rubric.py) this Marker's results count towards. None means
        ## "not tied to a criterion", e.g. a Marker used standalone,
        ## outside Exercise.check_consistent_with_rubric_toml.
        self.criterion = criterion
        self.steps: List[Step] = []
        self.results: List[Result] = []
        self._next_is_fallback = False

    @property
    def name(self):
        return self.title or self.rubric_title or self.criterion

    @property
    def task_text(self):
        return self.task or self.rubric_task

    def _step(self, mechanical, action, out_of=None, undecided_result=None):
        self.steps.append(
            Step(
                mechanical,
                action,
                out_of,
                fallback=self._next_is_fallback,
                undecided_result=undecided_result,
            )
        )
        self._next_is_fallback = False
        return self

    def or_else(self):
        """Make the next step a fallback: it runs only if the scoring step
        before it could not decide (a matcher-based step that matched
        nothing), e.g. ``.match_stdout(...).or_else().ask_for_score(...)``.
        """
        if not self.steps:
            raise ValueError("or_else() needs a step before it")
        self._next_is_fallback = True
        return self

    def result(self, result):
        self.results.append(result)
        return self

    def max_score(self):
        """Total points this Marker can award, from its own steps'
        declared out_of values -- static, no step is actually run. A
        fallback step is an alternative to the step before it, so the pair
        counts as the larger of the two."""
        total = 0
        last = 0
        for step in self.steps:
            if step.out_of is None:
                continue
            if step.fallback:
                total += max(0, step.out_of - last)
                last = max(last, step.out_of)
            else:
                total += step.out_of
                last = step.out_of
        return total


class DirectoryMarker(Marker):
    """A Marker whose checks run against a submission *directory* --
    most student submissions pre-define their own entry-point filename
    (the assignment's own convention, e.g. "hello_world.py"), so a
    Marker is pointed at the directory once and each step says which
    file within it to act on, rather than a Marker being tied to one
    fixed file."""

    def __init__(self, directory, criterion=None, title=None, task=None, **kwargs):
        super().__init__(criterion=criterion, title=title, task=task, **kwargs)
        self.directory = directory

    @property
    def root(self):
        """Where the student's project is. A Marker is pointed at it
        directly (the Exercise's ``root`` has already been applied)."""
        return self.directory


    def _check(self, out_of, check):
        """A scoring step from ``check(root) -> (ok, message)`` (see
        arbiter.checks). Passing scores ``out_of``; otherwise the step is
        undecided -- 0 unless an ``or_else()`` step follows -- and either
        way ``message`` is noted for a human question to show."""

        def action(ctx):
            ok, message = check(self.root)
            ctx.notes.append(message)
            if ok:
                return Result(out_of, out_of, message)
            ctx.last_message = message
            return UNDECIDED

        return self._step(
            True,
            action,
            out_of=out_of,
            undecided_result=lambda ctx: Result(out_of, 0, ctx.last_message),
        )

    def file_exists(self, out_of, *patterns, require_all=False):
        """Score ``out_of`` if the submission has a file matching any of
        the case-insensitive globs -- or each of them, with
        ``require_all`` (a pattern with no ``/`` matches a file's name
        wherever it is)."""
        return self._check(
            out_of, lambda root: checks.file_exists(root, patterns, require_all)
        )

    def file_contains(self, out_of, patterns, regexp):
        """Score ``out_of`` if a file matching ``patterns`` (a glob or a
        list of them) has text matching ``regexp``, ignoring case."""
        return self._check(
            out_of,
            lambda root: checks.file_contains(root, _as_list(patterns), regexp),
        )

    def files_match(self, out_of, patterns, regexp):
        """Score ``out_of`` if any line of any file matching ``patterns``
        matches ``regexp`` (case-sensitive; use ``(?i)`` for otherwise)."""
        return self._check(
            out_of, lambda root: checks.files_match(root, _as_list(patterns), regexp)
        )

    def word_count(self, out_of, patterns, low, high, under=0.0, over=0.0):
        """Score ``out_of`` if the words in the files matching
        ``patterns`` number from ``low`` to ``high``, widened by
        ``under`` below ``low`` and ``over`` above ``high`` (0.1 is 10%)."""
        return self._check(
            out_of,
            lambda root: checks.word_count(
                root, _as_list(patterns), low, high, under, over
            ),
        )

    def git_commit_count(self, out_of, at_least):
        return self._check(
            out_of, lambda root: checks.git_commit_count(root, at_least)
        )

    def git_log_matches(self, out_of, regexp, messages=True, diffs=True):
        """Score ``out_of`` if any commit's message (``messages``) or
        changed lines (``diffs``) match ``regexp``, ignoring case."""
        return self._check(
            out_of, lambda root: checks.git_log_matches(root, regexp, messages, diffs)
        )

    def note_unexpected_hidden(self, allowed=(".git", ".gitignore")):
        """Score nothing, but note any hidden file or directory
        (``.venv``, ``.idea``...) in the submission that is not in
        ``allowed``, for a later question to show."""

        def action(ctx):
            found = submission.unexpected_hidden(self.root, allowed)
            ctx.notes.append(
                "Unexpected hidden files: " + ", ".join(found)
                if found
                else "No unexpected hidden files"
            )
            return None

        return self._step(True, action)

    def show_command(self, title, command):
        """Run ``command`` (a list of words, in the project root) and show
        its output to a later human question under ``title``."""

        def action(ctx):
            ctx.shown.append(ContextItem(title, text=_run_for_display(command, self.root)))
            return None

        return self._step(True, action)

    def show_git_log(self, title="Git log", *args):
        """Show the project's ``git log`` (``args`` default to a dated
        ``--stat`` listing)."""
        args = args or ("--stat", "--date=short")

        def action(ctx):
            if not checks.has_git(self.root):
                text = "(no .git directory)"
            else:
                result = checks._git(self.root, "log", *args)
                text = result[1] if result and result[0] == 0 else "(could not read the git history)"
            ctx.shown.append(ContextItem(title, text=text))
            return None

        return self._step(True, action)

    def show_files(self, *patterns):
        """Show each file matching any of ``patterns`` (see
        ``file_exists``), one tab each, which a viewer can open."""

        def action(ctx):
            found = submission.find(self.root, *patterns)
            if not found:
                ctx.shown.append(
                    ContextItem(
                        "Files",
                        text="(no file matching {})".format(" or ".join(patterns)),
                    )
                )
            for rel in found:
                ctx.shown.append(
                    ContextItem(rel, path=os.path.join(self.root, rel), inline=True)
                )
            return None

        return self._step(True, action)


def _run_for_display(command, directory):
    try:
        run = subprocess.run(
            command,
            cwd=directory,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return "(could not run {}: {})".format(" ".join(command), e)
    return run.stdout + (("\n" + run.stderr) if run.stderr else "")


def _as_list(patterns):
    return [patterns] if isinstance(patterns, str) else list(patterns)


class RunMarker(DirectoryMarker):
    def _submission_files(self):
        """The student's own files, as path context items (see
        arbiter.submission.walk for what is left out)."""
        return [
            ContextItem(rel, path=os.path.join(self.directory, rel))
            for rel in submission.walk(self.directory)
        ]

    def python(self, entry_point, *args, venv=False, **kwargs):
        """Run a script and capture its output. With ``venv=True`` it runs
        through ``marker-python``, so in the submission's own venv with its
        requirements installed -- which needs the Exercise's scripts to
        have been written (``Exercise.prepare``)."""

        def action(ctx):
            if venv:
                command = [
                    marker_scripts.script_path(self.root, "marker-python"),
                    entry_point,
                    *args,
                ]
            else:
                command = ["python3", entry_point, *args]
            ctx.completed_process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=self.root,
                **kwargs,
            )
            return None

        return self._step(True, action)

    def match_stdout(self, out_of, *matchers):
        """Score the script's stdout with the first of ``matchers`` (see
        arbiter.matchers) that matches it. If none do the step is
        undecided: a following ``or_else()`` step takes over, otherwise it
        scores 0."""

        def action(ctx):
            stdout = ctx.completed_process.stdout
            for matcher in matchers:
                if matcher.matches(stdout):
                    return matcher.result(out_of)
            return UNDECIDED

        return self._step(
            True,
            action,
            out_of=out_of,
            undecided_result=Result(
                out_of=out_of, score=0, feedback="stdout did not match"
            ),
        )

    def ask_for_score(self, question, out_of, choices=None):
        """``question`` may be a plain string, or a callable taking the
        Marker's own RunContext -- e.g. to quote the script's own stdout
        back in the question text. Either way it is not actually called
        until the second pass. ``choices``, if given, are the only scores
        the marker may enter, in place of any number up to ``out_of``.
        """

        after_or_else = self._next_is_fallback

        def action(ctx):
            text = question(ctx) if callable(question) else question
            context = []
            if ctx.notes:
                context.append(ContextItem("Automatic checks", text="\n".join(ctx.notes)))
            context.extend(ctx.shown)
            process = getattr(ctx, "completed_process", None)
            if process is not None:
                context.append(ContextItem("stdout", text=process.stdout))
                context.append(ContextItem("stderr", text=process.stderr))
            if not ctx.shown:
                context.extend(self._submission_files())
            return Question(
                text,
                out_of,
                context,
                undecided=after_or_else,
                choices=list(choices) if choices is not None else None,
            )

        return self._step(False, action, out_of=out_of)


def _undecided_result(step, ctx):
    result = step.undecided_result
    return result(ctx) if callable(result) else result


class Exercise:
    def __init__(self, *markers):
        self.markers = list(markers)
        self.assignment_text = None
        ## The student's project directory, where the Markers look. None
        ## until something that knows it (arb.toml's loader) sets it.
        self.directory = None
        ## Whether to write marker-* scripts into each submission, which
        ## extra ones (marker_scripts.Script), and the venv's Python version.
        self.use_scripts = False
        self.scripts = []
        self.python_version = None

    def all_scripts(self):
        return marker_scripts.BUILTIN + self.scripts

    def prepare(self, directory):
        """Write the marker-* scripts into ``directory`` (the project
        directory, where its ``requirements.txt`` is), if this Exercise
        uses them. Raises ``arbiter.scripts.ScriptClash`` (writing nothing)
        if the submission already has something of that name."""
        if self.use_scripts:
            marker_scripts.write_scripts(
                directory, self.all_scripts(), self.python_version
            )

    def apply_rubric(self, path):
        """Take what a marker is called, and what the student was asked,
        from the rubric's criteria (a marker's own ``title`` and ``task``
        still win), and the assignment's description from the markdown
        file the rubric names, if that file exists."""
        parsed = load_rubric_toml(path)
        criteria = {c["id"]: c for c in parsed.get("criteria", [])}
        for marker in self.markers:
            criterion = criteria.get(marker.criterion)
            if criterion is not None:
                marker.rubric_title = criterion.get("description")
                marker.rubric_task = (criterion.get("long_description") or "").strip() or None
        description = parsed.get("assignment", {}).get("description")
        if description:
            md = os.path.join(os.path.dirname(os.path.abspath(path)), description)
            try:
                with open(md) as f:
                    self.assignment_text = f.read()
            except OSError:
                pass

    def counted(self):
        """The Markers that count towards the total (not the formative)."""
        return [m for m in self.markers if not m.formative]

    def max_score(self):
        return sum(marker.max_score() for marker in self.counted())

    def score(self):
        return sum(r.score for marker in self.counted() for r in marker.results)

    def parts(self):
        """``[(part, score, out_of)]`` for each named part, in the order
        each first appears; Markers with no part are left out."""
        names = []
        for marker in self.counted():
            if marker.part is not None and marker.part not in names:
                names.append(marker.part)
        return [
            (
                name,
                sum(r.score for m in self.counted() if m.part == name for r in m.results),
                sum(m.max_score() for m in self.counted() if m.part == name),
            )
            for name in names
        ]

    def run(
        self,
        ask_interactively,
        checkpoint=None,
        label="",
        directory=None,
        previous=None,
    ):
        """``checkpoint``, if given, is called with this Exercise after the
        mechanical pass and after every human answer, so results can be
        saved as they happen rather than only at the end. ``label`` names
        the submission, and ``directory`` is where it is, in each question's
        ``session``.

        ``previous`` maps a question id to the human answer stored by an
        earlier run. Every mechanical step is run afresh each time -- they
        are cheap and the files may have changed -- but a question shows
        its stored answer, pre-filled. Answers not yet asked again stay in
        ``self.stored`` so checkpoints do not lose them. An ask hook that
        raises ``RestartMarking`` starts the whole attempt again."""
        self.stored = dict(previous or {})
        self.restarts = 0
        while True:
            self.given = {}
            for marker in self.markers:
                marker.results = []
            try:
                self._attempt(ask_interactively, checkpoint, label, directory)
                return self
            except RestartMarking:
                self.restarts += 1
                self.stored.update(self.given)

    def _attempt(self, ask_interactively, checkpoint, label, directory):
        questions = []  # [(marker, step, ctx, id)], deferred to the second pass
        for number, marker in enumerate(self.markers):
            ctx = RunContext()
            held = None  # last step to return UNDECIDED, awaiting a fallback
            for position, step in enumerate(marker.steps):
                if step.fallback:
                    if held is None:
                        continue
                    held = None
                elif held is not None:
                    marker.result(_undecided_result(held, ctx))
                    held = None
                if step.mechanical:
                    result = step.action(ctx)
                    if result is UNDECIDED:
                        held = step
                    elif result is not None:
                        marker.result(result)
                else:
                    qid = "{}:{}".format(marker.criterion or "marker{}".format(number + 1), position)
                    questions.append((marker, step, ctx, qid))
            if held is not None:
                marker.result(_undecided_result(held, ctx))
        if checkpoint is not None:
            checkpoint(self)
        for position, (marker, step, ctx, qid) in enumerate(questions, 1):
            question = step.action(ctx)
            stored = self.stored.get(qid)
            if stored is not None and question.accepts(stored.score):
                question.previous = stored
            question.session = Session(
                label,
                marker.name,
                self.score(),
                self.max_score(),
                position,
                len(questions),
                [(m.name, r) for m in self.markers for r in m.results],
                marker.task_text,
                self.assignment_text,
                directory,
                [s.name for s in self.all_scripts()] if self.use_scripts else [],
            )
            answer = ask_interactively(question)
            answer.decided_by = "human"
            answer.question_id = qid
            marker.result(answer)
            self.given[qid] = answer
            self.stored.pop(qid, None)
            if checkpoint is not None:
                checkpoint(self)

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
