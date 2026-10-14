import os
import subprocess

import pytest

from arbiter import submission
from arbiter.core import Exercise, Result, RunMarker

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.org",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.org",
}


def _git(path, *args):
    subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        env={**os.environ, **GIT_ENV},
    )


def _repo(path, *commits):
    """A repo with one commit per ``(message, {file: text})``."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    for message, files in commits:
        for name, text in files.items():
            target = path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        _git(path, "add", "-A")
        _git(path, "commit", "-q", "-m", message)


def _score(tmp_path, build, answers=()):
    """Run a one-marker Exercise; ``build(marker)`` adds its steps.
    Returns (results, questions asked)."""
    marker = RunMarker(str(tmp_path), criterion="c")
    build(marker)
    asked = []
    queue = iter(answers)

    def ask(question):
        asked.append(question)
        return Result(question.out_of, next(queue), "human")

    Exercise(marker).run(ask)
    return marker.results, asked


# ---- finding the submission ------------------------------------------------


def test_root_is_found_through_wrapper_directories(tmp_path):
    _repo(tmp_path / "id" / "project", ("one", {"a.py": ""}))
    assert submission.submission_root(str(tmp_path)) == str(tmp_path / "id" / "project")


def test_root_ignores_macos_noise_and_our_files(tmp_path):
    _repo(tmp_path / "project", ("one", {"a.py": ""}))
    (tmp_path / "__MACOSX").mkdir()
    (tmp_path / ".DS_Store").write_text("")
    (tmp_path / "marker-python").write_text("")
    assert submission.submission_root(str(tmp_path)) == str(tmp_path / "project")


def test_root_without_a_git_directory_is_still_the_inner_project(tmp_path):
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "a.py").write_text("")
    assert submission.submission_root(str(tmp_path)) == str(tmp_path / "project")


def test_root_is_the_directory_when_it_is_not_just_a_wrapper(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.py").write_text("")
    assert submission.submission_root(str(tmp_path)) == str(tmp_path)


def test_walk_skips_hidden_virtualenv_and_our_files(tmp_path):
    for name in ["a.py", "doc/r.md", ".venv/x.py", "env/pyvenv.cfg", "env/y.py",
                 "marker-venv/z.py", "marker-python", "__pycache__/c.pyc"]:
        f = tmp_path / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("")
    assert list(submission.walk(str(tmp_path))) == ["a.py", "doc/r.md"]


def test_globs_ignore_case_and_match_names_anywhere():
    assert submission.matches("docs/ReadMe.MD", "readme.md")
    assert not submission.matches("docs/ReadMe.MD", "doc/*.md")
    assert submission.matches("doc/x.md", "doc/*.md")


# ---- file checks -----------------------------------------------------------


def test_file_exists_accepts_either_spelling(tmp_path):
    (tmp_path / "LICENSE.md").write_text("")
    results, asked = _score(tmp_path, lambda m: m.file_exists(1, "licence.md", "license.md"))
    assert (results[0].score, results[0].out_of) == (1, 1) and not asked


def test_a_failed_check_scores_zero_with_what_it_found(tmp_path):
    results, _ = _score(tmp_path, lambda m: m.file_exists(1, "README.md"))
    assert results[0].score == 0
    assert "no file matching README.md" in results[0].feedback


def test_a_failed_check_hands_over_to_a_human_who_sees_why(tmp_path):
    def build(m):
        m.file_exists(1, "README.md")
        m.or_else()
        m.ask_for_score("Is there a readme somewhere odd?", 1)

    results, asked = _score(tmp_path, build, answers=[1])
    assert results[0].decided_by == "human"
    notes = [c.text for c in asked[0].context if c.title == "Automatic checks"]
    assert "no file matching README.md" in notes[0]


def test_a_passed_check_does_not_ask(tmp_path):
    (tmp_path / "README.md").write_text("hi")

    def build(m):
        m.file_exists(1, "README.md")
        m.or_else()
        m.ask_for_score("?", 1)

    results, asked = _score(tmp_path, build)
    assert results[0].score == 1 and not asked


def test_file_contains_is_case_insensitive(tmp_path):
    (tmp_path / "requirements.txt").write_text("Rich==13.7.0\nrequests\n")
    results, _ = _score(tmp_path, lambda m: m.file_contains(1, "requirements.txt", "rich"))
    assert results[0].score == 1
    results, _ = _score(tmp_path, lambda m: m.file_contains(1, "requirements.txt", "numpy"))
    assert results[0].score == 0


def test_files_match_finds_a_print_anywhere(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\nprint('hi')\n")
    results, _ = _score(tmp_path, lambda m: m.files_match(1, "*.py", r"\bprint\b"))
    assert results[0].score == 1


def test_checks_chain_with_or_else(tmp_path):
    _repo(tmp_path, ("Add hello_world", {"a.py": "x = 1\n"}))

    def build(m):
        m.files_match(1, "*.py", r"\bprint\b")
        m.or_else()
        m.git_log_matches(1, "hello_world", diffs=False)
        m.or_else()
        m.ask_for_score("?", 1)

    results, asked = _score(tmp_path, build)
    assert results[0].score == 1 and not asked
    assert "message matches" in results[0].feedback


def test_word_count_with_allowance_and_human_fallback(tmp_path):
    (tmp_path / "doc").mkdir()
    (tmp_path / "doc" / "r.md").write_text("word " * 520)
    results, _ = _score(tmp_path, lambda m: m.word_count(1, "doc/*.md", 300, 500, over=0.1))
    assert results[0].score == 1
    (tmp_path / "doc" / "r.md").write_text("word " * 600)

    def build(m):
        m.word_count(1, "doc/*.md", 300, 500, over=0.1)
        m.or_else()
        m.ask_for_score("?", 1)

    results, asked = _score(tmp_path, build, answers=[0])
    assert results[0].decided_by == "human"
    assert "has 600 words, wanted 300 to 500" in asked[0].context[0].text


def test_word_count_with_no_such_file_is_undecided(tmp_path):
    results, _ = _score(tmp_path, lambda m: m.word_count(1, "doc/*.md", 300, 500))
    assert results[0].score == 0 and "no file matching" in results[0].feedback


def test_unexpected_hidden_files_are_noted_not_scored(tmp_path):
    for d in [".git", ".venv", ".idea", "__MACOSX"]:
        (tmp_path / d).mkdir()
    (tmp_path / ".gitignore").write_text("")

    def build(m):
        m.note_unexpected_hidden()
        m.ask_for_score("Deduct?", 0, choices=[0, -1])

    results, asked = _score(tmp_path, build, answers=[-1])
    assert results[0].score == -1
    assert asked[0].context[0].text == "Unexpected hidden files: .idea, .venv"


def test_nothing_unexpected_is_still_noted(tmp_path):
    def build(m):
        m.note_unexpected_hidden()
        m.ask_for_score("Deduct?", 0, choices=[0, -1])

    _, asked = _score(tmp_path, build, answers=[0])
    assert asked[0].context[0].text == "No unexpected hidden files"


# ---- git checks ------------------------------------------------------------


def test_commit_count(tmp_path):
    _repo(tmp_path, *[("c%d" % i, {"f": str(i)}) for i in range(4)])
    results, _ = _score(tmp_path, lambda m: m.git_commit_count(1, 4))
    assert results[0].score == 1
    results, _ = _score(tmp_path, lambda m: m.git_commit_count(1, 5))
    assert results[0].score == 0 and "4 commit(s), wanted at least 5" in results[0].feedback


def test_no_git_directory_is_not_found_in_a_parent_repo(tmp_path):
    _repo(tmp_path, ("outer", {"f": "x"}))
    inner = tmp_path / "inner"
    inner.mkdir()
    results, _ = _score(inner, lambda m: m.git_commit_count(1, 1))
    assert results[0].score == 0 and "no .git" in results[0].feedback


def test_git_log_matches_messages_and_diffs(tmp_path):
    _repo(tmp_path, ("Start", {"a.py": "print('hello')\n"}), ("Tidy", {"a.py": "x = 1\n"}))
    results, _ = _score(tmp_path, lambda m: m.git_log_matches(1, r"\bprint\b", messages=False))
    assert results[0].score == 1 and "diff matches" in results[0].feedback
    results, _ = _score(tmp_path, lambda m: m.git_log_matches(1, "print", diffs=False))
    assert results[0].score == 0
    results, _ = _score(tmp_path, lambda m: m.git_log_matches(1, "START", diffs=False))
    assert results[0].score == 1


def test_checks_work_when_the_project_is_in_a_wrapper_directory(tmp_path):
    _repo(tmp_path / "project", ("one", {"README.md": "hi"}))
    results, _ = _score(tmp_path, lambda m: m.file_exists(1, "README.md"))
    assert results[0].score == 1
    results, _ = _score(tmp_path, lambda m: m.git_commit_count(1, 1))
    assert results[0].score == 1


# ---- arb.toml --------------------------------------------------------------


def test_toml_builds_the_checks(tmp_path):
    from arbiter.toml_exercise import load_exercise

    arb = tmp_path / "arb.toml"
    arb.write_text(
        """
[[marker]]
criterion = "a"
[[marker.step]]
type = "file_exists"
files = ["README.md", "README"]
out_of = 1
[[marker.step]]
type = "file_contains"
files = "requirements.txt"
pattern = "rich"
out_of = 1
or_else = true
[[marker.step]]
type = "word_count"
files = ["doc/*.md"]
low = 300
high = 500
over = 0.1
out_of = 1
[[marker.step]]
type = "git_commit_count"
at_least = 4
out_of = 1
[[marker.step]]
type = "git_log_matches"
pattern = "hello_world"
diffs = false
out_of = 1
[[marker.step]]
type = "note_unexpected_hidden"
"""
    )
    exercise, _ = load_exercise(str(arb), str(tmp_path))
    assert len(exercise.markers[0].steps) == 6
    assert exercise.max_score() == 4  # the or_else pair counts once


def test_toml_names_the_checks_in_its_error():
    from arbiter.toml_exercise import ArbTomlError, _add_step

    with pytest.raises(ArbTomlError, match="file_exists"):
        _add_step(RunMarker("."), {"type": "nonsense"}, "marker 1 step 1", ".")


def test_word_count_over_allowance_does_not_widen_the_lower_end(tmp_path):
    (tmp_path / "doc").mkdir()

    def passes(words):
        (tmp_path / "doc" / "r.md").write_text("word " * words)
        results, _ = _score(
            tmp_path, lambda m: m.word_count(1, "doc/*.md", 300, 500, over=0.1)
        )
        return results[0].score == 1

    assert [passes(n) for n in (299, 300, 550, 551)] == [False, True, True, False]


# ---- show steps ------------------------------------------------------------


def _context(tmp_path, build):
    _, asked = _score(tmp_path, lambda m: (build(m), m.ask_for_score("?", 1))[1], answers=[1])
    return asked[0].context


def test_show_git_log_puts_the_history_in_front_of_the_marker(tmp_path):
    _repo(tmp_path, ("Add readme", {"README.md": "hi"}), ("Fix typo", {"README.md": "ho"}))
    context = _context(tmp_path, lambda m: m.show_git_log())
    assert context[0].title == "Git log"
    assert "Add readme" in context[0].text and "Fix typo" in context[0].text
    assert "README.md" in context[0].text  # --stat


def test_show_git_log_without_git_says_so(tmp_path):
    context = _context(tmp_path, lambda m: m.show_git_log("History"))
    assert (context[0].title, context[0].text) == ("History", "(no .git directory)")


def test_show_files_gives_one_openable_item_per_file(tmp_path):
    (tmp_path / "doc").mkdir()
    (tmp_path / "doc" / "a.md").write_text("A")
    (tmp_path / "doc" / "b.md").write_text("B")
    (tmp_path / "x.py").write_text("")
    context = _context(tmp_path, lambda m: m.show_files("doc/*.md"))
    assert [(c.title, c.path) for c in context] == [
        ("doc/a.md", str(tmp_path / "doc" / "a.md")),
        ("doc/b.md", str(tmp_path / "doc" / "b.md")),
    ]


def test_show_files_with_no_match_says_so(tmp_path):
    context = _context(tmp_path, lambda m: m.show_files("doc/*.md"))
    assert "no file matching doc/*.md" in context[0].text


def test_show_command_captures_output(tmp_path):
    import sys

    context = _context(
        tmp_path,
        lambda m: m.show_command("echo", [sys.executable, "-c", "print('hello')"]),
    )
    assert (context[0].title, context[0].text.strip()) == ("echo", "hello")


def test_show_command_that_cannot_run_is_reported(tmp_path):
    context = _context(tmp_path, lambda m: m.show_command("x", ["no-such-program-xyz"]))
    assert "could not run no-such-program-xyz" in context[0].text


def test_without_show_steps_every_file_is_listed_with_show_steps_only_those(tmp_path):
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    assert [c.title for c in _context(tmp_path, lambda m: None)] == ["a.py", "b.py"]
    assert [c.title for c in _context(tmp_path, lambda m: m.show_files("a.py"))] == ["a.py"]


def test_toml_builds_the_show_steps(tmp_path):
    from arbiter.toml_exercise import load_exercise

    arb = tmp_path / "arb.toml"
    arb.write_text(
        """
[[marker]]
criterion = "a"
[[marker.step]]
type = "show_git_log"
[[marker.step]]
type = "show_files"
files = ["doc/*.md"]
[[marker.step]]
type = "show_command"
title = "status"
command = ["git", "status", "--short"]
[[marker.step]]
type = "ask_for_score"
question = "?"
out_of = 1
"""
    )
    exercise, _ = load_exercise(str(arb), str(tmp_path))
    assert len(exercise.markers[0].steps) == 4


def test_plain_prompt_prints_shown_files_in_full(tmp_path, monkeypatch, capsys):
    from arbiter.cli import _default_ask_interactively

    (tmp_path / "a.md").write_text("the report\n")
    (tmp_path / "b.py").write_text("code\n")
    _, asked = _score(
        tmp_path, lambda m: (m.show_files("a.md"), m.ask_for_score("?", 1))[1], answers=[1]
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "1")
    _default_ask_interactively(asked[0])
    out = capsys.readouterr().out
    assert "--- a.md" in out and "the report" in out and "code" not in out
