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
    assert "7/10 [AUTO] output" in marked
    assert "1/2 [you] style" in marked


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


async def _drag_splitter(app, dx):
    async with app.run_test(size=(100, 30)) as pilot:
        marked = app.query_one("#marked")
        before = marked.outer_size.width
        await pilot.mouse_down("#splitter")
        await pilot.hover("#splitter", offset=(dx, 0))
        await pilot.mouse_up("#splitter")
        await pilot.pause()
        return before, marked.outer_size.width


def test_dragging_the_splitter_resizes_the_marked_pane(tmp_path):
    app = QuestionApp(_question(tmp_path))
    before, after = asyncio.run(_drag_splitter(app, -15))
    assert after > before


def test_marked_pane_keeps_a_minimum_width(tmp_path):
    app = QuestionApp(_question(tmp_path))
    before, after = asyncio.run(_drag_splitter(app, 25))
    assert after >= 12


async def _footer_labels(app):
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        from textual.widgets._footer import FooterKey

        return [str(k.description) for k in app.query(FooterKey)]


def test_command_palette_is_labelled_menu(tmp_path):
    labels = asyncio.run(_footer_labels(QuestionApp(_question(tmp_path))))
    assert "menu" in labels
    assert "palette" not in labels


async def _splitter_text(app):
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        splitter = app.query_one("#splitter")
        return "".join(
            "".join(seg.text for seg in line)
            for line in splitter.render_lines(splitter.size.region)
        ).strip()


def test_the_splitter_draws_no_text(tmp_path):
    assert asyncio.run(_splitter_text(QuestionApp(_question(tmp_path)))) == ""


def test_marked_scores_are_coloured_by_result(tmp_path):
    from arbiter.core import Result
    from arbiter.tui import _marked_text

    question = _question(tmp_path)
    question.session.marked = [
        ("a", Result(score=10, out_of=10, feedback="ok", decided_by="auto")),
        ("b", Result(score=1, out_of=2, feedback="some", decided_by="human")),
        ("c", Result(score=0, out_of=3, feedback="none", decided_by="human")),
        ("d", Result(score=-1, out_of=0, feedback="deduct", decided_by="human")),
    ]
    text = _marked_text(question)
    styles = {text.plain[s.start:s.end]: str(s.style) for s in text.spans}
    assert styles == {
        "10/10": "green",
        "1/2": "dark_orange",
        "0/3": "red",
        "-1/0": "red",
    }
    assert text.plain.startswith("10/10 [AUTO] a")


class _Viewer:
    def __init__(self):
        self.opened = []

    def open_file(self, path):
        self.opened.append(path)

    def close_file(self, path):
        pass


async def _open_from(app, tab):
    async with app.run_test(size=(100, 30)) as pilot:
        app.query_one("#context").active = tab
        await pilot.pause()
        await pilot.press("ctrl+o")


def test_open_from_a_non_file_tab_opens_the_next_file(tmp_path):
    for tab in ("question", "item0"):  # item0 is the stdout text item
        viewer = _Viewer()
        app = QuestionApp(_question(tmp_path), viewer=viewer)
        asyncio.run(_open_from(app, tab))
        assert viewer.opened == [str(tmp_path / "s.py")], tab


def test_open_from_a_file_tab_opens_that_file(tmp_path):
    viewer = _Viewer()
    app = QuestionApp(_question(tmp_path), viewer=viewer)
    asyncio.run(_open_from(app, "item1"))
    assert viewer.opened == [str(tmp_path / "s.py")]


def test_ctrl_q_quits_without_an_answer(tmp_path):
    app = QuestionApp(_question(tmp_path))

    async def run():
        async with app.run_test() as pilot:
            await pilot.press("ctrl+q")
            await pilot.pause()

    asyncio.run(run())
    assert app.result is None and not app.restart


def test_quit_is_listed_in_the_footer(tmp_path):
    labels = asyncio.run(_footer_labels(QuestionApp(_question(tmp_path))))
    assert "Quit" in labels


async def _tabs_after(app, keys):
    async with app.run_test(size=(100, 30)) as pilot:
        for key in keys:
            await pilot.press(key)
            await pilot.pause()
        return app.query_one("#context").active


def test_ctrl_arrows_move_between_tabs_and_wrap(tmp_path):
    def after(*keys):
        app = QuestionApp(_question(tmp_path))
        return asyncio.run(_tabs_after(app, keys))

    # Tabs: Question, stdout, s.py
    assert after("ctrl+right") == "item0"
    assert after("ctrl+right", "ctrl+right") == "item1"
    assert after("ctrl+right", "ctrl+right", "ctrl+right") == "question"
    assert after("ctrl+left") == "item1"


def test_progress_panel_shows_only_for_a_batch(tmp_path):
    from arbiter.cli import Progress

    async def panel(progress):
        app = QuestionApp(_question(tmp_path), progress=progress)
        async with app.run_test() as pilot:
            return len(app.query("#progress"))

    batch = Progress(3)
    batch.skipped("c01")
    assert asyncio.run(panel(batch)) == 1
    assert asyncio.run(panel(Progress(1))) == 0
    assert asyncio.run(panel(None)) == 0


def test_next_student_dialog_continues_on_enter_and_stops_on_quit():
    from arbiter.tui import NextStudentApp

    async def run(key):
        app = NextStudentApp("c01", "c02")
        async with app.run_test() as pilot:
            await pilot.press(key)
        return app.carry_on

    assert asyncio.run(run("enter")) is True
    assert asyncio.run(run("ctrl+q")) is False


def test_full_marks_fill_the_feedback_box(tmp_path):
    question = _question(tmp_path)
    question.full_feedback = "Correct"
    app = QuestionApp(question)
    asyncio.run(_answer(app, "5", ""))
    assert (app.result.score, app.result.feedback) == (5.0, "Correct")


def test_full_marks_default_keeps_what_marker_typed(tmp_path):
    question = _question(tmp_path)
    question.full_feedback = "Correct"
    app = QuestionApp(question)

    async def go():
        async with app.run_test() as pilot:
            app.query_one("#feedback").value = "lovely"
            await pilot.press("5", "enter", "enter")

    asyncio.run(go())
    assert app.result.feedback == "lovely"


def test_required_feedback_is_enforced_below_full_marks(tmp_path):
    question = _question(tmp_path)
    question.require_feedback = True
    app = QuestionApp(question)

    async def go():
        async with app.run_test() as pilot:
            await pilot.press("3", "enter", "enter")
            assert app.result is None
            await pilot.press(*"why", "enter")

    asyncio.run(go())
    assert (app.result.score, app.result.feedback) == (3.0, "why")


def test_required_feedback_not_needed_for_full_marks(tmp_path):
    question = _question(tmp_path)
    question.require_feedback = True
    app = QuestionApp(question)
    asyncio.run(_answer(app, "5", ""))
    assert app.result.score == 5.0


def test_tab_to_feedback_shows_the_full_marks_text(tmp_path):
    question = _question(tmp_path)
    question.full_feedback = "Correct"
    app = QuestionApp(question)

    async def go():
        async with app.run_test() as pilot:
            await pilot.press("5", "tab")
            assert app.query_one("#feedback").value == "Correct"

    asyncio.run(go())
