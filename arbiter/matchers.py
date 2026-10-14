"""Matchers for ``RunMarker.match_stdout`` -- see ../notes.org.

Each matcher is one case: if it matches the text it yields its own
feedback and score. ``match_stdout`` tries its matchers in order and uses
the first that matches, so a nearly-right answer can be listed after the
exact one and earn partial credit.
"""

import re

from arbiter.core import Result


def _as_text(match):
    return match.decode("utf-8") if isinstance(match, bytes) else match


class Matcher:
    def __init__(self, feedback, score):
        self.feedback = feedback
        self.score = score

    def matches(self, text):
        raise NotImplementedError

    def result(self, out_of):
        return Result(out_of=out_of, score=self.score, feedback=self.feedback)


class Exact(Matcher):
    """The whole text equals ``match`` (str or bytes)."""

    def __init__(self, match, feedback, score):
        super().__init__(feedback, score)
        self.match = _as_text(match)

    def matches(self, text):
        return text == self.match


class SubString(Matcher):
    """``match`` (str or bytes) appears somewhere in the text."""

    def __init__(self, match, feedback, score):
        super().__init__(feedback, score)
        self.match = _as_text(match)

    def matches(self, text):
        return self.match in text


class RegexpAny(Matcher):
    """The regular expression (str or compiled) matches anywhere in the text."""

    def __init__(self, pattern, feedback, score):
        super().__init__(feedback, score)
        self.pattern = re.compile(pattern)

    def matches(self, text):
        return self.pattern.search(text) is not None


class Always(Matcher):
    """Matches anything; put last as a fall-through with its own feedback."""

    def matches(self, text):
        return True
