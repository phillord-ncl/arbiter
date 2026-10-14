import re

from arbiter.core import Result, RunMarker
from arbiter.matchers import Always, Exact, RegexpAny, SubString


def test_exact_requires_the_whole_text():
    assert Exact("Hello\n", "fb", 1).matches("Hello\n")
    assert not Exact("Hello", "fb", 1).matches("Hello\n")


def test_substring_matches_anywhere():
    assert SubString("ell", "fb", 1).matches("Hello")
    assert not SubString("xyz", "fb", 1).matches("Hello")


def test_regexp_any_searches_rather_than_anchors():
    assert RegexpAny(r"[Hh]ello", "fb", 1).matches("say hello there")
    assert RegexpAny(re.compile("^H"), "fb", 1).matches("Hello")
    assert not RegexpAny(r"^ello", "fb", 1).matches("Hello")


def test_bytes_patterns_match_text():
    assert Exact(b"Hi", "fb", 1).matches("Hi")
    assert SubString(b"i", "fb", 1).matches("Hi")


def test_always_matches_anything():
    assert Always("fb", 0).matches("")


def _run(tmp_path, stdout, *matchers):
    script = tmp_path / "s.py"
    script.write_text(f"print({stdout!r})\n")
    marker = RunMarker(str(tmp_path))
    marker.python(script.name).match_stdout(10, *matchers)
    from arbiter.core import Exercise

    Exercise(marker).run(ask_interactively=None)
    return marker.results[0]


MATCHERS = (
    Exact("Hello World\n", "exact", 10),
    Exact("hello world\n", "wrong case", 8),
    SubString("Hello", "part right", 5),
    Always("nothing right", 1),
)


def test_first_matching_matcher_wins(tmp_path):
    result = _run(tmp_path, "Hello World", *MATCHERS)
    assert (result.score, result.feedback, result.out_of) == (10, "exact", 10)


def test_later_matcher_gives_partial_credit(tmp_path):
    assert _run(tmp_path, "hello world", *MATCHERS).score == 8
    assert _run(tmp_path, "Hello there", *MATCHERS).score == 5


def test_fall_through_matcher(tmp_path):
    result = _run(tmp_path, "nope", *MATCHERS)
    assert (result.score, result.feedback) == (1, "nothing right")


def test_no_matcher_scores_zero(tmp_path):
    result = _run(tmp_path, "nope", Exact("x", "fb", 10))
    assert result.score == 0


def _run_with_fallback(tmp_path, stdout, answer):
    script = tmp_path / "s.py"
    script.write_text(f"print({stdout!r})\n")
    marker = RunMarker(str(tmp_path))
    marker.python(script.name).match_stdout(
        10,
        Exact("Hello World\n", "exact", 10),
        Exact("Goodbye World\n", "wrong", 0),
    ).or_else().ask_for_score("score?", 10)
    asked = []

    def ask(question):
        asked.append(question)
        return Result(out_of=question.out_of, score=answer, feedback="human")

    from arbiter.core import Exercise

    Exercise(marker).run(ask_interactively=ask)
    return marker, asked


def test_or_else_is_skipped_when_a_matcher_decides(tmp_path):
    marker, asked = _run_with_fallback(tmp_path, "Hello World", 7)
    assert asked == []
    assert [(r.score, r.feedback) for r in marker.results] == [(10, "exact")]


def test_explicit_zero_matcher_also_decides(tmp_path):
    marker, asked = _run_with_fallback(tmp_path, "Goodbye World", 7)
    assert asked == []
    assert [(r.score, r.feedback) for r in marker.results] == [(0, "wrong")]


def test_or_else_asks_when_nothing_matches(tmp_path):
    marker, asked = _run_with_fallback(tmp_path, "what", 7)
    assert len(asked) == 1
    assert [(r.score, r.feedback) for r in marker.results] == [(7, "human")]


def test_or_else_pair_counts_once_in_max_score(tmp_path):
    marker = RunMarker(str(tmp_path))
    marker.python("s.py").match_stdout(10, Always("x", 0)).or_else().ask_for_score(
        "q", 10
    )
    assert marker.max_score() == 10


def test_or_else_without_a_step_is_an_error(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        RunMarker(str(tmp_path)).or_else()


def test_or_else_question_can_quote_the_output(tmp_path):
    script = tmp_path / "s.py"
    script.write_text("print('surprise')\n")
    marker = RunMarker(str(tmp_path))
    marker.python(script.name).match_stdout(
        10, Exact("Hello World\n", "exact", 10)
    ).or_else().ask_for_score(
        lambda ctx: "printed: " + ctx.completed_process.stdout, 10
    )
    asked = []

    def ask(question):
        asked.append(question.question)
        return Result(out_of=question.out_of, score=0, feedback="human")

    from arbiter.core import Exercise

    Exercise(marker).run(ask_interactively=ask)
    assert asked == ["printed: surprise\n"]
