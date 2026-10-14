import re

from tent_arbiter.core import RunMarker
from tent_arbiter.matchers import Always, Exact, RegexpAny, SubString


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
    from tent_arbiter.core import Exercise

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
