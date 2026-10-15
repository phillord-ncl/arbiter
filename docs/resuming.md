# Resuming and restarting

`arbiter` writes `arb-results.toml` in the submission as you mark, after the
automatic checks and after every answer you give. Run it again on the same
submission and it picks up where you were:

- every automatic check is run again from scratch, since they are cheap and
  the files may have changed;
- each question you already answered comes back with your score and feedback
  pre-filled, so Enter, Enter keeps them and any of them can be changed;
- answers in the file that have not been asked again yet stay in it, listed
  as `[[stored]]` and not counted in the score, so a crash part-way through
  loses nothing.

A stored answer is matched to its question by an id (`criterion:step`). If
you have edited the `arb.toml` so the id no longer matches, or the stored
score is no longer allowed, it is ignored.

`--fresh` ignores the file and starts with empty boxes.

## Restarting after editing the submission

If something not the student's fault stops the program running, fix it in a
terminal (Ctrl-T), then press Ctrl-R (or type `restart` at the plain prompt).
Marking begins again as above: automatic checks re-run on the edited files and
your answers so far are offered back, pre-filled. The number of restarts is
recorded in the results file.

## Marking a series

Name several submissions, or use `-r` to name directories whose
subdirectories are the submissions:

    arbiter -r submissions
    arbiter submissions/c01 submissions/c02     # or submissions/*

When more than one submission is named (or with `-r`), any whose results file
says `complete = true` is skipped, so rerunning carries on with the ones not
finished. `--fresh` marks everyone again. A single submission named outright
is always marked, complete or not. `--output` needs exactly one submission.

In the TUI a small panel under "Marked so far" shows how many are done and
to go, and the last two log lines (marked, or skipped as complete).

Between students a "Next student" dialog reminds you to close the last
student's terminals and viewer files. Enter carries on; Ctrl-Q stops (those
already marked stay complete). Plain mode asks `Next student?` when run in a
terminal.
