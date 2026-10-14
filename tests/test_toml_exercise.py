import re
import os
import textwrap

import pytest
from click.testing import CliRunner

from arbiter.cli import cli
from arbiter.toml_exercise import ArbTomlError, load_exercise

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples", "greeting")


def _run_example(tmp_path, submission, answers=""):
    result = CliRunner().invoke(
        cli,
        [
            "--arb",
            os.path.join(EXAMPLE, "arb.toml"),
            "--output",
            str(tmp_path / "results.toml"),
            os.path.join(EXAMPLE, "submissions", submission),
        ],
        input=answers,
    )
    assert result.exit_code == 0, result.output
    return result.output


def test_example_correct_submission_is_decided_mechanically(tmp_path):
    output = _run_example(tmp_path, "correct", "2\n")
    assert "correctness: 10/10 -- Your program greets Ada as required" in output
    assert "No expected output matched" not in output


def test_example_partial_credit(tmp_path):
    output = _run_example(tmp_path, "sloppy", "1\n")
    assert "correctness: 7/10 -- Right idea" in output


def test_example_explicit_zero_does_not_ask(tmp_path):
    output = _run_example(tmp_path, "ignores_name", "0\n")
    assert "correctness: 0/10 -- Your program ignores the name" in output
    assert "No expected output matched" not in output


def test_example_undecided_asks_and_quotes_stdout(tmp_path):
    output = _run_example(tmp_path, "odd", "6\n2\n")
    assert "It printed:\nGreetings, Ada" in output
    assert "correctness: 6.0/10 -- marker-entered" in output


def test_example_style_question_quotes_the_source(tmp_path):
    assert 'print("Hello, World!")' in _run_example(tmp_path, "ignores_name", "0\n")


def _write(tmp_path, text):
    path = tmp_path / "arb.toml"
    path.write_text(textwrap.dedent(text))
    return str(path)


def test_rubric_path_is_relative_to_the_toml(tmp_path):
    path = _write(
        tmp_path,
        """
        rubric = "r.toml"
        [[marker]]
        criterion = "c"
        """,
    )
    _, rubric = load_exercise(path, str(tmp_path))
    assert rubric == str(tmp_path / "r.toml")


@pytest.mark.parametrize(
    "body, message",
    [
        ("", "no [[marker]]"),
        ('[[marker]]\n[[marker.step]]\ntype = "nope"\n', "unknown step type"),
        ('[[marker]]\n[[marker.step]]\ntype = "python"\n', "missing 'entry_point'"),
        (
            '[[marker]]\n[[marker.step]]\ntype = "match_stdout"\nout_of = 1\n'
            '[[marker.step.match]]\ntype = "fuzzy"\n',
            "unknown match type",
        ),
    ],
)
def test_bad_toml_gives_a_clear_error(tmp_path, body, message):
    with pytest.raises(ArbTomlError, match=re.escape(message)):
        load_exercise(_write(tmp_path, body), str(tmp_path))


def test_default_arb_lookup_falls_back_to_arb_toml(tmp_path, monkeypatch):
    (tmp_path / "s.py").write_text("print('x')\n")
    _write(
        tmp_path,
        """
        [[marker]]
        criterion = "c"
        [[marker.step]]
        type = "python"
        entry_point = "s.py"
        [[marker.step]]
        type = "match_stdout"
        out_of = 3
        [[marker.step.match]]
        type = "exact"
        match = "x\\n"
        feedback = "ok"
        score = 3
        """,
    )
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, [str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "c: 3/3 -- ok" in result.output


def test_default_arb_lookup_prefers_arb_toml_over_arb_py(tmp_path, monkeypatch):
    (tmp_path / "arb.py").write_text("raise RuntimeError('arb.py was loaded')\n")
    (tmp_path / "s.py").write_text("print('x')\n")
    _write(
        tmp_path,
        """
        [[marker]]
        criterion = "c"
        """,
    )
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, [str(tmp_path)])
    assert result.exit_code == 0, result.output
