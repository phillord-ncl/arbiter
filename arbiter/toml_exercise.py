"""Build an ``Exercise`` from an ``arb.toml`` instead of an ``arb.py``.

A declarative alternative for the common case -- run a script, score its
output with matchers, ask a human about the rest. Anything it cannot say
still needs an ``arb.py``. Layout::

    rubric = "greeting.rubric.toml"      # optional, relative to this file
    python_version = "3.14"              # optional: the marker-venv's Python
    root = "project"                     # optional: the student's project, a
                                         # directory inside each submission
                                         # (default: the submission itself;
                                         # ``--root`` on the command line wins)

    [[script]]                           # optional: a marker-* command, run in
    name = "marker-run"                  # the submission's venv, as well as the
    command = ["python", "greeting.py"]  # always-present marker-python/-pip

Declaring a ``[[script]]`` or ``python_version``, or a step with
``venv = true``, makes arbiter write the marker-* scripts into each
submission before marking.

    [[marker]]
    criterion = "correctness"            # a .rubric.toml criterion id
    title = "Hello World output"         # optional: what the marker is shown
                                         # (default: the rubric's description)
    task = "Print a greeting"            # optional: what the student was asked
                                         # (default: the rubric's long_description)
    part = "Part 1"                      # optional: group markers for subtotals
    formative = true                     # optional: recorded, but counts for nothing

    [[marker.step]]
    type = "python"                      # entry point, in the submission
    entry_point = "greeting.py"
    args = ["Ada"]                       # optional
    venv = true                          # optional: run in marker-venv

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
    choices = [0, 5, 10]                 # optional: the only scores allowed
                                         # (negative ones make a deduction,
                                         # with out_of = 0)
    full_feedback = "Correct"            # optional: offered for full marks
    require_feedback = true              # optional: feedback needed unless
                                         # full marks

    type = "ask_for_feedback"            # no score, only feedback
    question = "Any overall comments for the student? "
    require_feedback = true              # optional

Mechanical checks (see arbiter.checks) score full marks when they pass and
are otherwise undecided, so ``or_else = true`` on a following step lets a
human decide, shown what the check found::

    type = "file_exists"                 # also: file_contains, files_match,
    files = ["README.md", "README"]      #   word_count, git_commit_count,
    out_of = 1                           #   git_log_matches,
                                         #   note_unexpected_hidden
    # Any of these may set  feedback = "..."  (what the student is told on a
    # pass) and  fail_feedback = "..."  (on a zero, when no later or_else
    # step decides); the default for both is what the check found.
    # file_exists: optionally require = "all" (a file for each of files)
    # file_contains / files_match:  files = [...], pattern = "regexp"
    # word_count:     files = [...], low = 300, high = 500, over = 0.1
    #                 (under / over: fraction allowed below low / above high)
    # git_commit_count:  at_least = 4
    # git_log_matches:   pattern = "regexp", messages = true, diffs = true
    # note_unexpected_hidden:  allowed = [".git", ".gitignore"]  (no out_of)

Steps that score nothing but choose what a later question shows (when any
are used, the question shows these instead of listing every file)::

    type = "show_git_log"                # optional: title, args = ["--stat"]
    type = "show_files"                  # files = ["doc/*.md", "*.py"]
    type = "show_command"                # title = "...", command = ["git", "status"]

A question may use ``{stdout}`` and ``{stderr}`` (from the marker's own
``python`` step; empty if there was none) and ``{file}``, the contents of
the step's optional ``file`` (in the submission).
"""

import os
import tomllib

from arbiter.core import Exercise, RunMarker
from arbiter.matchers import Always, Exact, RegexpAny, SubString
from arbiter.scripts import Script


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


def _files(spec):
    files = spec["files"]
    return [files] if isinstance(files, str) else list(files)


def _fb(spec):
    return dict(
        feedback=spec.get("feedback"), fail_feedback=spec.get("fail_feedback")
    )


CHECKS = {
    "file_exists": lambda m, s: m.file_exists(
        s["out_of"], *_files(s), require_all=s.get("require", "any") == "all",
        **_fb(s)
    ),
    "file_contains": lambda m, s: m.file_contains(
        s["out_of"], _files(s), s["pattern"], **_fb(s)
    ),
    "files_match": lambda m, s: m.files_match(
        s["out_of"], _files(s), s["pattern"], **_fb(s)
    ),
    "word_count": lambda m, s: m.word_count(
        s["out_of"], _files(s), s["low"], s["high"], s.get("under", 0.0), s.get("over", 0.0),
        **_fb(s)
    ),
    "git_commit_count": lambda m, s: m.git_commit_count(
        s["out_of"], s["at_least"], **_fb(s)
    ),
    "git_log_matches": lambda m, s: m.git_log_matches(
        s["out_of"], s["pattern"], s.get("messages", True), s.get("diffs", True),
        **_fb(s)
    ),
    "note_unexpected_hidden": lambda m, s: m.note_unexpected_hidden(
        tuple(s.get("allowed", (".git", ".gitignore")))
    ),
    "show_git_log": lambda m, s: m.show_git_log(s.get("title", "Git log"), *s.get("args", [])),
    "show_files": lambda m, s: m.show_files(*_files(s)),
    "show_command": lambda m, s: m.show_command(s["title"], list(s["command"])),
}


def _add_step(marker, spec, where, directory):
    kind = spec.get("type")
    if spec.get("or_else", False):
        marker.or_else()
    try:
        if kind == "python":
            marker.python(
                spec["entry_point"],
                *spec.get("args", []),
                venv=spec.get("venv", False),
            )
        elif kind == "match_stdout":
            matchers = [
                _matcher(m, "{} match {}".format(where, i + 1))
                for i, m in enumerate(spec.get("match", []))
            ]
            marker.match_stdout(spec["out_of"], *matchers)
        elif kind in CHECKS:
            CHECKS[kind](marker, spec)
        elif kind == "ask_for_feedback":
            marker.ask_for_feedback(
                _question(spec, directory),
                require_feedback=spec.get("require_feedback", False),
            )
        elif kind == "ask_for_score":
            marker.ask_for_score(
                _question(spec, directory),
                spec["out_of"],
                spec.get("choices"),
                full_feedback=spec.get("full_feedback"),
                require_feedback=spec.get("require_feedback", False),
            )
        else:
            raise ArbTomlError(
                "{}: unknown step type {!r} (want one of python, "
                "match_stdout, ask_for_score, ask_for_feedback, {})".format(
                    where, kind, ", ".join(CHECKS)
                )
            )
    except KeyError as e:
        raise ArbTomlError("{}: missing {}".format(where, e)) from None


def load_exercise(path, submission_dir, root=None):
    """Return ``(exercise, rubric_path)``; ``rubric_path`` is None if the
    file names no rubric. ``exercise.directory`` is the project directory:
    ``root`` (else the file's own ``root``, else none) inside
    ``submission_dir``."""
    with open(path, "rb") as f:
        data = tomllib.load(f)
    root = root or data.get("root")
    if root:
        submission_dir = os.path.join(submission_dir, root)

    markers = []
    for i, spec in enumerate(data.get("marker", [])):
        where = "marker {}".format(i + 1)
        marker = RunMarker(
            submission_dir,
            criterion=spec.get("criterion"),
            title=spec.get("title"),
            task=spec.get("task"),
            part=spec.get("part"),
            formative=spec.get("formative", False),
        )
        for j, step in enumerate(spec.get("step", [])):
            _add_step(marker, step, "{} step {}".format(where, j + 1), submission_dir)
        markers.append(marker)
    if not markers:
        raise ArbTomlError("{} defines no [[marker]]".format(path))

    exercise = Exercise(*markers)
    exercise.directory = submission_dir
    exercise.python_version = data.get("python_version")
    for i, spec in enumerate(data.get("script", [])):
        try:
            exercise.scripts.append(Script(spec["name"], list(spec["command"])))
        except KeyError as e:
            raise ArbTomlError("script {}: missing {}".format(i + 1, e)) from None
    exercise.use_scripts = bool(
        exercise.scripts
        or exercise.python_version
        or any(
            step.get("venv", False)
            for spec in data.get("marker", [])
            for step in spec.get("step", [])
        )
    )

    rubric = data.get("rubric")
    if rubric is not None:
        rubric = os.path.join(os.path.dirname(os.path.abspath(path)), rubric)
    return exercise, rubric
