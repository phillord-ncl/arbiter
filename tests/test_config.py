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


def test_viewer_closes_everything_it_opened(tmp_path):
    from arbiter.config import Viewer

    log = tmp_path / "log"
    viewer = Viewer(
        "sh -c 'echo open {file} >> " + str(log) + "'",
        "sh -c 'echo close {file} >> " + str(log) + "'",
    )
    viewer.open_file("a")
    viewer.open_file("b")
    viewer.close_file("a")
    viewer.close_all()
    assert log.read_text().split("\n")[:-1] == [
        "open a", "open b", "close a", "close b"
    ]
    assert viewer.opened == []


def test_close_dir_is_used_for_everything_under_the_directory(tmp_path):
    from arbiter.config import Viewer

    log = tmp_path / "log"
    viewer = Viewer(
        "true {file}",
        "sh -c 'echo close {file} >> " + str(log) + "'",
        "sh -c 'echo dir {dir} >> " + str(log) + "'",
    )
    viewer.open_file("a")
    viewer.close_all(str(tmp_path / "s 1"))
    assert log.read_text() == "dir {}\n".format(tmp_path / "s 1")
    assert viewer.opened == []


from arbiter.config import preset_viewer, save_viewer


def test_presets_differ_by_platform():
    assert preset_viewer("vscode", "linux").open.startswith("code ")
    assert preset_viewer("vscode", "win32").open.startswith("code.cmd ")
    assert preset_viewer("emacsclient", "linux").open.startswith("emacsclient ")
    assert preset_viewer("emacsclient", "win32").open.startswith("emacsclientw.exe ")
    assert preset_viewer("emacsclient", "win32").close is None
    assert preset_viewer("emacsclient", "linux").close_dir is not None
    assert preset_viewer("emacs", "linux").open == "emacs {file}"
    assert preset_viewer("emacs", "linux").detach
    assert preset_viewer("emacs", "win32").open.startswith("runemacs.exe ")
    assert preset_viewer("emacs", "darwin").open.startswith("open -a Emacs")
    assert preset_viewer("pycharm", "darwin").open.startswith("open -a PyCharm")


def test_saved_viewer_loads_back(tmp_path):
    path = str(tmp_path / "sub" / "config.toml")
    for name in ("emacsclient", "emacs"):
        saved = save_viewer(name, path, "linux")
        assert load_viewer(path) == saved


def test_detached_viewer_does_not_wait(tmp_path):
    viewer = Viewer(
        sys.executable + " -c 'import time; time.sleep(30)' {file}", detach=True
    )
    viewer.open_file(str(tmp_path / "f"))  # would hang for 30s if it waited


def test_save_viewer_replaces_only_the_viewer_section(tmp_path):
    path = _write(
        tmp_path,
        '[terminal]\nopen = "kitty {dir}"\n\n[viewer]\nopen = "old {file}"\n'
        'close = "x"\n\n[other]\na = 1\n',
    )
    save_viewer("vscode", path, "linux")
    text = (tmp_path / "config.toml").read_text()
    assert 'open = "kitty {dir}"' in text and "[other]" in text
    assert "old" not in text and text.count("[viewer]") == 1
    assert load_viewer(path).open == "code --reuse-window {file}"


def test_save_none_removes_the_viewer(tmp_path):
    path = _write(tmp_path, '[viewer]\nopen = "old {file}"\n')
    assert save_viewer(None, path) is None
    assert load_viewer(path) is None
