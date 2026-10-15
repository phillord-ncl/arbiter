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

`--into NAME` makes a different directory name.
