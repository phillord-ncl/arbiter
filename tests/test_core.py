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
