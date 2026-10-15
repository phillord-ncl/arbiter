import os
import subprocess
import sys

import pytest
from click.testing import CliRunner

from arbiter import scripts
from arbiter.cli import cli
from arbiter.core import Exercise, Result, RunMarker
from arbiter.scripts import BUILTIN, Script, ScriptClash
from arbiter.terminal import TerminalError, default_command, open_terminal

posix_only = pytest.mark.skipif(os.name == "nt", reason="runs the POSIX scripts")


def test_interpreter_per_platform_and_version():
    assert scripts.interpreter(None, windows=False) == ["python3"]
    assert scripts.interpreter("3.14", windows=False) == ["python3.14"]
    assert scripts.interpreter(None, windows=True) == ["py", "-3"]
    assert scripts.interpreter("3.14", windows=True) == ["py", "-3.14"]


def test_posix_script_bootstraps_then_runs_in_the_venv():
    text = scripts.render(Script("marker-run", ["python", "a b.py"]), "3.14", windows=False)
    assert text.startswith("#!/bin/sh\n# arbiter-generated: marker-run\n")
    assert "python3.14 -m venv marker-venv" in text
    assert "marker-venv/bin/python -m pip install -q -r requirements.txt" in text
    assert text.rstrip().endswith("""exec marker-venv/bin/python 'a b.py' "$@\"""")


def test_windows_script_uses_scripts_dir_and_py_launcher():
    text = scripts.render(Script("marker-run", ["python", "a.py"]), "3.14", windows=True)
    assert "\r\n" in text
    assert "rem arbiter-generated: marker-run" in text
    assert "py -3.14 -m venv marker-venv" in text
    assert r"marker-venv\Scripts\python.exe a.py %*" in text


def test_pip_without_arguments_only_bootstraps():
    pip = BUILTIN[1]
    assert 'if [ $# -gt 0 ]; then' in scripts.render(pip, windows=False)
    assert 'if not "%~1"==""' in scripts.render(pip, windows=True)


def test_script_files_per_platform(tmp_path):
    assert scripts.filename("marker-python", windows=False) == "marker-python"
    assert scripts.filename("marker-python", windows=True) == "marker-python.cmd"


def test_write_scripts_is_idempotent_and_executable(tmp_path):
    first = scripts.write_scripts(str(tmp_path), BUILTIN, windows=False)
    assert [os.path.basename(p) for p in first] == ["marker-python", "marker-pip"]
    assert os.access(first[0], os.X_OK)
    # Our own earlier scripts are not a clash.
    assert scripts.write_scripts(str(tmp_path), BUILTIN, windows=False) == first


def test_a_clash_stops_and_writes_nothing(tmp_path):
    (tmp_path / "marker-pip").write_text("student's own file\n")
    with pytest.raises(ScriptClash) as e:
        scripts.write_scripts(str(tmp_path), BUILTIN, windows=False)
    assert "marker-pip" in str(e.value)
    assert not (tmp_path / "marker-python").exists()
    assert (tmp_path / "marker-pip").read_text() == "student's own file\n"


def test_a_venv_dir_that_is_not_a_venv_is_a_clash(tmp_path):
    (tmp_path / "marker-venv").mkdir()
    with pytest.raises(ScriptClash):
        scripts.write_scripts(str(tmp_path), BUILTIN, windows=False)


@posix_only
def test_marker_python_makes_a_venv_and_runs_in_it(tmp_path):
    (tmp_path / "requirements.txt").write_text("# nothing needed\n")
    (tmp_path / "where.py").write_text("import sys\nprint(sys.prefix)\nprint(sys.argv[1:])\n")
    scripts.write_scripts(str(tmp_path), BUILTIN)
    run = subprocess.run(
        [str(tmp_path / "marker-python"), "where.py", "x y"],
        capture_output=True,
        text=True,
        cwd="/",
    )
    assert run.returncode == 0, run.stderr
    prefix, argv = run.stdout.splitlines()
    assert os.path.realpath(prefix) == os.path.realpath(tmp_path / "marker-venv")
    assert argv == "['x y']"
    # A second run reuses the venv.
    again = subprocess.run(
        [str(tmp_path / "marker-python"), "where.py"], capture_output=True, text=True
    )
    assert again.returncode == 0, again.stderr


@posix_only
def test_python_step_with_venv_runs_through_marker_python(tmp_path):
    (tmp_path / "where.py").write_text("import sys\nprint(sys.prefix)\n")
    marker = RunMarker(str(tmp_path), criterion="a")
    marker.python("where.py", venv=True)
    marker.ask_for_score("?", 1)
    exercise = Exercise(marker)
    exercise.use_scripts = True
    exercise.prepare(str(tmp_path))
    seen = []
    exercise.run(
        lambda q: (seen.append(q.context[0].text), Result(1, 1, ""))[1],
        directory=str(tmp_path),
    )
    assert os.path.realpath(seen[0].strip()) == os.path.realpath(tmp_path / "marker-venv")


def test_prepare_does_nothing_unless_the_exercise_uses_scripts(tmp_path):
    Exercise().prepare(str(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_our_files_are_left_out_of_the_submission_listing(tmp_path):
    (tmp_path / "a.py").write_text("")
    scripts.write_scripts(str(tmp_path), BUILTIN)
    (tmp_path / "marker-venv").mkdir(exist_ok=True)
    (tmp_path / "marker-venv" / "pyvenv.cfg").write_text("")
    names = [i.title for i in RunMarker(str(tmp_path))._submission_files()]
    assert names == ["a.py"]


def test_toml_declares_scripts_and_version(tmp_path):
    from arbiter.toml_exercise import load_exercise

    arb = tmp_path / "arb.toml"
    arb.write_text(
        """
python_version = "3.14"
[[script]]
name = "marker-run"
command = ["python", "app.py"]
[[marker]]
criterion = "a"
[[marker.step]]
type = "ask_for_score"
question = "?"
out_of = 1
"""
    )
    exercise, _ = load_exercise(str(arb), str(tmp_path))
    assert exercise.use_scripts and exercise.python_version == "3.14"
    assert [s.name for s in exercise.all_scripts()] == [
        "marker-python",
        "marker-pip",
        "marker-run",
    ]


def test_toml_without_scripts_writes_none(tmp_path):
    from arbiter.toml_exercise import load_exercise

    arb = tmp_path / "arb.toml"
    arb.write_text(
        '[[marker]]\ncriterion="a"\n[[marker.step]]\ntype="ask_for_score"\nquestion="?"\nout_of=1\n'
    )
    exercise, _ = load_exercise(str(arb), str(tmp_path))
    assert not exercise.use_scripts


def test_cli_stops_on_a_clash(tmp_path):
    sub = tmp_path / "s"
    sub.mkdir()
    (sub / "marker-python").write_text("mine\n")
    arb = tmp_path / "arb.toml"
    arb.write_text(
        'python_version = "3"\n[[marker]]\ncriterion="a"\n[[marker.step]]\n'
        'type="ask_for_score"\nquestion="?"\nout_of=1\n'
    )
    result = CliRunner().invoke(cli, ["--arb", str(arb), "--no-tui", str(sub)], input="1\n")
    assert result.exit_code != 0
    assert "marker-python" in result.output
    assert (sub / "marker-python").read_text() == "mine\n"


# ---- terminal -------------------------------------------------------------


class _Popen:
    def __init__(self):
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))


def test_configured_terminal_gets_the_directory_and_cwd():
    popen = _Popen()
    args = open_terminal(
        "/work/s one", "kitty --directory {dir}", platform="linux", popen=popen
    )
    assert args == ["kitty", "--directory", "/work/s one"]
    assert popen.calls[0][1]["cwd"] == "/work/s one"


def test_default_terminals_per_platform():
    none = lambda name: None
    only = lambda *have: (lambda name: "/bin/" + name if name in have else None)
    assert default_command("windows", only("wt")) == ["wt", "-d", "{dir}"]
    assert default_command("windows", none)[:2] == ["cmd", "/c"]
    assert default_command("darwin", none)[:3] == ["open", "-a", "Terminal"]
    assert default_command("linux", only("xterm"), {}) == ["xterm"]
    assert default_command("linux", only("xterm"), {"TERMINAL": "foot -e"}) == ["foot", "-e"]
    assert default_command("linux", none, {}) is None
    both = lambda n: n if n in ("xdg-terminal-exec", "xterm") else None
    assert default_command("linux", both, {}) == ["xdg-terminal-exec"]


def test_no_terminal_is_a_clear_error():
    with pytest.raises(TerminalError, match="no terminal found"):
        open_terminal("/d", platform="linux", popen=_Popen(), which=lambda n: None, environ={})


def test_terminal_that_will_not_start_is_a_clear_error():
    def boom(args, **kwargs):
        raise FileNotFoundError("nope")

    with pytest.raises(TerminalError, match="cannot start"):
        open_terminal("/d", "nosuch {dir}", platform="linux", popen=boom)


def test_load_terminal_reads_config(tmp_path):
    from arbiter.config import ConfigError, load_terminal

    path = tmp_path / "config.toml"
    assert load_terminal(str(path)) is None
    path.write_text('[terminal]\nopen = "kitty --directory {dir}"\n')
    assert load_terminal(str(path)) == "kitty --directory {dir}"
    path.write_text("[terminal]\n")
    with pytest.raises(ConfigError):
        load_terminal(str(path))
