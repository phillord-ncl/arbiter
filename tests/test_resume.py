import asyncio
import tomllib

import pytest
from click.testing import CliRunner

from arbiter.cli import cli
from arbiter.core import Exercise, RestartMarking, Result, RunMarker, Step
from arbiter.dump import Dumper, load_previous


def _exercise(tmp_path):
    (tmp_path / "s.py").write_text("print('x')\n")
    a = RunMarker(str(tmp_path), criterion="a")
    a.python("s.py").ask_for_score("one?", 5)
    b = RunMarker(str(tmp_path), criterion="b")
    b.ask_for_score("two?", 5, choices=[0, 2, 5])
    return Exercise(a, b)


def _human(score, feedback="fb"):
    return Result(5, score, feedback, "human")


def test_answers_carry_a_question_id(tmp_path):
    exercise = _exercise(tmp_path)
    exercise.run(lambda q: _human(3))
    assert [r.question_id for m in exercise.markers for r in m.results] == ["a:1", "b:0"]


def test_previous_answer_is_offered_when_acceptable(tmp_path):
    exercise = _exercise(tmp_path)
    seen = {}

    def ask(question):
        seen[question.question] = question.previous
        return _human(2)

    # b:0 only allows 0, 2 or 5, so a stored 3 is not offered.
    exercise.run(ask, previous={"a:1": _human(4, "kept"), "b:0": _human(3)})
    assert seen["one?"].score == 4 and seen["one?"].feedback == "kept"
    assert seen["two?"] is None


def test_mechanical_steps_rerun_every_time(tmp_path):
    exercise = _exercise(tmp_path)
    marker = RunMarker(str(tmp_path), criterion="m")
    runs = []
    marker.steps.append(
        Step(True, lambda ctx: runs.append(1) or Result(1, 1, "auto"), out_of=1)
    )
    exercise.markers.append(marker)
    exercise.run(lambda q: _human(1), previous={"a:1": _human(1)})
    exercise.run(lambda q: _human(1), previous={"a:1": _human(1)})
    assert len(runs) == 2


def test_checkpoints_keep_stored_answers_not_yet_asked_again(tmp_path):
    exercise = _exercise(tmp_path)
    dumper = Dumper(str(tmp_path / "out"), str(tmp_path), None)
    previous = {"a:1": _human(4, "old a"), "b:0": _human(2, "old b")}
    states = []

    def ask(question):
        states.append(tomllib.loads((tmp_path / "out.toml").read_text()))
        return _human(1, "new")

    exercise.run(ask, checkpoint=dumper.write, previous=previous)
    dumper.write(exercise, complete=True)
    # Before the first question, both stored answers are in the file...
    assert {s["question"] for s in states[0]["stored"]} == {"a:1", "b:0"}
    # ...before the second only b:0 remains, and a:1's new answer is a result.
    assert {s["question"] for s in states[1]["stored"]} == {"b:0"}
    assert states[1]["result"][0]["question"] == "a:1"
    # They never count towards the score.
    assert states[0]["score"] == 0
    # Complete: nothing stored is left.
    assert "stored" not in tomllib.loads((tmp_path / "out.toml").read_text())


def test_load_previous_reads_results_and_stored(tmp_path):
    exercise = _exercise(tmp_path)
    dumper = Dumper(str(tmp_path / "out"), str(tmp_path), None)
    def ask(question):
        if question.question == "two?":
            raise KeyboardInterrupt
        return _human(4, "done a")

    with pytest.raises(KeyboardInterrupt):
        exercise.run(ask, checkpoint=dumper.write, previous={"b:0": _human(2, "old b")})
    loaded = load_previous(str(tmp_path / "out.toml"))
    assert loaded["a:1"].score == 4 and loaded["a:1"].feedback == "done a"
    assert loaded["b:0"].score == 2 and loaded["b:0"].feedback == "old b"
    assert load_previous(str(tmp_path / "missing.toml")) == {}


def test_restart_reruns_everything_and_remembers_answers(tmp_path):
    exercise = _exercise(tmp_path)
    calls = []

    def ask(question):
        calls.append((question.question, question.previous.score if question.previous else None))
        if len(calls) == 2:
            raise RestartMarking()
        return _human(3, "first go")

    exercise.run(ask)
    # a answered 3, then b asked and restarted; the second attempt asks a
    # again with its earlier answer, then b.
    assert calls == [("one?", None), ("two?", None), ("one?", 3), ("two?", None)]
    assert exercise.restarts == 1
    assert len(exercise.markers[0].results) == 1  # not doubled up


def test_plain_prompt_keeps_stored_answer_on_enter_and_restarts(monkeypatch):
    from arbiter.cli import _default_ask_interactively
    from arbiter.core import Question

    question = Question("?", 5, previous=_human(4, "kept"))
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    result = _default_ask_interactively(question)
    assert (result.score, result.feedback) == (4, "kept")
    monkeypatch.setattr("builtins.input", lambda prompt: "restart")
    with pytest.raises(RestartMarking):
        _default_ask_interactively(question)


def test_tui_prefills_and_enter_accepts():
    pytest.importorskip("textual")
    from arbiter.core import Question
    from arbiter.tui import QuestionApp

    app = QuestionApp(Question("?", 5, previous=_human(4, "kept")))

    async def go():
        async with app.run_test() as pilot:
            await pilot.press("enter", "enter")

    asyncio.run(go())
    assert (app.result.score, app.result.feedback) == (4.0, "kept")


def test_tui_restart_key_raises_restart():
    pytest.importorskip("textual")
    from arbiter.core import Question
    from arbiter.tui import QuestionApp

    app = QuestionApp(Question("?", 5))

    async def go():
        async with app.run_test() as pilot:
            await pilot.press("ctrl+r")

    asyncio.run(go())
    assert app.restart and app.result is None


def _arb(tmp_path):
    arb = tmp_path / "arb.toml"
    arb.write_text(
        '[[marker]]\ncriterion="a"\n[[marker.step]]\ntype="ask_for_score"\n'
        'question="?"\nout_of=5\n'
    )
    return arb


def test_cli_resumes_from_the_results_file_and_fresh_ignores_it(tmp_path):
    sub = tmp_path / "s"
    sub.mkdir()
    arb = _arb(tmp_path)

    def run(*extra, answers):
        return CliRunner().invoke(
            cli, ["--arb", str(arb), "--no-tui", *extra, str(sub)], input=answers
        )

    first = run(answers="4\n")
    assert first.exit_code == 0, first.output
    again = run(answers="\n")  # Enter keeps the stored answer
    assert again.exit_code == 0, again.output
    assert "Stored answer: 4.0" in again.output
    assert "a: 4.0/5" in again.output
    fresh = run("--fresh", answers="2\n")
    assert "Stored answer" not in fresh.output
    assert "a: 2.0/5" in fresh.output
