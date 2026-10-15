import sys

import pytest

from arbiter.config import ConfigError, Viewer, default_viewer, load_viewer


def _write(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text)
    return str(path)


def test_no_config_file_means_no_viewer(tmp_path):
    assert load_viewer(str(tmp_path / "missing.toml")) is None


def test_config_without_viewer_means_no_viewer(tmp_path):
    assert load_viewer(_write(tmp_path, "[other]\nx = 1\n")) is None


def test_open_only(tmp_path):
    viewer = load_viewer(_write(tmp_path, '[viewer]\nopen = "ed {file}"\n'))
    assert viewer == Viewer("ed {file}", None)


def test_open_and_close(tmp_path):
    viewer = load_viewer(
        _write(tmp_path, '[viewer]\nopen = "ed {file}"\nclose = "bye {file}"\n')
    )
    assert viewer == Viewer("ed {file}", "bye {file}")


def test_viewer_without_open_is_an_error(tmp_path):
    with pytest.raises(ConfigError):
        load_viewer(_write(tmp_path, '[viewer]\nclose = "x"\n'))


def test_bad_toml_is_an_error(tmp_path):
    with pytest.raises(ConfigError):
        load_viewer(_write(tmp_path, "[viewer\n"))


def test_open_substitutes_path_with_spaces(tmp_path):
    target = tmp_path / "out.txt"
    script = tmp_path / "w.py"
    script.write_text(
        "import sys\nopen(sys.argv[1], 'w').write(sys.argv[2])\n"
    )
    viewer = Viewer('"{}" "{}" "{}" {{file}}'.format(sys.executable, script, target))
    viewer.open_file("a file with spaces.py")
    assert target.read_text() == "a file with spaces.py"


def test_close_without_command_does_nothing():
    Viewer("x {file}").close_file("f")


def test_default_viewer_is_vscode_on_windows_when_installed():
    viewer = default_viewer("win32", which=lambda name: "C:\\code.cmd")
    assert viewer == Viewer("code.cmd --reuse-window {file}")


def test_no_default_viewer_without_vscode_or_off_windows():
    assert default_viewer("win32", which=lambda name: None) is None
    assert default_viewer("linux", which=lambda name: "/usr/bin/code.cmd") is None
