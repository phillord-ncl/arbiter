# Unpacking submissions

    arbiter unpack DIR              # one submission
    arbiter unpack -r SUBMISSIONS   # a directory of submissions

Makes `DIR/project/` (what an `arb.toml` calls its `root`) from the files the
student uploaded, and leaves the originals beside it.

- An archive (zip, tar, tar.gz, tgz) is unpacked. Directories that hold
  nothing but one directory are removed, so a zip holding `Name/`, `a/b/`, or
  the files loose at the top all give the same `project/`. `__MACOSX` and
  `.DS_Store` are dropped. Spaces in the student's directory names do not
  matter, as `project` replaces the outermost name.
- Plain files with no archive are copied into `project/`.
- If `project/` exists it is left alone, so it is safe to rerun. `--force`
  replaces it, discarding changes made there.
- More than one archive, an archive with loose files, nothing at all, or an
  unreadable archive is reported for that submission and the rest carry on;
  the exit status is then non-zero.

## Straight from Canvas

    arbiter unpack --canvas OUT submissions.zip

Canvas's bulk download is a `submissions.zip` of files named
`NAME_[LATE_]USERID_SUBMISSIONID_FILE`. With `--canvas OUT` (the argument may
also be the already-unpacked directory) arbiter makes `OUT/NAME_USERID/` for
each student holding their files, a small `canvas.toml` (user id, submission
ids, late or not, original file names), and then the `project/` as above. The
download itself is not touched, and no API key is needed. A file not named
this way stops it, rather than being guessed at.

Then mark with `arbiter -r OUT`.

`--into NAME` makes a different directory name.
