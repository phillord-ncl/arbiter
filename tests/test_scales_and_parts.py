import asyncio
import tomllib

import pytest

from arbiter.core import Exercise, Question, Result, RunMarker
from arbiter.dump import Dumper




def _answer(score):
    return lambda question: Result(out_of=question.out_of, score=score, feedback="")


def test_choices_restrict_what_is_accepted():
    question = Question("?", 2, choices=[0, 0.5, 1, 1.5, 2])
    assert question.accepts(1.5)
    assert not question.accepts(1.2)
    assert not question.accepts(3)
    assert question.allowed() == "one of 0, 0.5, 1, 1.5, 2"


def test_without_choices_any_number_up_to_out_of():
    question = Question("?", 5)
    assert question.accepts(0) and question.accepts(5) and question.accepts(2.3)
    assert not question.accepts(-1) and not question.accepts(6)
    assert question.allowed() == "a number from 0 to 5"


def test_ask_for_score_passes_choices_to_the_question(tmp_path):
    marker = RunMarker(str(tmp_path), criterion="a")
    marker.ask_for_score("?", 2, choices=(0, 1, 2))
    seen = []

    def ask(question):
        seen.append(question.choices)
        return Result(out_of=2, score=1, feedback="")

    Exercise(marker).run(ask)
    assert seen == [[0, 1, 2]]


def test_a_deduction_is_a_scale_below_zero(tmp_path):
    marker = RunMarker(str(tmp_path), criterion="stray")
    marker.ask_for_score("stray files?", 0, choices=[0, -1])
    good = RunMarker(str(tmp_path), criterion="work")
    good.ask_for_score("work?", 20)
    exercise = Exercise(good, marker)
    answers = iter([20, -1])
    exercise.run(lambda q: Result(out_of=q.out_of, score=next(answers), feedback=""))
    assert exercise.max_score() == 20
    assert exercise.score() == 19
    # Nothing is floored: a theoretical -1 stays -1.
    assert Question("?", 0, choices=[0, -1]).accepts(-1)


def test_formative_markers_count_for_nothing(tmp_path):
    graded = RunMarker(str(tmp_path), criterion="a")
    graded.ask_for_score("?", 1)
    formative = RunMarker(str(tmp_path), criterion="b", formative=True)
    formative.ask_for_score("?", 1)
    exercise = Exercise(graded, formative)
    exercise.run(_answer(1))
    assert (exercise.score(), exercise.max_score()) == (1, 1)
    # Still recorded, though.
    assert formative.results[0].score == 1
    # And Marker.max_score() is untouched, so a rubric check still sees it.
    assert formative.max_score() == 1


def test_parts_subtotals_in_order_of_first_appearance(tmp_path):
    def marker(part, out_of, **kwargs):
        m = RunMarker(str(tmp_path), part=part, **kwargs)
        m.ask_for_score("?", out_of)
        return m

    exercise = Exercise(
        marker("Part 1", 1),
        marker("Part 2", 3),
        marker("Part 1", 2),
        marker("Part 2", 1, formative=True),
        marker(None, 5),
    )
    exercise.run(_answer(1))
    assert exercise.parts() == [("Part 1", 2, 3), ("Part 2", 1, 3)]


def test_dump_has_part_subtotals_and_excludes_formative(tmp_path):
    a = RunMarker(str(tmp_path), criterion="a", part="Part 1")
    a.ask_for_score("?", 2)
    b = RunMarker(str(tmp_path), criterion="b", part="Part 1", formative=True)
    b.ask_for_score("?", 5)
    exercise = Exercise(a, b)
    dumper = Dumper(str(tmp_path / "out"), str(tmp_path), None, ["text"])
    exercise.run(_answer(1))
    dumper.write(exercise, complete=True)
    data = tomllib.loads((tmp_path / "out.toml").read_text())
    assert (data["score"], data["out_of"]) == (1, 2)
    assert data["part"] == [{"part": "Part 1", "score": 1, "out_of": 2}]
    assert [r["formative"] for r in data["result"]] == [False, True]
    assert data["result"][0]["part"] == "Part 1"
    text = (tmp_path / "out.txt").read_text()
    assert "b: 1/5 (formative, not counted)" in text
    assert "Part 1: 1/2" in text
    assert "Total: 1/2" in text


def test_plain_prompt_asks_again_until_valid(monkeypatch, capsys):
    from arbiter.cli import _default_ask_interactively

    answers = iter(["1.2", "x", "1.5"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    result = _default_ask_interactively(Question("?", 2, choices=[0, 0.5, 1, 1.5, 2]))
    assert result.score == 1.5
    out = capsys.readouterr().out
    assert out.count("Please enter one of 0, 0.5, 1, 1.5, 2.") == 2


def test_tui_refuses_a_score_off_the_scale():
    pytest.importorskip("textual")
    from arbiter.tui import QuestionApp

    def run(keys):
        app = QuestionApp(Question("?", 2, choices=[0, 0.5, 1, 1.5, 2]))

        async def go():
            async with app.run_test() as pilot:
                await pilot.press(*keys, "enter", "enter")

        asyncio.run(go())
        return app.result

    assert run("1.2") is None
    assert run("1.5").score == 1.5


def test_toml_reads_part_formative_and_choices(tmp_path):
    from arbiter.toml_exercise import load_exercise

    arb = tmp_path / "arb.toml"
    arb.write_text(
        """
[[marker]]
criterion = "a"
part = "Part 1"
[[marker.step]]
type = "ask_for_score"
question = "?"
out_of = 2
choices = [0, 0.5, 1, 1.5, 2]

[[marker]]
criterion = "b"
formative = true
[[marker.step]]
type = "ask_for_score"
question = "?"
out_of = 1
"""
    )
    exercise, _ = load_exercise(str(arb), str(tmp_path))
    first, second = exercise.markers
    assert (first.part, first.formative) == ("Part 1", False)
    assert (second.part, second.formative) == (None, True)
    seen = []
    exercise.run(lambda q: (seen.append(q.choices), Result(q.out_of, 1, ""))[1])
    assert seen == [[0, 0.5, 1, 1.5, 2], None]
