"""A Textual interface for answering a judgement question -- see
../plans/tui.md. Needs the optional ``tui`` extra.

``ask_interactively`` is called synchronously by ``Exercise.run``, so each
question gets its own short-lived app rather than one app driving the run.
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Footer, Input, Label, Static, TabbedContent, TabPane

from .core import UNDECIDED_NOTE, Result


def _header_text(question):
    session = question.session
    if session is None:
        return "Out of {}".format(question.out_of)
    return "{}   {}   marks {}/{}   question {} of {}".format(
        session.label or "(submission)",
        session.criterion or "",
        session.score,
        session.out_of,
        session.position,
        session.total,
    )


def _question_text(question):
    session = question.session
    criterion = session.criterion if session and session.criterion else None
    heading = "{}out of {}".format(
        "{}: ".format(criterion) if criterion else "", question.out_of
    )
    text = heading + "\n\n" + question.question.rstrip()
    if question.undecided:
        text += "\n\n" + UNDECIDED_NOTE
    return text


def _item_text(item):
    if item.text is not None:
        return item.text
    try:
        with open(item.path, errors="replace") as f:
            return f.read()
    except OSError as e:
        return "(cannot read {}: {})".format(item.path, e)


class QuestionApp(App):
    CSS = """
    #header { background: $boost; padding: 0 1; }
    TabbedContent { height: 1fr; }
    #entry { height: auto; }
    """
    BINDINGS = [
        Binding("ctrl+o", "open_file", "Open in viewer"),
        Binding("ctrl+x", "close_file", "Close in viewer"),
    ]

    def __init__(self, question, viewer=None):
        super().__init__()
        self.question = question
        self.viewer = viewer
        self.result = None

    def compose(self) -> ComposeResult:
        yield Label(_header_text(self.question), id="header")
        with TabbedContent(id="context"):
            with TabPane("Question", id="question"):
                with VerticalScroll():
                    yield Static(_question_text(self.question), markup=False)
            for i, item in enumerate(self.question.context):
                with TabPane(item.title, id="item{}".format(i)):
                    with VerticalScroll():
                        yield Static(_item_text(item), markup=False)
        yield Input(
            placeholder="score (0 to {})".format(self.question.out_of), id="score"
        )
        yield Input(placeholder="feedback", id="feedback")
        yield Footer()

    def on_mount(self):
        self.query_one("#score").focus()

    def _current_item(self):
        pane_id = self.query_one("#context", TabbedContent).active
        if pane_id.startswith("item"):
            return self.question.context[int(pane_id[len("item"):])]
        return None

    def action_open_file(self):
        item = self._current_item()
        if self.viewer is None:
            self.notify("No viewer configured (see docs/viewer.md)")
            return
        if item is None or item.path is None:
            self.notify("This tab is not a file; switch to a file's tab first")
            return
        self.viewer.open_file(item.path)

    def action_close_file(self):
        item = self._current_item()
        if self.viewer is not None and item is not None and item.path is not None:
            self.viewer.close_file(item.path)

    def on_input_submitted(self, event):
        if event.input.id == "score":
            self.query_one("#feedback").focus()
            return
        text = self.query_one("#score").value.strip()
        try:
            score = float(text) if text else 0.0
        except ValueError:
            score = None
        if score is None or not 0 <= score <= self.question.out_of:
            self.notify(
                "Score must be a number from 0 to {}".format(self.question.out_of),
                severity="error",
            )
            self.query_one("#score").focus()
            return
        feedback = self.query_one("#feedback").value.strip() or "marker-entered"
        self.result = Result(
            out_of=self.question.out_of, score=score, feedback=feedback
        )
        self.exit()


def make_ask_interactively(viewer=None):
    """An ``ask_interactively`` hook that shows each question in a
    ``QuestionApp``. Quitting the app without answering stops marking."""

    def ask(question):
        app = QuestionApp(question, viewer)
        app.run()
        if app.result is None:
            raise KeyboardInterrupt("question not answered")
        return app.result

    return ask
