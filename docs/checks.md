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
| `file_exists` | a file matches any of `files` |
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

The project root is found for you: if an upload is wrapped in extra
directories, `arbiter` goes down through them to the first that looks like a project (a `.git`, `requirements.txt`, `pyproject.toml`, `setup.py` or a `.py` file).
Git is never looked for above that, so a submission with no `.git` does not
borrow a parent's history.

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
