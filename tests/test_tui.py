import asyncio

import pytest

pytest.importorskip("textual")

from arbiter.core import ContextItem, Question, Session
from arbiter.tui import QuestionApp


def _question(tmp_path):
    f = tmp_path / "s.py"
    f.write_text("print('hi')\n")
    return Question(
        "score? ",
        5,
        [ContextItem("stdout", text="hi\n"), ContextItem("s.py", path=str(f))],
        Session("alice", "style", 3, 12, 1, 2),
    )


async def _answer(app, score, feedback):
    async with app.run_test() as pilot:
        await pilot.press(*score, "enter", *feedback, "enter")


def test_answer_is_returned(tmp_path):
    app = QuestionApp(_question(tmp_path))
    asyncio.run(_answer(app, "4", "good"))
    assert (app.result.score, app.result.out_of, app.result.feedback) == (
        4.0, 5, "good")


def test_blank_answers_default(tmp_path):
    app = QuestionApp(_question(tmp_path))
    asyncio.run(_answer(app, "", ""))
    assert (app.result.score, app.result.feedback) == (0.0, "marker-entered")


def test_out_of_range_score_is_refused(tmp_path):
    app = QuestionApp(_question(tmp_path))

    async def go():
        async with app.run_test() as pilot:
            await pilot.press("9", "enter", "enter")

    asyncio.run(go())
    assert app.result is None


def test_question_tab_shows_the_question_text(tmp_path):
    from textual.widgets import TabbedContent

    question = _question(tmp_path)
    question.question = "Is the style good? "
    app = QuestionApp(question)

    async def go():
        async with app.run_test():
            assert app.query_one(TabbedContent).active == "question"
            texts = [str(w.render()) for w in app.query("Static")]
            assert any("Is the style good?" in t for t in texts)
            assert any(t.startswith("style: out of 5") for t in texts)

    asyncio.run(go())


def test_header_and_marked_panel(tmp_path):
    from arbiter.core import Result
    from arbiter.tui import _header_text, _marked_text

    question = _question(tmp_path)
    question.session.marked = [
        ("output", Result(out_of=10, score=7, feedback="close")),
        ("style", Result(out_of=2, score=1, feedback="ok", decided_by="human")),
    ]
    header = _header_text(question)
    assert "Student/Directory: alice" in header
    assert "Criterion: style" in header
    marked = _marked_text(question)
    assert "[AUTO] output: 7/10" in marked
    assert "[you] style: 1/2" in marked


def test_question_tab_shows_task_and_assignment_tab(tmp_path):
    from textual.widgets import TabbedContent

    question = _question(tmp_path)
    question.session.task = "Print a greeting"
    question.session.assignment = "The whole assignment"
    app = QuestionApp(question)

    async def go():
        async with app.run_test():
            texts = [str(w.render()) for w in app.query("Static")]
            assert any("Task: Print a greeting" in t for t in texts)
            assert any(t == "The whole assignment" for t in texts)
            assert app.query_one(TabbedContent).get_tab("assignment")

    asyncio.run(go())
