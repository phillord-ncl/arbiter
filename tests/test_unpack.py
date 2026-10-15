import os
import zipfile

import pytest
from click.testing import CliRunner

from arbiter.cli import unpack_cmd
from arbiter.unpack import UnpackError, unpack


def make_zip(path, names):
    with zipfile.ZipFile(path, "w") as z:
        for name in names:
            z.writestr(name, "x = 1\n" if not name.endswith("/") else "")


def project(sub):
    return sorted(
        os.path.relpath(os.path.join(h, f), sub / "project")
        for h, _, files in os.walk(sub / "project")
        for f in files
    )


def test_single_directory(tmp_path):
    make_zip(tmp_path / "a.zip", ["My Project/a.py", "My Project/doc/r.md"])
    assert "1 level" in unpack(str(tmp_path))
    assert project(tmp_path) == ["a.py", os.path.join("doc", "r.md")]
    assert (tmp_path / "a.zip").exists()


def test_tarbomb(tmp_path):
    make_zip(tmp_path / "a.zip", ["a.py", "doc/r.md", "README.md"])
    assert "unpacked" in unpack(str(tmp_path))
    assert (tmp_path / "project" / "a.py").exists()
    assert (tmp_path / "project" / "README.md").exists()


def test_nested_wrappers_and_junk(tmp_path):
    make_zip(
        tmp_path / "a.zip",
        ["__MACOSX/._a.py", "one/two/a.py", "one/two/.DS_Store", "one/two/b.py"],
    )
    assert "2 levels" in unpack(str(tmp_path))
    assert project(tmp_path) == ["a.py", "b.py"]


def test_wrapper_with_a_sibling_file_is_kept(tmp_path):
    make_zip(tmp_path / "a.zip", ["README.md", "src/a.py"])
    unpack(str(tmp_path))
    assert project(tmp_path) == ["README.md", os.path.join("src", "a.py")]


def test_loose_files_are_copied(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "arb-results.toml").write_text("")
    (tmp_path / "tent-peg.toml").write_text("")
    assert "copied a.py" in unpack(str(tmp_path))
    assert project(tmp_path) == ["a.py"]
    assert (tmp_path / "a.py").exists()


def test_existing_project_is_left_alone_unless_forced(tmp_path):
    make_zip(tmp_path / "a.zip", ["a.py"])
    unpack(str(tmp_path))
    (tmp_path / "project" / "mine.txt").write_text("")
    assert "left alone" in unpack(str(tmp_path))
    assert (tmp_path / "project" / "mine.txt").exists()
    unpack(str(tmp_path), force=True)
    assert not (tmp_path / "project" / "mine.txt").exists()


def test_problems_are_errors(tmp_path):
    with pytest.raises(UnpackError, match="no files"):
        unpack(str(tmp_path))
    (tmp_path / "a.zip").write_text("not a zip")
    with pytest.raises(UnpackError, match="cannot read"):
        unpack(str(tmp_path))
    (tmp_path / "a.zip").unlink()
    make_zip(tmp_path / "a.zip", ["a.py"])
    make_zip(tmp_path / "b.zip", ["b.py"])
    with pytest.raises(UnpackError, match="more than one"):
        unpack(str(tmp_path))
    assert not (tmp_path / "project").exists()
    assert not (tmp_path / ".unpack-tmp").exists()


def test_command_goes_on_after_a_bad_submission(tmp_path):
    for name in ("c01", "c02"):
        (tmp_path / name).mkdir()
    (tmp_path / "c01" / "a.zip").write_text("not a zip")
    make_zip(tmp_path / "c02" / "a.zip", ["a.py"])
    result = CliRunner().invoke(unpack_cmd, ["-r", str(tmp_path)])
    assert result.exit_code != 0
    assert (tmp_path / "c02" / "project" / "a.py").exists()
