"""A Textual interface for answering a judgement question -- see
../plans/tui.md. Needs the optional ``tui`` extra.

``ask_interactively`` is called synchronously by ``Exercise.run``, so each
question gets its own short-lived app rather than one app driving the run.
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Input, Label, Static, TabbedContent, TabPane

from .core import UNDECIDED_NOTE, RestartMarking, Result
from .terminal import TerminalError, open_terminal


def _header_text(question):
    session = question.session
    if session is None:
        return "Marks available: {}".format(question.out_of)
    lines = [
        "Student/Directory: {}".format(session.label or "(unknown)"),
        "Criterion: {}".format(session.criterion or "(none)"),
        "Marks so far: {} of {}   Question {} of {}".format(
            session.score, session.out_of, session.position, session.total
        ),
    ]
    if session.commands:
        lines.append(
            "Ctrl-T opens a terminal; there run: {}".format(", ".join(session.commands))
        )
    return "\n".join(lines)


def _marked_text(question):
    session = question.session
    if session is None or not session.marked:
        return "Nothing marked yet."
    lines = []
    for criterion, result in session.marked:
        who = "you" if result.decided_by == "human" else "AUTO"
        lines.append(
            "[{}] {}: {}/{}\n    {}".format(
                who, criterion or "(none)", result.score, result.out_of, result.feedback
            )
        )
    return "\n".join(lines)


def _question_text(question):
    session = question.session
    criterion = session.criterion if session and session.criterion else None
    heading = "{}out of {}".format(
        "{}: ".format(criterion) if criterion else "", question.out_of
    )
    text = heading + "\n"
    if session is not None and session.task:
        text += "\nTask: " + session.task + "\n"
    text += "\n" + question.question.rstrip()
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
    #body { height: 1fr; }
    #context { width: 2fr; }
    #marked { width: 1fr; border: round $primary; border-title-align: left; padding: 0 1; }
    #entry { height: auto; }
    """
    BINDINGS = [
        Binding("ctrl+o", "open_file", "Open in viewer"),
        Binding("ctrl+x", "close_file", "Close in viewer"),
        Binding("ctrl+t", "terminal", "Terminal"),
        Binding("ctrl+r", "restart", "Restart marking"),
    ]

    def __init__(self, question, viewer=None, terminal=None):
        super().__init__()
        self.question = question
        self.viewer = viewer
        ## The configured ``[terminal] open`` command line, or None for a
        ## platform default.
        self.terminal = terminal
        self.result = None
        self.restart = False

    def compose(self) -> ComposeResult:
        yield Label(_header_text(self.question), id="header", markup=False)
        with Horizontal(id="body"):
            with TabbedContent(id="context"):
                with TabPane("Question", id="question"):
                    with VerticalScroll():
                        yield Static(_question_text(self.question), markup=False)
                session = self.question.session
                if session is not None and session.assignment:
                    with TabPane("Assignment", id="assignment"):
                        with VerticalScroll():
                            yield Static(session.assignment, markup=False)
                for i, item in enumerate(self.question.context):
                    with TabPane(item.title, id="item{}".format(i)):
                        with VerticalScroll():
                            yield Static(_item_text(item), markup=False)
            with VerticalScroll(id="marked"):
                yield Static(_marked_text(self.question), markup=False)
        previous = self.question.previous
        yield Input(
            value=format(previous.score, "g") if previous else "",
            placeholder="score ({})".format(self.question.allowed()),
            id="score",
        )
        yield Input(
            value=previous.feedback if previous else "",
            placeholder="feedback",
            id="feedback",
        )
        yield Footer()

    def on_mount(self):
        self.query_one("#marked").border_title = "Marked so far"
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

    def action_restart(self):
        self.restart = True
        self.exit()

    def action_terminal(self):
        session = self.question.session
        if session is None or session.directory is None:
            self.notify("No submission directory to open a terminal in")
            return
        try:
            open_terminal(session.directory, self.terminal)
        except TerminalError as e:
            self.notify(str(e), severity="error")

    def on_input_submitted(self, event):
        if event.input.id == "score":
            self.query_one("#feedback").focus()
            return
        text = self.query_one("#score").value.strip()
        try:
            score = float(text) if text else 0.0
        except ValueError:
            score = None
        if score is None or not self.question.accepts(score):
            self.notify(
                "Score must be {}".format(self.question.allowed()),
                severity="error",
            )
            self.query_one("#score").focus()
            return
        feedback = self.query_one("#feedback").value.strip() or "marker-entered"
        self.result = Result(
            out_of=self.question.out_of, score=score, feedback=feedback
        )
        self.exit()


def make_ask_interactively(viewer=None, terminal=None):
    """An ``ask_interactively`` hook that shows each question in a
    ``QuestionApp``. Quitting the app without answering stops marking."""

    def ask(question):
        app = QuestionApp(question, viewer, terminal)
        app.run()
        if app.restart:
            raise RestartMarking()
        if app.result is None:
            raise KeyboardInterrupt("question not answered")
        return app.result

    return ask
