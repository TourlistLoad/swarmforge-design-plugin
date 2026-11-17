"""Split a shell command line into simple commands a policy can judge.

The split is deliberately conservative: control operators (`&&`, `||`, `;`,
`|`, `&`, parentheses, newlines) separate commands, redirections are recorded
as written paths, and the usual wrappers (`env`, `timeout`, `nice`, `xargs`,
`bash -c`, the pack's `lane`, `find -exec`) are unwrapped so the command they
run is judged too.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass

CONTROL_CHARS = frozenset(";&|()")
REDIRECT_CHARS = frozenset("<>&|")
FD_DUPLICATIONS = frozenset({">&", "<&"})
READ_REDIRECTS = frozenset({"<", "<<", "<<<"})
DISCARD_TARGETS = frozenset({"/dev/null", "/dev/stdout", "/dev/stderr"})
SHELLS = frozenset({"bash", "sh", "zsh", "dash"})
EXEC_FLAGS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
EXEC_END = frozenset({";", "+"})
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
PYTHON = re.compile(r"python(\d+(\.\d+)?)?$")
PYTHON_OPTIONS_WITH_ARG = frozenset({"-W", "-X"})
RUNNERS = frozenset({"npx", "pnpx", "bunx"})
SINGLE_TARGET = frozenset({"cp", "mv", "install", "ln"})
EVERY_TARGET = frozenset({"rm", "rmdir", "touch", "truncate", "unlink", "shred", "tee"})
SED_SCRIPT_FLAGS = frozenset({"-e", "--expression", "-f", "--file"})

# wrapper -> options that consume the following word
WRAPPERS = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "stdbuf": frozenset({"-i", "-o", "-e"}),
    "sudo": frozenset({"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U"}),
    "xargs": frozenset({"-n", "-I", "-L", "-P", "-d", "-s", "-a", "-E", "-e", "-l"}),
    "time": frozenset({"-f", "-o"}),
    "nohup": frozenset(),
    "command": frozenset(),
    "builtin": frozenset(),
    "exec": frozenset(),
    "noglob": frozenset(),
}


class Unparseable(Exception):
    """The command line cannot be split safely, for example an unclosed quote."""


@dataclass(frozen=True)
class SimpleCommand:
    """One command of a command line: its words and the files it redirects into."""

    words: tuple
    writes: tuple = ()

    @property
    def program(self) -> str:
        return _resolve(self.words)[0]

    @property
    def args(self) -> tuple:
        return _resolve(self.words)[1]

    def written_paths(self) -> tuple:
        """Every path this command writes: redirections plus file-writing programs."""
        name = os.path.basename(self.words[0]) if self.words else ""
        operands = tuple(word for word in self.words[1:] if not word.startswith("-"))
        if name in EVERY_TARGET:
            return self.writes + operands
        if name in SINGLE_TARGET:
            return self.writes + operands[-1:]
        if name == "sed" and _edits_in_place(self.words[1:]):
            return self.writes + _sed_files(self.words[1:])
        if name == "ruff" and _ruff_rewrites(self.words[1:]):
            return self.writes + (operands[1:] or (".",))
        return self.writes


def parse(command: str) -> tuple:
    """Every simple command in a command line, with wrappers unwrapped."""
    commands = []
    for words, writes in _segments(_tokens(command)):
        commands.extend(_unwrap(words, writes))
    return tuple(commands)


def _tokens(command: str) -> list:
    lexer = shlex.shlex(command.replace("\r", " ").replace("\n", " ; "), posix=True, punctuation_chars=";&|()<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError as error:
        raise Unparseable(str(error)) from error


def _segments(tokens: list) -> list:
    """Group tokens into (words, written paths) per simple command."""
    segments, words, writes = [], [], []
    position = 0
    while position < len(tokens):
        token = tokens[position]
        if _is_redirect(token):
            position = _take_redirect(tokens, position, words, writes)
        elif _is_control(token):
            segments.append((words, writes))
            words, writes = [], []
        else:
            words.append(token)
        position += 1
    segments.append((words, writes))
    return [(w, tuple(t)) for w, t in segments if w or t]


def _is_redirect(token: str) -> bool:
    return bool(token) and set(token) <= REDIRECT_CHARS and bool(set(token) & set("<>"))


def _is_control(token: str) -> bool:
    return bool(token) and set(token) <= CONTROL_CHARS


def _take_redirect(tokens: list, position: int, words: list, writes: list) -> int:
    """Record a redirection's target and return the index of that target."""
    if words and len(words[-1]) == 1 and words[-1].isdigit():
        words.pop()  # the file descriptor in `2>`
    operator = tokens[position]
    target = tokens[position + 1] if position + 1 < len(tokens) else ""
    if _writes_file(operator, target):
        writes.append(target)
    return position + 1


def _writes_file(operator: str, target: str) -> bool:
    if operator in READ_REDIRECTS or target in DISCARD_TARGETS or not target:
        return False
    if operator in FD_DUPLICATIONS:
        return not (target.isdigit() or target == "-")
    return ">" in operator


def _unwrap(words: list, writes: tuple) -> list:
    words = _strip_wrappers(words)
    if not words:
        return [SimpleCommand((), writes)] if writes else []
    name = os.path.basename(words[0])
    if name in SHELLS and "-c" in words:
        return _shell_body(words, writes)
    if name == "lane" and len(words) > 2:
        return _unwrap(words[2:], writes)
    inner = _exec_command(words) if name == "find" else []
    return [SimpleCommand(tuple(words), writes)] + _unwrap(inner, ())


def _shell_body(words: list, writes: tuple) -> list:
    """`bash -c '<body>'`: judge the body's commands, and keep the outer redirections."""
    body = words[words.index("-c") + 1 : words.index("-c") + 2]
    outer = [SimpleCommand(tuple(words), writes)] if writes else []
    return list(parse(body[0] if body else "")) + outer


def _strip_wrappers(words: list) -> list:
    words = list(words)
    while words:
        if ASSIGNMENT.match(words[0]):
            words.pop(0)
            continue
        name = os.path.basename(words[0])
        if name not in WRAPPERS:
            break
        words.pop(0)
        _drop_options(words, WRAPPERS[name])
        if name == "timeout" and words:
            words.pop(0)  # the duration
    return words


def _drop_options(words: list, with_argument: frozenset) -> None:
    while words and words[0].startswith("-"):
        option = words.pop(0)
        if option == "--":
            return
        if option in with_argument and words:
            words.pop(0)


def _exec_command(words: list) -> list:
    """The command a `find -exec … ;` runs, if any."""
    flags = [index for index, word in enumerate(words) if word in EXEC_FLAGS]
    if not flags:
        return []
    inner = words[flags[0] + 1 :]
    ends = [index for index, word in enumerate(inner) if word in EXEC_END]
    return inner[: ends[0]] if ends else inner


def _resolve(words: tuple) -> tuple:
    """(program, arguments): python scripts and `-m` modules count as the program."""
    if not words:
        return "", ()
    name = os.path.basename(words[0])
    if PYTHON.match(name):
        return _python_target(tuple(words[1:]))
    if name in RUNNERS and len(words) > 1:
        return os.path.basename(words[1]), tuple(words[2:])
    return name, tuple(words[1:])


def _python_target(args: tuple) -> tuple:
    index = _skip_python_options(args)
    if index >= len(args):
        return "python", ()
    if args[index] == "-m":
        module = args[index + 1] if index + 1 < len(args) else "python"
        return module.split(".")[0], args[index + 2 :]
    if args[index] == "-c":
        return "python -c", args[index + 1 :]
    return os.path.basename(args[index].rstrip("/")), args[index + 1 :]


def _skip_python_options(args: tuple) -> int:
    index = 0
    while index < len(args) and args[index].startswith("-"):
        if args[index] in ("-m", "-c"):
            break
        index += 2 if args[index] in PYTHON_OPTIONS_WITH_ARG else 1
    return index


def _edits_in_place(args: list) -> bool:
    return any(arg == "-i" or arg.startswith(("-i", "--in-place")) for arg in args)


def _sed_files(args: list) -> tuple:
    """The files `sed -i` rewrites: operands, minus the script and its flags' values."""
    operands, skip_next, script_given = [], False, False
    for arg in args:
        if skip_next:
            skip_next = False
        elif arg in SED_SCRIPT_FLAGS:
            skip_next, script_given = True, True
        elif not arg.startswith("-"):
            operands.append(arg)
    return tuple(operands if script_given else operands[1:])


def _ruff_rewrites(args: list) -> bool:
    """`ruff format …` (not `--check`/`--diff`) and `ruff check --fix …` rewrite the files they are given."""
    args = list(args)
    if args[:1] == ["format"]:
        return "--check" not in args and "--diff" not in args
    return args[:1] == ["check"] and any(arg.startswith(("--fix", "--unsafe-fixes")) for arg in args)
