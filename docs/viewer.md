# Viewing a submission's files

When `arbiter` asks you a question in the terminal UI, the question
comes with context: the program's output and the files in the submission.
Out of the box the UI shows these itself, in tabs. If you would rather read
the code in your own editor, tell `arbiter` how to open it.

## Choosing a viewer from the UI

Press Ctrl-P (the menu) and choose **Configure viewer**. Pick Emacsclient,
Emacs, Visual Studio Code or PyCharm, or none. The choice takes effect at once and is
written to `config.toml` (below), replacing any `[viewer]` section there and
leaving the rest of the file alone. The command is the usual one for your
platform: `emacsclient` (`emacsclientw.exe` on Windows), plain `emacs`
(`open -a Emacs` on macOS, `runemacs.exe` on Windows), `code` (`code.cmd`
on Windows), and `pycharm` (`pycharm.cmd` on Windows, `open -a PyCharm` on
macOS). The program must be on your `PATH`; if yours is not, or you need
different options, edit the file by hand as below. Emacsclient needs a
running server, and on Linux and macOS gets the close commands too. Plain
Emacs starts Emacs for the files and cannot close them again, so it has no
close commands. It uses `detach = true` so arbiter does not wait for Emacs to
exit; set that in a hand-written `[viewer]` for any program that stays running.

## Configuration

Create `config.toml` in the per-user config directory:

| Platform | Location |
|----------|----------|
| Linux    | `~/.config/arbiter/config.toml` |
| macOS    | `~/Library/Application Support/arbiter/config.toml` |
| Windows  | `%APPDATA%\arbiter\config.toml` |

It has one section:

```toml
[viewer]
open = "COMMAND {file}"
close = "COMMAND {file}"     # optional
close_dir = "COMMAND {dir}"  # optional
```

- `open` is run when you press Ctrl-O on a file's tab.
- `close` is run when you press Ctrl-X. It is optional; without it Ctrl-X
  does nothing. When a student is finished, `close` is also run for every
  file you opened and have not closed.
- `close_dir` is run when a student is finished, with `{dir}` the full path of
  their submission directory. It should close every file under it, including
  ones you opened yourself, which `close` cannot know about. Without it, the
  files opened with Ctrl-O are closed one by one with `close`.
- `{file}` is replaced by the file's full path.

Each command is split into words first and `{file}` is substituted
afterwards, and nothing is run through a shell. So a path with spaces in it
arrives as a single argument, but shell features (pipes, `~`, environment
variables) do not work. Use full paths for programs not on your `PATH`.

If you configure nothing, on Windows `arbiter` uses Visual Studio Code when
`code.cmd` is on your `PATH`, as in the example below. Elsewhere, or without
VS Code, Ctrl-O and Ctrl-X just tell you no viewer is configured. The files
are still shown in the UI.

A close command that fails is ignored, so a refused close looks like Ctrl-X
doing nothing.

## Example: Emacs

```toml
[viewer]
open = "emacsclient --no-wait {file}"
close = "emacsclient --eval '(let ((b (find-buffer-visiting \"{file}\"))) (when b (kill-buffer b)))'"
close_dir = "emacsclient --eval '(dolist (b (buffer-list)) (let ((f (buffer-file-name b))) (when (and f (string-prefix-p \"{dir}/\" f) (not (buffer-modified-p b))) (kill-buffer b))))'"
```

This needs a running Emacs server (`M-x server-start`, or `(server-start)`
in your init file). `--no-wait` returns at once rather than waiting until
you finish editing.

`close_dir` kills every buffer visiting a file under the student's directory,
except ones with unsaved changes, which stay open.

The close command kills the buffer visiting the file. If you have modified
the buffer without saving, Emacs asks you whether to discard it, and
`arbiter` waits for your answer. If you decline, the command fails and
the buffer stays open.

## Example: Visual Studio Code

```toml
[viewer]
open = "code --reuse-window {file}"      # code.cmd on Windows
```

On Windows the command is `code.cmd`, as no shell is involved to find it
as `code`. `--reuse-window` opens the file in the window you already have rather than
starting a new one. VS Code has no command line way to close a file, so
there is no `close` line.

## Turning the UI off

`arbiter --no-tui SUBMISSION` uses plain terminal prompts instead. The
text context is printed before each question; the viewer is not used. The
UI is the default when the `tui` extra is installed
(`pip install 'arbiter[tui]'`) and you are in a terminal.
