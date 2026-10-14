import os
import tomllib

import pytest
from click.testing import CliRunner

from tent_arbiter.cli import cli
from tent_arbiter.core import Exercise, Result, RunMarker
from tent_arbiter.dump import Dumper

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples", "greeting")


def _exercise(tmp_path):
    (tmp_path / "s.py").write_text("print('x')\n")
    marker = RunMarker(str(tmp_path), criterion="a")
    marker.python("s.py").ask_for_score("one?", 5)
    other = RunMarker(str(tmp_path), criterion="b")
    other.ask_for_score("two?", 5)
    return Exercise(marker, other)


def _answer(question):
    return Result(out_of=question.out_of, score=4, feedback='said "hi"\nline two')


def _load(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def test_toml_round_trips_awkward_strings(tmp_path):
    exercise = _exercise(tmp_path)
    dumper = Dumper(str(tmp_path / "out"), str(tmp_path), None)
    exercise.run(_answer)
    dumper.write(exercise, complete=True)
    data = _load(tmp_path / "out.toml")
    assert data["complete"] is True
    assert (data["score"], data["out_of"]) == (8, 10)
    assert data["result"][0]["feedback"] == 'said "hi"\nline two'
    assert data["result"][0]["decided_by"] == "human"


def test_results_are_written_after_every_human_answer(tmp_path):
    exercise = _exercise(tmp_path)
    dumper = Dumper(str(tmp_path / "out"), str(tmp_path), None)
    calls = []

    def ask(question):
        if calls:
            # The first answer must already be on disk when asked the second.
            assert len(_load(tmp_path / "out.toml")["result"]) == 1
            raise KeyboardInterrupt
        calls.append(question)
        return _answer(question)

    with pytest.raises(KeyboardInterrupt):
        exercise.run(ask, checkpoint=dumper.write)
    data = _load(tmp_path / "out.toml")
    assert data["complete"] is False
    assert len(data["result"]) == 1


def test_mechanical_results_are_saved_before_any_question(tmp_path):
    exercise = _exercise(tmp_path)
    marker = RunMarker(str(tmp_path), criterion="m")
    marker.python("s.py").match_stdout(3)  # no matchers: undecided, scores 0
    exercise.markers.append(marker)
    dumper = Dumper(str(tmp_path / "out"), str(tmp_path), None)

    def ask(question):
        data = _load(tmp_path / "out.toml")
        assert [r["criterion"] for r in data["result"]] == ["m"]
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        exercise.run(ask, checkpoint=dumper.write)


def test_text_format_is_written_beside_the_toml(tmp_path):
    exercise = _exercise(tmp_path)
    dumper = Dumper(str(tmp_path / "out"), str(tmp_path), None, ["text"])
    exercise.run(_answer)
    dumper.write(exercise, complete=True)
    text = (tmp_path / "out.txt").read_text()
    assert "a: 4/5" in text and "Total: 8/10" in text
    assert "not finished" not in text


def test_unknown_format_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="nope"):
        Dumper(str(tmp_path / "out"), str(tmp_path), None, ["nope"])


def test_no_temporary_files_are_left_behind(tmp_path):
    exercise = _exercise(tmp_path)
    Dumper(str(tmp_path / "out"), str(tmp_path), None).write(exercise)
    assert sorted(os.listdir(tmp_path)) == ["out.toml", "s.py"]


def _copy_submission(tmp_path):
    import shutil

    target = tmp_path / "sub"
    shutil.copytree(os.path.join(EXAMPLE, "submissions", "odd"), target)
    return target


def test_cli_writes_toml_into_the_submission_by_default(tmp_path):
    sub = _copy_submission(tmp_path)
    result = CliRunner().invoke(
        cli, ["--arb", os.path.join(EXAMPLE, "arb.toml"), str(sub)], input="6\n2\n"
    )
    assert result.exit_code == 0, result.output
    data = _load(sub / ".arb-results.toml")
    assert data["complete"] is True
    assert data["rubric"].endswith("greeting.rubric.toml")
    assert [r["decided_by"] for r in data["result"]] == ["human", "human"]


def test_cli_output_and_also_options(tmp_path):
    sub = _copy_submission(tmp_path)
    out = tmp_path / "elsewhere" / "marks.toml"
    out.parent.mkdir()
    result = CliRunner().invoke(
        cli,
        ["--arb", os.path.join(EXAMPLE, "arb.toml"), "--output", str(out),
         "--also", "text", str(sub)],
        input="6\n2\n",
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert (out.parent / "marks.txt").exists()
    assert not (sub / ".arb-results.toml").exists()
