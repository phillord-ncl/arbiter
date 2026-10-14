from tent_arbiter.core import Exercise, Result, RunMarker
from tent_arbiter.matchers import Exact


SIMPLE_RUBRIC_TOML = """
[assignment]
title = "Hello World"
description = "description.md"
points_possible = 12
submission_types = ["online_upload"]
published = false

[[criteria]]
id = "correctness"
description = "Correctness"
points = 10

[[criteria.ratings]]
id = "full"
description = "Prints exactly \\"Hello World\\""
points = 10

[[criteria.ratings]]
id = "none"
description = "Does not"
points = 0

[[criteria]]
id = "style"
description = "Style"
points = 2

[[criteria.ratings]]
id = "full"
description = "Readable"
points = 2

[[criteria.ratings]]
id = "none"
description = "Not readable"
points = 0
"""


def _write_rubric_toml(tmp_path):
    path = tmp_path / "hello_world.rubric.toml"
    path.write_text(SIMPLE_RUBRIC_TOML)
    return str(path)


def _write_script(tmp_path, name, output):
    path = tmp_path / name
    path.write_text(f'print("{output}")\n')
    return path


def _collecting_ask_interactively(asked):
    def ask_interactively(question):
        asked.append(question)
        return Result(out_of=question.out_of, score=question.out_of, feedback="asked")

    return ask_interactively


def test_match_stdout_reads_its_own_markers_python_output(tmp_path):
    script = _write_script(tmp_path, "a.py", "A")
    marker = RunMarker(str(tmp_path))
    marker.python(script.name).match_stdout(5, Exact("A\n", "output correct", 5))

    Exercise(marker).run(ask_interactively=lambda q: None)

    [result] = marker.results
    assert result.score == 5


def test_match_stdout_detects_a_mismatch(tmp_path):
    script = _write_script(tmp_path, "a.py", "A")
    marker = RunMarker(str(tmp_path))
    marker.python(script.name).match_stdout(5, Exact("not-A\n", "output correct", 5))

    Exercise(marker).run(ask_interactively=lambda q: None)

    [result] = marker.results
    assert result.score == 0


def test_two_run_markers_do_not_leak_context(tmp_path):
    """The worked example notes.org asked for: two RunMarkers in one
    Exercise, where the second Marker's python() step runs (in the first,
    mechanical pass) *after* the first Marker's own python() step but
    *before* the first Marker's deferred judgement step is finally asked
    (in the second pass).

    If RunContext were shared Exercise-wide -- as the original sketch
    literally wrote it, with a single ``ctx = RunContext()`` outside any
    per-Marker loop -- marker_b's python() would overwrite
    ``ctx.completed_process`` before marker_a's question is ever asked, so
    the question would quote marker_b's stdout instead of marker_a's own.
    Per-Marker RunContext (what Exercise.run() actually does) keeps them
    apart.
    """
    script_a = _write_script(tmp_path, "a.py", "A")
    script_b = _write_script(tmp_path, "b.py", "B")

    marker_a = RunMarker(str(tmp_path))
    marker_a.python(script_a.name).ask_for_score(
        lambda ctx: f"rate this output: {ctx.completed_process.stdout!r}", 5
    )

    marker_b = RunMarker(str(tmp_path))
    marker_b.python(script_b.name).match_stdout(5, Exact("B\n", "output correct", 5))

    asked = []
    Exercise(marker_a, marker_b).run(
        ask_interactively=_collecting_ask_interactively(asked)
    )

    # marker_b's own mechanical check ran correctly against its own script.
    [result_b] = marker_b.results
    assert result_b.score == 5

    # marker_a's question -- asked in the *second* pass, after marker_b's
    # python() has already run in the first pass -- still quotes marker_a's
    # own stdout, not marker_b's.
    [question] = asked
    assert "'A\\n'" in question.question
    assert "B" not in question.question


def test_check_consistent_with_rubric_toml_passes_when_points_match(tmp_path):
    rubric_path = _write_rubric_toml(tmp_path)
    script = _write_script(tmp_path, "a.py", "Hello World")

    correctness = RunMarker(str(tmp_path), criterion="correctness")
    correctness.python(script.name).match_stdout(10, Exact("Hello World\n", "output correct", 10))

    style = RunMarker(str(tmp_path), criterion="style")
    style.python(script.name).ask_for_score("rate the style", 2)

    exercise = Exercise(correctness, style)
    assert exercise.check_consistent_with_rubric_toml(rubric_path) == []


def test_check_consistent_with_rubric_toml_flags_a_points_mismatch(tmp_path):
    rubric_path = _write_rubric_toml(tmp_path)
    script = _write_script(tmp_path, "a.py", "Hello World")

    # "correctness" is worth 10 in the rubric, but this marker only
    # awards 5 -- a drift the static check must catch without running
    # anything.
    correctness = RunMarker(str(tmp_path), criterion="correctness")
    correctness.python(script.name).match_stdout(5, Exact("Hello World\n", "output correct", 5))

    style = RunMarker(str(tmp_path), criterion="style")
    style.python(script.name).ask_for_score("rate the style", 2)

    exercise = Exercise(correctness, style)
    [problem] = exercise.check_consistent_with_rubric_toml(rubric_path)
    assert "correctness" in problem
    assert "5" in problem and "10" in problem


def test_check_consistent_with_rubric_toml_flags_an_unknown_criterion(tmp_path):
    rubric_path = _write_rubric_toml(tmp_path)
    script = _write_script(tmp_path, "a.py", "Hello World")

    marker = RunMarker(str(tmp_path), criterion="not-a-real-criterion")
    marker.python(script.name).match_stdout(10, Exact("Hello World\n", "output correct", 10))

    # Also flags "correctness"/"style" as unmarked -- nothing in this
    # Exercise claims either -- which is correct, not just noise from
    # this test's setup.
    problems = Exercise(marker).check_consistent_with_rubric_toml(rubric_path)
    assert any("not-a-real-criterion" in p for p in problems)


def test_check_consistent_with_rubric_toml_flags_a_criterion_with_no_marker(tmp_path):
    rubric_path = _write_rubric_toml(tmp_path)
    script = _write_script(tmp_path, "a.py", "Hello World")

    # Only "correctness" has a marker -- "style" (in the rubric) does
    # not, so nothing would ever mark it.
    correctness = RunMarker(str(tmp_path), criterion="correctness")
    correctness.python(script.name).match_stdout(10, Exact("Hello World\n", "output correct", 10))

    [problem] = Exercise(correctness).check_consistent_with_rubric_toml(rubric_path)
    assert "style" in problem


def test_question_context_has_output_and_files(tmp_path):
    script = tmp_path / "s.py"
    script.write_text("import sys\nprint('out')\nprint('err', file=sys.stderr)\n")
    (tmp_path / "arb-results.toml").write_text("")
    marker = RunMarker(str(tmp_path))
    marker.python(script.name).ask_for_score("q", 5)
    asked = []

    def ask(question):
        asked.append(question)
        return Result(out_of=question.out_of, score=0, feedback="")

    Exercise(marker).run(ask_interactively=ask)
    context = {item.title: item for item in asked[0].context}
    assert context["stdout"].text == "out\n"
    assert context["stderr"].text == "err\n"
    assert context["s.py"].path == str(script)
    assert "arb-results.toml" not in context
    assert not asked[0].undecided


def test_question_after_or_else_is_marked_undecided(tmp_path):
    from tent_arbiter.matchers import Exact

    script = tmp_path / "s.py"
    script.write_text("print('x')\n")
    marker = RunMarker(str(tmp_path))
    marker.python(script.name).match_stdout(
        5, Exact("nope", "exact", 5)
    ).or_else().ask_for_score("q", 5)
    asked = []

    def ask(question):
        asked.append(question)
        return Result(out_of=question.out_of, score=0, feedback="")

    Exercise(marker).run(ask_interactively=ask)
    assert asked[0].undecided


def test_question_session_tracks_progress(tmp_path):
    script = tmp_path / "s.py"
    script.write_text("print('x')\n")
    marker = RunMarker(str(tmp_path), criterion="c")
    marker.python(script.name).match_stdout(
        3, Exact("x\n", "ok", 3)
    ).ask_for_score("one", 4).ask_for_score("two", 5)
    sessions = []

    def ask(question):
        sessions.append(question.session)
        return Result(out_of=question.out_of, score=1, feedback="")

    Exercise(marker).run(ask_interactively=ask, label="alice")
    assert [(s.label, s.criterion, s.score, s.out_of, s.position, s.total)
            for s in sessions] == [
        ("alice", "c", 3, 12, 1, 2),
        ("alice", "c", 4, 12, 2, 2),
    ]


def test_marker_title_is_what_the_session_shows(tmp_path):
    script = tmp_path / "s.py"
    script.write_text("print('x')\n")
    marker = RunMarker(str(tmp_path), criterion="c", title="The nice name")
    marker.python(script.name).ask_for_score("q", 5)
    sessions = []

    def ask(question):
        sessions.append(question.session)
        return Result(out_of=question.out_of, score=1, feedback="")

    Exercise(marker).run(ask_interactively=ask)
    assert sessions[0].criterion == "The nice name"
    assert marker.criterion == "c"


RUBRIC = """\
[assignment]
title = "A"
description = "a.md"
points_possible = 5

[[criteria]]
id = "c"
description = "Nice name"
long_description = "What they were asked."
points = 5
"""


def _rubric_exercise(tmp_path, **marker_kwargs):
    (tmp_path / "r.rubric.toml").write_text(RUBRIC)
    (tmp_path / "a.md").write_text("The whole assignment\n")
    marker = RunMarker(str(tmp_path), criterion="c", **marker_kwargs)
    marker.ask_for_score("q", 5)
    exercise = Exercise(marker)
    exercise.apply_rubric(str(tmp_path / "r.rubric.toml"))
    return exercise


def _first_session(exercise):
    sessions = []

    def ask(question):
        sessions.append(question.session)
        return Result(out_of=question.out_of, score=1, feedback="")

    exercise.run(ask_interactively=ask)
    return sessions[0]


def test_rubric_supplies_name_task_and_assignment(tmp_path):
    session = _first_session(_rubric_exercise(tmp_path))
    assert session.criterion == "Nice name"
    assert session.task == "What they were asked."
    assert session.assignment == "The whole assignment\n"


def test_marker_title_and_task_beat_the_rubric(tmp_path):
    session = _first_session(
        _rubric_exercise(tmp_path, title="Mine", task="My task")
    )
    assert (session.criterion, session.task) == ("Mine", "My task")


def test_missing_assignment_file_is_fine(tmp_path):
    exercise = _rubric_exercise(tmp_path)
    (tmp_path / "a.md").unlink()
    exercise.assignment_text = None
    exercise.apply_rubric(str(tmp_path / "r.rubric.toml"))
    assert _first_session(exercise).assignment is None
