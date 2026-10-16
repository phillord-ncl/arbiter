import pytest
import textwrap

from click.testing import CliRunner

from arbiter.cli import cli


ARB_PY = textwrap.dedent(
    """
    import os

    from arbiter.core import Exercise, RunMarker
    from arbiter.matchers import Exact

    RUBRIC_TOML = os.path.join(os.path.dirname(__file__), "rubric.toml")

    def build(submission_dir):
        marker = RunMarker(submission_dir, criterion="correctness")
        marker.python("a.py").match_stdout(5, Exact("A\\n", "output correct", 5))
        return Exercise(marker)
    """
)

CONSISTENT_RUBRIC_TOML = textwrap.dedent(
    """
    [assignment]
    title = "T"
    description = "d.md"

    [[criteria]]
    id = "correctness"
    description = "Correctness"
    points = 5
    """
)

INCONSISTENT_RUBRIC_TOML = textwrap.dedent(
    """
    [assignment]
    title = "T"
    description = "d.md"

    [[criteria]]
    id = "correctness"
    description = "Correctness"
    points = 999
    """
)


def _write(tmp_path, name, output):
    path = tmp_path / name
    path.write_text(f'print("{output}")\n')
    return path


def test_cli_runs_the_exercise_and_prints_results(tmp_path):
    (tmp_path / "arb.py").write_text(ARB_PY)
    (tmp_path / "rubric.toml").write_text(CONSISTENT_RUBRIC_TOML)
    _write(tmp_path, "a.py", "A")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--arb", str(tmp_path / "arb.py"), str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    assert "correctness: 5/5" in result.output


def test_cli_fails_fast_on_rubric_inconsistency(tmp_path):
    (tmp_path / "arb.py").write_text(ARB_PY)
    (tmp_path / "rubric.toml").write_text(INCONSISTENT_RUBRIC_TOML)
    _write(tmp_path, "a.py", "A")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--arb", str(tmp_path / "arb.py"), str(tmp_path)]
    )

    assert result.exit_code != 0
    assert "inconsistent" in result.output.lower()


def test_default_prompt_prints_context(monkeypatch, capsys):
    from arbiter.cli import _default_ask_interactively
    from arbiter.core import ContextItem, Question

    monkeypatch.setattr("builtins.input", lambda prompt: "3")
    question = Question("score? ", 5, [ContextItem("stdout", text="hello\n")])
    result = _default_ask_interactively(question)
    assert result.score == 3
    out = capsys.readouterr().out
    assert "--- stdout" in out and "hello" in out


def test_no_tui_and_non_terminal_use_the_plain_prompt():
    from arbiter.cli import _choose_ask, _default_ask_interactively

    assert _choose_ask(False) is _default_ask_interactively
    # Under pytest stdin is not a terminal.
    assert _choose_ask(None) is _default_ask_interactively


def test_tui_flag_builds_the_textual_hook():
    pytest.importorskip("textual")
    from arbiter.cli import _choose_ask, _default_ask_interactively

    assert _choose_ask(True) is not _default_ask_interactively


def test_cli_reports_a_missing_project_directory(tmp_path):
    (tmp_path / "arb.toml").write_text(
        'root = "project"\n'
        '[[marker]]\ncriterion = "c"\ntitle = "t"\n'
        '[[marker.step]]\ntype = "file_exists"\nfiles = "a"\nout_of = 1\n'
    )
    sub = tmp_path / "sub"
    sub.mkdir()

    result = CliRunner().invoke(
        cli, ["--arb", str(tmp_path / "arb.toml"), str(sub)]
    )

    assert result.exit_code != 0
    assert "no project directory" in result.output


def test_find_arb_takes_a_single_named_arb_toml(tmp_path, monkeypatch):
    from arbiter.cli import _find_arb

    monkeypatch.chdir(tmp_path)
    (tmp_path / "x.arb.toml").write_text("")
    assert _find_arb() == "x.arb.toml"
    (tmp_path / "y.arb.toml").write_text("")
    with pytest.raises(Exception, match="more than one"):
        _find_arb()
    (tmp_path / "arb.toml").write_text("")
    assert _find_arb() == "arb.toml"


def test_find_submission_completes_a_short_name(tmp_path, monkeypatch):
    from arbiter.cli import _find_submission

    monkeypatch.chdir(tmp_path)
    (tmp_path / "c01@uni.ac.uk").mkdir()
    (tmp_path / "c02@uni.ac.uk").mkdir()
    assert _find_submission("c01") == "c01@uni.ac.uk"
    assert _find_submission("c01@uni.ac.uk") == "c01@uni.ac.uk"
    assert _find_submission("c99") == "c99"
    (tmp_path / "d1@a").mkdir()
    (tmp_path / "d1@b").mkdir()
    with pytest.raises(Exception, match="more than one"):
        _find_submission("d1")


def _series(tmp_path, names=("c01", "c02", "c03")):
    """An arb.toml with one automatic check, and a ``subs`` directory of
    submissions, the first two with the file the check wants."""
    (tmp_path / "arb.toml").write_text(
        '[[marker]]\ncriterion = "c"\ntitle = "t"\n'
        '[[marker.step]]\ntype = "file_exists"\nfiles = "a.txt"\nout_of = 1\n'
    )
    subs = tmp_path / "subs"
    for name in names:
        (subs / name).mkdir(parents=True)
    for name in names[:2]:
        (subs / name / "a.txt").write_text("x")
    (subs / ".hidden").mkdir()
    return subs


def test_recursive_marks_every_subdirectory(tmp_path):
    subs = _series(tmp_path)

    result = CliRunner().invoke(
        cli, ["--arb", str(tmp_path / "arb.toml"), "--no-tui", "-r", str(subs)]
    )

    assert result.exit_code == 0, result.output
    for name in ("c01", "c02", "c03"):
        assert (subs / name / "arb-results.toml").exists()
    assert not (subs / ".hidden" / "arb-results.toml").exists()
    assert "c01: 1/1" in result.output
    assert "c03: 0/1" in result.output


def test_several_arguments_are_the_same_as_recursive(tmp_path):
    subs = _series(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["--arb", str(tmp_path / "arb.toml"), "--no-tui",
         str(subs / "c01"), str(subs / "c02")],
    )

    assert result.exit_code == 0, result.output
    assert (subs / "c02" / "arb-results.toml").exists()
    assert not (subs / "c03" / "arb-results.toml").exists()


def test_recursive_skips_complete_submissions_unless_fresh(tmp_path):
    subs = _series(tmp_path)
    args = ["--arb", str(tmp_path / "arb.toml"), "--no-tui", "-r", str(subs)]
    CliRunner().invoke(cli, args)
    (subs / "c03" / "arb-results.toml").unlink()

    again = CliRunner().invoke(cli, args)

    assert "c01: already complete, skipped" in again.output
    assert "c03: 0/1" in again.output
    assert (subs / "c03" / "arb-results.toml").exists()

    fresh = CliRunner().invoke(cli, [*args, "--fresh"])

    assert "skipped" not in fresh.output


def test_single_named_submission_is_marked_even_if_complete(tmp_path):
    subs = _series(tmp_path)
    args = ["--arb", str(tmp_path / "arb.toml"), "--no-tui", str(subs / "c01")]
    CliRunner().invoke(cli, args)

    again = CliRunner().invoke(cli, args)

    assert "skipped" not in again.output
    assert "c: 1/1" in again.output


def test_output_needs_a_single_submission(tmp_path):
    subs = _series(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["--arb", str(tmp_path / "arb.toml"), "--output", str(tmp_path / "o.toml"),
         "-r", str(subs)],
    )

    assert result.exit_code != 0
    assert "--output" in result.output


def test_progress_panel_text():
    pytest.importorskip("textual")
    from arbiter.cli import Progress
    from arbiter.tui import _progress_text

    progress = Progress(5)
    progress.skipped("c01")
    progress.finished("c02")
    progress.finished("c03")

    text = _progress_text(progress).splitlines()
    assert text[0] == "3 done, 2 to go (of 5)"
    assert text[1:] == ["c02: marked", "c03: marked"]


def test_marker_is_asked_between_students_and_can_stop(tmp_path, monkeypatch):
    import arbiter.cli as cli_module

    subs = _series(tmp_path)
    asked = []

    def hook(finished, upcoming, progress):
        asked.append((finished, upcoming))
        return len(asked) < 2

    ask = lambda q: None
    ask.next_student = hook
    monkeypatch.setattr(cli_module, "_choose_ask", lambda tui, progress=None: ask)

    result = CliRunner().invoke(
        cli, ["--arb", str(tmp_path / "arb.toml"), "-r", str(subs)]
    )

    assert asked == [("c01", "c02"), ("c02", "c03")]
    assert result.exit_code != 0  # Aborted at the second pause
    assert (subs / "c02" / "arb-results.toml").exists()
    assert not (subs / "c03" / "arb-results.toml").exists()


def test_help_lists_the_unpack_subcommand():
    result = CliRunner().invoke(cli, ["--help"])
    assert "Subcommands" in result.output and "unpack" in result.output
