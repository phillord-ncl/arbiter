import asyncio

import pytest

pytest.importorskip("textual")

from tent_arbiter.core import ContextItem, Question, Session
from tent_arbiter.tui import QuestionApp


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
