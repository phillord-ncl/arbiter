# Viewing a submission's files

When `arbiter` asks you a question in the terminal UI, the question
comes with context: the program's output and the files in the submission.
Out of the box the UI shows these itself, in tabs. If you would rather read
the code in your own editor, tell `arbiter` how to open it.

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
```

- `open` is run when you press Ctrl-O on a file's tab.
- `close` is run when you press Ctrl-X. It is optional; without it Ctrl-X
  does nothing.
- `{file}` is replaced by the file's full path.

Each command is split into words first and `{file}` is substituted
afterwards, and nothing is run through a shell. So a path with spaces in it
arrives as a single argument, but shell features (pipes, `~`, environment
variables) do not work. Use full paths for programs not on your `PATH`.

If you configure nothing, Ctrl-O and Ctrl-X just tell you no viewer is
configured. The files are still shown in the UI.

A close command that fails is ignored, so a refused close looks like Ctrl-X
doing nothing.

## Example: Emacs

```toml
[viewer]
open = "emacsclient --no-wait {file}"
close = "emacsclient --eval '(let ((b (find-buffer-visiting \"{file}\"))) (when b (kill-buffer b)))'"
```

This needs a running Emacs server (`M-x server-start`, or `(server-start)`
in your init file). `--no-wait` returns at once rather than waiting until
you finish editing.

The close command kills the buffer visiting the file. If you have modified
the buffer without saving, Emacs asks you whether to discard it, and
`arbiter` waits for your answer. If you decline, the command fails and
the buffer stays open.

## Example: Visual Studio Code

```toml
[viewer]
open = "code --reuse-window {file}"
```

`--reuse-window` opens the file in the window you already have rather than
starting a new one. VS Code has no command line way to close a file, so
there is no `close` line.

## Turning the UI off

`arbiter --no-tui SUBMISSION` uses plain terminal prompts instead. The
text context is printed before each question; the viewer is not used. The
UI is the default when the `tui` extra is installed
(`pip install 'arbiter[tui]'`) and you are in a terminal.
