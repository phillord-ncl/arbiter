"""Turn what a student uploaded into a ``project`` directory to mark.

A submission directory holds the files as downloaded: usually one archive,
but an exercise may ask for a single file or several. Archives are not under
our control: a student's zip may hold one directory (what they are told to
do), the files loose at the top (a "tarbomb"), or a pointless stack of
nested directories, and the names may contain spaces. ``unpack`` always
leaves the same shape, ``DIR/project/``, and keeps the originals beside it.
"""

import os
import re
import shutil
import tarfile
import zipfile

#: What an upload may hold that is never part of the student's work.
JUNK = {"__MACOSX", ".DS_Store", "Thumbs.db"}

#: Files in a submission directory that are ours, not the student's.
OWN_FILES = ("arb-results", "tent-peg.toml", "canvas.toml")

ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")


class UnpackError(Exception):
    pass


def is_archive(name):
    return name.lower().endswith(ARCHIVE_SUFFIXES)


def _is_ours(name):
    return name.startswith(OWN_FILES) or name.startswith(".")


def find_inputs(submission):
    """The archives and the loose files in ``submission``, as two lists of
    names (our own files and the unpacked project left out)."""
    archives, loose = [], []
    for name in sorted(os.listdir(submission)):
        if name in JUNK or _is_ours(name):
            continue
        if not os.path.isfile(os.path.join(submission, name)):
            continue
        (archives if is_archive(name) else loose).append(name)
    return archives, loose


def _extract(archive, into):
    try:
        if archive.lower().endswith(".zip"):
            ## extractall refuses to write outside ``into`` for ../ names
            with zipfile.ZipFile(archive) as z:
                z.extractall(into)
        else:
            with tarfile.open(archive) as t:
                t.extractall(into, filter="data")
    except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError) as e:
        raise UnpackError("cannot read {}: {}".format(os.path.basename(archive), e))


def _remove_junk(root):
    for here, dirs, files in os.walk(root, topdown=True):
        for name in list(dirs):
            if name in JUNK:
                shutil.rmtree(os.path.join(here, name))
                dirs.remove(name)
        for name in files:
            if name in JUNK:
                os.remove(os.path.join(here, name))


def project_root(directory):
    """The directory holding the student's work: ``directory``, descended
    through any level whose only content is one directory. Returns the path
    and the number of levels descended."""
    levels = 0
    while True:
        entries = os.listdir(directory)
        if len(entries) == 1 and os.path.isdir(os.path.join(directory, entries[0])):
            ## A lone .git directory is the project itself, not a wrapper
            if entries[0] == ".git":
                return directory, levels
            directory = os.path.join(directory, entries[0])
            levels += 1
        else:
            return directory, levels


def unpack(submission, into="project", force=False):
    """Make ``submission/into`` from the submission's uploaded files.

    Returns a one-line description of what was done. Nothing is done, and
    the same is said, if the directory already exists (unless ``force``,
    which replaces it). Raises UnpackError if there is nothing sensible to
    do."""
    target = os.path.join(submission, into)
    if os.path.exists(target):
        if not force:
            return "{} exists, left alone".format(into)
        shutil.rmtree(target)

    archives, loose = find_inputs(submission)
    if len(archives) > 1:
        raise UnpackError(
            "more than one archive ({}); unpack by hand".format(", ".join(archives))
        )
    if archives and loose:
        raise UnpackError(
            "an archive ({}) and loose files ({}); unpack by hand".format(
                archives[0], ", ".join(loose)
            )
        )
    if not archives and not loose:
        raise UnpackError("no files submitted")

    work = os.path.join(submission, ".unpack-tmp")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    try:
        if archives:
            _extract(os.path.join(submission, archives[0]), work)
            _remove_junk(work)
            if not os.listdir(work):
                raise UnpackError("{} is empty".format(archives[0]))
            root, levels = project_root(work)
            shutil.move(root, target)
            if levels:
                note = "{} level{} of directory removed".format(
                    levels, "" if levels == 1 else "s"
                )
            else:
                note = "unpacked"
            how = "{}: {}".format(archives[0], note)
        else:
            os.makedirs(target)
            for name in loose:
                shutil.copy2(os.path.join(submission, name), target)
            how = "copied {}".format(", ".join(loose))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return how


#: Canvas's bulk download names a file NAME_[LATE_]USERID_SUBMISSIONID_ORIGINAL
CANVAS_NAME = re.compile(
    r"^(?P<name>[^_]+)_(?P<late>LATE_)?(?P<user>\d+)_(?P<submission>\d+)_(?P<original>.+)$"
)


def gather_canvas(download, out):
    """``download`` is the directory, or the submissions.zip Canvas hands
    over, of a bulk download. The files in it are copied into one directory per
    student under ``out``, named NAME_USERID, with a ``canvas.toml`` noting
    the ids, which files and whether any was late. Returns the directories
    made. The download is left untouched; a file not named the Canvas way
    raises UnpackError rather than being guessed at."""
    if os.path.isfile(download):
        scratch = os.path.join(out, ".canvas-tmp")
        shutil.rmtree(scratch, ignore_errors=True)
        os.makedirs(scratch)
        try:
            _extract(download, scratch)
            return gather_canvas(scratch, out)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    students = {}
    for name in sorted(os.listdir(download)):
        path = os.path.join(download, name)
        if not os.path.isfile(path) or name.startswith("."):
            continue
        m = CANVAS_NAME.match(name)
        if m is None:
            raise UnpackError("{} is not named like a Canvas download".format(name))
        students.setdefault((m["name"], m["user"]), []).append((m, path))
    if not students:
        raise UnpackError("no files in {}".format(download))

    made = []
    for (name, user), files in sorted(students.items()):
        directory = os.path.join(out, "{}_{}".format(name, user))
        os.makedirs(directory, exist_ok=True)
        for m, path in files:
            shutil.copy2(path, os.path.join(directory, m["original"]))
        with open(os.path.join(directory, "canvas.toml"), "w") as f:
            f.write("user_id = {}\n".format(user))
            f.write("submission_ids = [{}]\n".format(
                ", ".join(sorted({m["submission"] for m, _ in files}))))
            f.write("late = {}\n".format(
                "true" if any(m["late"] for m, _ in files) else "false"))
            f.write("files = [{}]\n".format(
                ", ".join('"{}"'.format(m["original"].replace('"', "'"))
                          for m, _ in files)))
        made.append(directory)
    return made
