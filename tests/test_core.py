from tent_arbiter.core import Exercise, Result, RunMarker


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
    marker = RunMarker(str(script))
    marker.python().match_stdout("A\n", 5, 5, 0)

    Exercise(marker).run(ask_interactively=lambda q: None)

    [result] = marker.results
    assert result.score == 5


def test_match_stdout_detects_a_mismatch(tmp_path):
    script = _write_script(tmp_path, "a.py", "A")
    marker = RunMarker(str(script))
    marker.python().match_stdout("not-A\n", 5, 5, 0)

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

    marker_a = RunMarker(str(script_a))
    marker_a.python().ask_for_score(
        lambda ctx: f"rate this output: {ctx.completed_process.stdout!r}", 5
    )

    marker_b = RunMarker(str(script_b))
    marker_b.python().match_stdout("B\n", 5, 5, 0)

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
