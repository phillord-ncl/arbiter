"""A Textual interface for answering a judgement question -- see
../plans/tui.md. Needs the optional ``tui`` extra.

``ask_interactively`` is called synchronously by ``Exercise.run``, so each
question gets its own short-lived app rather than one app driving the run.
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from rich.text import Text
from textual import events
from textual.command import Hit, Provider
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import (
    Footer, Input, Label, OptionList, Static, TabbedContent, TabPane, TextArea,
)

from .config import VIEWER_CHOICES, VIEWER_LABELS, save_viewer
from .core import UNDECIDED_NOTE, GoBack, RestartMarking, Result
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


class ViewerScreen(ModalScreen):
    """Pick the viewer to open files in; dismissed with the choice's name,
    "none" to go back to showing files in the UI, or None if cancelled."""

    DEFAULT_CSS = """
    ViewerScreen { align: center middle; }
    #viewer-dialog { width: 60; height: auto; border: round $primary;
                     background: $surface; padding: 1 2; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="viewer-dialog"):
            yield Label("Open files in which viewer?", markup=False)
            yield OptionList(
                *[VIEWER_LABELS[name] for name in VIEWER_CHOICES],
                "None (show files in arbiter only)",
                id="viewer-choices",
            )

    def on_option_list_option_selected(self, event):
        index = event.option_index
        self.dismiss(VIEWER_CHOICES[index] if index < len(VIEWER_CHOICES) else "none")

    def action_cancel(self):
        self.dismiss(None)


class ViewerCommands(Provider):
    """The "Configure viewer" entry in the menu (Ctrl-P)."""

    TITLE = "Configure viewer"

    async def discover(self):
        yield Hit(
            1,
            "Configure viewer",
            self.app.action_configure_viewer,
            help="Choose Emacs, Emacsclient, VS Code or PyCharm for Ctrl-O",
        )

    async def search(self, query):
        match = self.matcher(query).match("Configure viewer")
        if match > 0:
            yield Hit(
                match,
                "Configure viewer",
                self.app.action_configure_viewer,
                help="Choose Emacs, Emacsclient, VS Code or PyCharm for Ctrl-O",
            )


class FeedbackBox(TextArea):
    """A wrapped, several-line box for the feedback. Enter submits, as in the
    one-line boxes; Ctrl-J starts a new line. ``value`` and
    ``cursor_position`` mirror ``Input``'s."""

    class Submitted(Message):
        pass

    def __init__(self, value="", placeholder="", **kwargs):
        super().__init__(
            value, soft_wrap=True, placeholder=placeholder, **kwargs
        )

    @property
    def value(self):
        return self.text

    @value.setter
    def value(self, text):
        self.text = text

    @property
    def cursor_position(self):
        return len(self.text)

    @cursor_position.setter
    def cursor_position(self, _):
        self.move_cursor(self.document.end)

    async def _on_key(self, event):
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted())
        elif event.key == "ctrl+j":
            event.stop()
            event.prevent_default()
            self.insert("\n")
        else:
            await super()._on_key(event)


class QuestionApp(App, inherit_bindings=False):
    COMMANDS = App.COMMANDS | {ViewerCommands}

    CSS = """
    #header { background: $boost; padding: 0 1; }
    #body { height: 1fr; }
    #context { width: 2fr; }
    #side { width: 1fr; min-width: 12; }
    #marked { height: 1fr; border: round $primary; border-title-align: left; padding: 0 1; }
    #progress { height: auto; border: round $primary; padding: 0 1; }
    #entry { height: auto; }
    #feedback { height: 8; }
    """
    BINDINGS = [
        ## Footer order follows this order. Textual's own bindings are not
        ## inherited: its Ctrl-Q would otherwise keep its early place.
        ## Priority, so the tab keys work from the entry boxes (where they
        ## would otherwise move by word).
        Binding("ctrl+left", "tab(-1)", "Previous tab", priority=True),
        Binding("ctrl+right", "tab(1)", "Next tab", priority=True),
        Binding("ctrl+o", "open_file", "Open in viewer"),
        Binding("ctrl+x", "close_file", "Close in viewer"),
        Binding("ctrl+t", "terminal", "Terminal"),
        Binding("ctrl+b", "back", "Previous question"),
        Binding("ctrl+r", "restart", "Restart marking"),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+c", "help_quit", show=False, system=True),
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

    def __init__(
        self, question, viewer=None, terminal=None, progress=None, config_path=None
    ):
        super().__init__()
        ## Where "Configure viewer" saves; None for the user's config.toml.
        self.config_path = config_path
        self.question = question
        ## A cli.Progress when marking a batch, else None.
        self.progress = progress
        self.viewer = viewer
        ## The configured ``[terminal] open`` command line, or None for a
        ## platform default.
        self.terminal = terminal
        self.result = None
        self.restart = False
        self.back = False

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
            value="0" if self.question.feedback_only
            else format(previous.score, "g") if previous else "",
            placeholder="score ({})".format(self.question.allowed()),
            id="score",
        )
        yield FeedbackBox(
            previous.feedback if previous else "",
            placeholder="feedback (Enter to finish, Ctrl-J for a new line)",
            id="feedback",
        )
        yield Footer()

    def on_mount(self):
        self.query_one("#marked").border_title = "Marked so far"
        if self.question.feedback_only:
            self.query_one("#score").display = False
            self.query_one("#feedback").focus()
        else:
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

    def action_configure_viewer(self):
        self.push_screen(ViewerScreen(), self._viewer_chosen)

    def _viewer_chosen(self, name):
        if name is None:
            return
        try:
            self.viewer = save_viewer(None if name == "none" else name, self.config_path)
        except OSError as e:
            self.notify("Cannot save the config: {}".format(e), severity="error")
            return
        self.notify(
            "Viewer: {}".format(VIEWER_LABELS.get(name, "none")) + " (saved)"
        )

    def action_back(self):
        session = self.question.session
        if session is None or session.position <= 1:
            self.notify("This is the first question")
            return
        self.back = True
        self.exit()

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

    def on_descendant_focus(self, event):
        """Offer the full-marks feedback as soon as the marker moves to the
        feedback box (Enter or Tab), so they can see and edit it."""
        feedback = self.query_one("#feedback")
        if event.widget is not feedback or feedback.value.strip():
            return
        if not self.question.full_feedback:
            return
        try:
            full = self.question.is_full(float(self.query_one("#score").value))
        except ValueError:
            return
        if full:
            feedback.value = self.question.full_feedback
            feedback.cursor_position = len(feedback.value)

    def on_input_submitted(self, event):
        if event.input.id == "score":
            self.query_one("#feedback").focus()

    def on_feedback_box_submitted(self, event):
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
        feedback = self.query_one("#feedback").value.strip()
        problem = self.question.feedback_problem(score, feedback)
        if problem:
            self.notify(problem, severity="error")
            self.query_one("#feedback").focus()
            return
        feedback = feedback or self.question.default_feedback(score)
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
            "Close their terminals, and any files the viewer could not close, "
            "so that you are not in the wrong place.",
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

    ## "Configure viewer" can replace the viewer part way through.
    current = {"viewer": viewer}

    def ask(question):
        app = QuestionApp(question, current["viewer"], terminal, progress)
        app.run()
        current["viewer"] = app.viewer
        if app.restart:
            raise RestartMarking()
        if app.back:
            raise GoBack()
        if app.result is None:
            raise KeyboardInterrupt("question not answered")
        return app.result

    def next_student(finished, upcoming, progress=None):
        app = NextStudentApp(finished, upcoming, progress)
        app.run()
        return bool(app.carry_on)

    def student_done(submission):
        if current["viewer"] is not None:
            current["viewer"].close_all(submission)

    ask.next_student = next_student
    ask.student_done = student_done
    return ask
