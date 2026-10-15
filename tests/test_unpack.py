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


def test_canvas_download_is_gathered_per_student(tmp_path):
    down, out = tmp_path / "down", tmp_path / "out"
    down.mkdir()
    make_zip(down / "smithjo_1_10_my project.zip", ["a.py"])
    make_zip(down / "doeana_LATE_2_20_p.zip", ["d/a.py"])
    (down / "doeana_2_21_notes.txt").write_text("hi")
    result = CliRunner().invoke(unpack_cmd, ["--canvas", str(out), str(down)])
    assert result.exit_code != 0  # doeana has an archive and a loose file
    assert (out / "smithjo_1" / "project" / "a.py").exists()
    assert (out / "smithjo_1" / "my project.zip").exists()
    meta = (out / "doeana_2" / "canvas.toml").read_text()
    assert "late = true" in meta and 'user_id = 2' in meta
    assert sorted(os.listdir(down)) == sorted(
        ["smithjo_1_10_my project.zip", "doeana_LATE_2_20_p.zip",
         "doeana_2_21_notes.txt"]
    )


def test_canvas_refuses_oddly_named_files(tmp_path):
    (tmp_path / "down").mkdir()
    (tmp_path / "down" / "mystery.zip").write_text("")
    result = CliRunner().invoke(
        unpack_cmd, ["--canvas", str(tmp_path / "out"), str(tmp_path / "down")]
    )
    assert result.exit_code != 0 and "not named like" in result.output


def test_canvas_submissions_zip_is_read_directly(tmp_path):
    inner = tmp_path / "in"
    inner.mkdir()
    make_zip(inner / "smithjo_1_10_p.zip", ["a.py"])
    with zipfile.ZipFile(tmp_path / "submissions.zip", "w") as z:
        z.write(inner / "smithjo_1_10_p.zip", "smithjo_1_10_p.zip")
    out = tmp_path / "out"
    result = CliRunner().invoke(
        unpack_cmd, ["--canvas", str(out), str(tmp_path / "submissions.zip")]
    )
    assert result.exit_code == 0, result.output
    assert (out / "smithjo_1" / "project" / "a.py").exists()
    assert sorted(os.listdir(out)) == ["smithjo_1"]
