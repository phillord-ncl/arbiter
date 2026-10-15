# Mechanical checks

Some marking lines need no judgement: is there a README, does
`requirements.txt` name a package, how many commits are there. `arbiter` has
steps for these. Each scores full marks if it passes. If it does not pass it
is *undecided*: it scores nothing, with the reason as its feedback, unless
the next step has `or_else = true`, in which case a human question follows,
shown what the check found under "Automatic checks". So a check can be final
or can be a first pass that a person may overturn.

| `type` | passes when |
|--------|-------------|
| `file_exists` | a file matches any of `files`, or with `require = "all"`, each of them |
| `file_contains` | a file matching `files` has text matching `pattern` (ignoring case) |
| `files_match` | any line of any file matching `files` matches `pattern` |
| `word_count` | the words in the files matching `files` are from `low` to `high`, widened by `under` below `low` and `over` above `high` (0.1 is 10%) |
| `git_commit_count` | the history has at least `at_least` commits |
| `git_log_matches` | a commit message (`messages`) or changed line (`diffs`) matches `pattern`, ignoring case |
| `note_unexpected_hidden` | (scores nothing) notes hidden files and directories such as `.venv`, other than `allowed` (default `.git`, `.gitignore`) |

Files are matched by case-insensitive glob. A pattern with no `/` matches a
file's name wherever it is; one with a `/` (`doc/*.md`) matches the path from
the project root. Hidden directories, virtualenvs, bytecode caches and
`marker-*` files are never searched.

Where the project is comes from the `arb.toml`, not a guess: `root =
"project"` at the top says it is the `project` directory inside each
submission (default: the submission itself). For an odd upload, say a
student's zip with extra directories inside, `--root some/dir` on the command
line overrides it for that run. Git is only looked for in the project
directory itself, never above it, so a submission with no `.git` does not
borrow a parent's history. The `marker-*` scripts are written there too.

```toml
[[marker.step]]
type = "file_exists"
files = ["LICENCE.md", "LICENSE.md"]
out_of = 1

[[marker.step]]
type = "word_count"
files = ["doc/*.md"]
low = 300
high = 500
over = 0.1
out_of = 1

[[marker.step]]
or_else = true
type = "ask_for_score"
question = "Is the report in another place or length?"
out_of = 1
```

## Feedback for human-marked questions

An `ask_for_score` step may set two optional keys (or the same arguments to
`ask_for_score()` in an `arb.py`):

```toml
[[marker.step]]
type = "ask_for_score"
question = "Does it work?"
out_of = 3
full_feedback = "Correct"       # offered for full marks
require_feedback = true         # needed for any other score
```

With `full_feedback`, moving from the score box to the feedback box (Enter
or Tab) after entering full marks fills the empty feedback box with that
text, which the marker may edit or clear. With `require_feedback`, the
marker cannot record a score below full marks without writing feedback.
The plain prompt asks for feedback only when either key is set. Questions
marked automatically keep the feedback of the check or match that decided
them.

## Showing the marker things

Some lines need a person to read something. These steps score nothing and
choose what a later question shows:

| `type` | shows |
|--------|-------|
| `show_git_log` | `git log` (default `--stat --date=short`; `args` replaces them), under `title` |
| `show_files` | each file matching `files`, one tab each, which a viewer can open; the plain prompt prints them in full |
| `show_command` | the output of `command` (a list of words, run in the project root) under `title` |

Without any of these a question lists every file in the submission (as tabs,
for a viewer); with one, it shows only what was chosen, after any
"Automatic checks".
