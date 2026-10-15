"""A Textual interface for answering a judgement question -- see
../plans/tui.md. Needs the optional ``tui`` extra.

``ask_interactively`` is called synchronously by ``Exercise.run``, so each
question gets its own short-lived app rather than one app driving the run.
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from rich.text import Text
from textual import events
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
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


def _score_style(result):
    """Green for full marks, red for none (or a deduction), else orange."""
    if result.score >= result.out_of:
        return "green"
    if result.score <= 0:
        return "red"
    return "dark_orange"


def _marked_text(question):
    session = question.session
    if session is None or not session.marked:
        return Text("Nothing marked yet.")
    text = Text()
    for criterion, result in session.marked:
        who = "you" if result.decided_by == "human" else "AUTO"
        if text:
            text.append("\n")
        text.append(
            "{}/{}".format(result.score, result.out_of),
            style=_score_style(result),
        )
        text.append(" [{}] {}\n    {}".format(
            who, criterion or "(none)", result.feedback
        ))
    return text


def _progress_text(progress):
    """Done and to go, then the last couple of log lines."""
    lines = [
        "{} done, {} to go (of {})".format(
            progress.done, progress.total - progress.done, progress.total
        )
    ]
    lines.extend(progress.log)
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


class Splitter(Widget):
    """A bar between the context and the "Marked so far" pane; drag it
    sideways to resize the marked pane."""

    MIN_WIDTH = 12
    MIN_CONTEXT = 20

    DEFAULT_CSS = """
    Splitter { width: 1; background: $primary 40%; }
    Splitter:hover { background: $primary; }
    """

    def __init__(self, target, **kwargs):
        super().__init__(**kwargs)
        self.target = target
        self.dragging = False

    def render(self):
        ## A bare widget draws its own name.
        return ""

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.dragging = True
        self.capture_mouse()
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self.dragging:
            self.resize_to(event.screen_x)
            event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self.dragging:
            self.dragging = False
            self.release_mouse()
            event.stop()

    def resize_to(self, screen_x):
        """Put the bar at column ``screen_x``; the target takes the rest."""
        total = self.app.size.width
        width = total - screen_x - 1
        width = max(self.MIN_WIDTH, min(width, total - self.MIN_CONTEXT - 1))
        self.target.styles.width = width


class QuestionApp(App):
    CSS = """
    #header { background: $boost; padding: 0 1; }
    #body { height: 1fr; }
    #context { width: 2fr; }
    #side { width: 1fr; min-width: 12; }
    #marked { height: 1fr; border: round $primary; border-title-align: left; padding: 0 1; }
    #progress { height: auto; border: round $primary; padding: 0 1; }
    #entry { height: auto; }
    """
    BINDINGS = [
        Binding("ctrl+o", "open_file", "Open in viewer"),
        Binding("ctrl+x", "close_file", "Close in viewer"),
        Binding("ctrl+t", "terminal", "Terminal"),
        Binding("ctrl+r", "restart", "Restart marking"),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        ## Priority, so they work from the entry boxes (where they would
        ## otherwise move by word).
        Binding("ctrl+right", "tab(1)", "Next tab", show=False, priority=True),
        Binding("ctrl+left", "tab(-1)", "Previous tab", show=False, priority=True),
        ## Textual's own command palette, relabelled; declaring it here
        ## stops Textual adding its default, labelled "palette".
        Binding(
            "ctrl+p",
            "command_palette",
            "menu",
            show=False,
            priority=True,
            tooltip="Open the command menu",
        ),
    ]

    def __init__(self, question, viewer=None, terminal=None, progress=None):
        super().__init__()
        self.question = question
        ## A cli.Progress when marking a batch, else None.
        self.progress = progress
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
            side = Vertical(id="side")
            yield Splitter(side, id="splitter")
            with side:
                with VerticalScroll(id="marked"):
                    yield Static(_marked_text(self.question), markup=False)
                if self.progress is not None and self.progress.total > 1:
                    yield Static(
                        _progress_text(self.progress), id="progress", markup=False
                    )
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

    def _file_item(self):
        """The file for Ctrl-O/Ctrl-X: this tab's if it is a file, else the
        next file's tab, else the first file."""
        pane_id = self.query_one("#context", TabbedContent).active
        items = self.question.context
        here = int(pane_id[len("item"):]) if pane_id.startswith("item") else -1
        if here >= 0 and items[here].path is not None:
            return items[here]
        for item in items[here + 1:] + items[:here + 1]:
            if item.path is not None:
                return item
        return None

    def action_open_file(self):
        if self.viewer is None:
            self.notify("No viewer configured (see docs/viewer.md)")
            return
        item = self._file_item()
        if item is None:
            self.notify("There is no file to open")
            return
        self.viewer.open_file(item.path)

    def action_close_file(self):
        item = self._file_item()
        if self.viewer is not None and item is not None:
            self.viewer.close_file(item.path)

    def action_tab(self, step: int):
        """Move ``step`` tabs along (wrapping round)."""
        context = self.query_one("#context", TabbedContent)
        ids = [pane.id for pane in context.query(TabPane)]
        if ids and context.active in ids:
            context.active = ids[(ids.index(context.active) + step) % len(ids)]

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


class NextStudentApp(App):
    """Shown between students: the marker closes the last one's terminals and
    viewer files, then says to go on. ``carry_on`` is None if they quit."""

    CSS = """
    Screen { align: center middle; }
    #dialog { width: 70; height: auto; border: round $primary; padding: 1 2; }
    """
    BINDINGS = [
        Binding("enter", "go", "Next student"),
        Binding("ctrl+q", "quit", "Stop marking", priority=True),
    ]

    def __init__(self, finished, upcoming, progress=None):
        super().__init__()
        self.finished = finished
        self.upcoming = upcoming
        self.progress = progress
        self.carry_on = None

    def compose(self) -> ComposeResult:
        lines = [
            "{} is marked.".format(self.finished),
            "",
            "Close their terminals and files in the viewer, so that you are "
            "not in the wrong place.",
            "",
            "Next student: {}".format(self.upcoming),
        ]
        if self.progress is not None:
            lines += ["", _progress_text(self.progress)]
        with Vertical(id="dialog"):
            yield Static("\n".join(lines), markup=False)
        yield Footer()

    def action_go(self):
        self.carry_on = True
        self.exit()

    def action_quit(self):
        self.carry_on = False
        self.exit()


def make_ask_interactively(viewer=None, terminal=None, progress=None):
    """An ``ask_interactively`` hook that shows each question in a
    ``QuestionApp``. Quitting the app without answering stops marking."""

    def ask(question):
        app = QuestionApp(question, viewer, terminal, progress)
        app.run()
        if app.restart:
            raise RestartMarking()
        if app.result is None:
            raise KeyboardInterrupt("question not answered")
        return app.result

    def next_student(finished, upcoming, progress=None):
        app = NextStudentApp(finished, upcoming, progress)
        app.run()
        return bool(app.carry_on)

    ask.next_student = next_student
    return ask
