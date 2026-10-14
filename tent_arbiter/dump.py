"""Dump an Exercise's results to files -- see ../plans/results_dump.md.

TOML is always written; other formats are optional extras registered in
``FORMATS`` (name -> (file suffix, render function)). Checkpointing matters
more than anything here: ``Dumper.write`` is cheap and atomic (write a
temporary file, then rename) so it can be called after every human answer,
and a crash mid-marking leaves the last complete file rather than a torn
one.
"""

import json
import os
import tempfile

FILENAME = ".arb-results"


def report(exercise, submission, rubric, complete):
    """A plain-data snapshot of ``exercise``'s results so far."""
    results = [
        {
            "criterion": marker.criterion or "",
            "score": r.score,
            "out_of": r.out_of,
            "feedback": r.feedback,
            "decided_by": r.decided_by,
        }
        for marker in exercise.markers
        for r in marker.results
    ]
    return {
        "submission": os.path.abspath(submission),
        "rubric": os.path.abspath(rubric) if rubric else "",
        "complete": complete,
        "score": sum(r["score"] for r in results),
        "out_of": sum(r["out_of"] for r in results),
        "results": results,
    }


def _value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    return repr(v)


def render_toml(data):
    lines = [
        "{} = {}".format(k, _value(v)) for k, v in data.items() if k != "results"
    ]
    for r in data["results"]:
        lines.append("")
        lines.append("[[result]]")
        lines.extend("{} = {}".format(k, _value(v)) for k, v in r.items())
    return "\n".join(lines) + "\n"


def render_text(data):
    lines = []
    for r in data["results"]:
        lines.append("{}: {}/{}".format(r["criterion"], r["score"], r["out_of"]))
        lines.append("  {}".format(r["feedback"]))
    lines.append("")
    lines.append("Total: {}/{}".format(data["score"], data["out_of"]))
    if not data["complete"]:
        lines.append("(marking not finished)")
    return "\n".join(lines) + "\n"


FORMATS = {"toml": (".toml", render_toml), "text": (".txt", render_text)}


def _atomic_write(path, text):
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".arb-tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


class Dumper:
    """Writes ``<base>.toml`` plus any extra ``formats`` on every call."""

    def __init__(self, base, submission, rubric, formats=()):
        unknown = [f for f in formats if f not in FORMATS]
        if unknown:
            raise ValueError("unknown dump format(s): {}".format(", ".join(unknown)))
        self.base = base
        self.submission = submission
        self.rubric = rubric
        self.formats = ["toml", *[f for f in formats if f != "toml"]]

    def write(self, exercise, complete=False):
        data = report(exercise, self.submission, self.rubric, complete)
        for name in self.formats:
            suffix, render = FORMATS[name]
            _atomic_write(self.base + suffix, render(data))

    def paths(self):
        return [self.base + FORMATS[n][0] for n in self.formats]
