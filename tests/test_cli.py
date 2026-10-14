import pytest
import textwrap

from click.testing import CliRunner

from tent_arbiter.cli import cli


ARB_PY = textwrap.dedent(
    """
    import os

    from tent_arbiter.core import Exercise, RunMarker
    from tent_arbiter.matchers import Exact

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
    from tent_arbiter.cli import _default_ask_interactively
    from tent_arbiter.core import ContextItem, Question

    monkeypatch.setattr("builtins.input", lambda prompt: "3")
    question = Question("score? ", 5, [ContextItem("stdout", text="hello\n")])
    result = _default_ask_interactively(question)
    assert result.score == 3
    out = capsys.readouterr().out
    assert "--- stdout" in out and "hello" in out


def test_no_tui_and_non_terminal_use_the_plain_prompt():
    from tent_arbiter.cli import _choose_ask, _default_ask_interactively

    assert _choose_ask(False) is _default_ask_interactively
    # Under pytest stdin is not a terminal.
    assert _choose_ask(None) is _default_ask_interactively


def test_tui_flag_builds_the_textual_hook():
    pytest.importorskip("textual")
    from tent_arbiter.cli import _choose_ask, _default_ask_interactively

    assert _choose_ask(True) is not _default_ask_interactively
