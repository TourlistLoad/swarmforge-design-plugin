"""Recognise a shell line the guard may let run unasked: it only reads inside the workspace, or it runs one
of the commands the pack's `tools/README.md` names, on paths inside the workspace.

Claude Code approves a plain `ls` or `cat` on its own, but asks for a compound line such as
`P=<ws>/docs; ls $P && head -5 $P/README.md`, or for the protocol's own commands chained together
(`rm -f "$A/stem.*"; gherkin-parser … && bb --config … gherkin-ir-dry-checker …`). Each one stopped the run.

A line passes only when every part is a read-only program or a pack command, nothing is redirected into a
file, and every path stays inside the roots. A `cd` must land in a directory that exists there. Anything
unclear (a heredoc, a command substitution, `~`, an unknown variable, a `.env` file) is left to Claude
Code's own permission check.

Pack commands (tools/README.md): a program under `<pack>/tools/`, `python3 <pack>/tools/…`, `python3 -m
pytest|coverage|ruff|crapper|dryer`, `ruff check` and `ruff format --check`, `bb --config <pack>/tools/…`,
the configured `acceptance_command`, read-only `git`, and `rm -f` of scratch under the artifacts root (the
protocol deletes a stale artifact before it regenerates it).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import packtools, shell
from .pack import Pack, is_under

READ_ONLY = frozenset(
    {
        "ls",
        "cat",
        "head",
        "tail",
        "wc",
        "grep",
        "egrep",
        "fgrep",
        "rg",
        "sort",
        "uniq",
        "cut",
        "tr",
        "diff",
        "cmp",
        "stat",
        "file",
        "tree",
        "echo",
        "printf",
        "pwd",
        "true",
        "false",
        "test",
        "[",
        "basename",
        "dirname",
        "realpath",
        "readlink",
        "nl",
        "column",
        "du",
        "md5sum",
        "sha256sum",
        "cd",
        "which",
        "seq",
        "date",
        "find",
    }
)
KEYWORDS = frozenset(
    {"for", "in", "do", "done", "while", "until", "if", "then", "else", "elif", "fi", "{", "}", "!", "]"}
)
FIND_UNSAFE = frozenset({"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"})
VARIABLE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
UNCLEAR = ("<<", "`", "$(", "<(", ">(")
CACHE_DIRS = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache", ".hypothesis"})
EXPORTED = ("PACK", "PROJECT", "PACK_PROJECT", "ARTIFACTS")  # read from the session's environment
SHELL_VARIABLES = {"PIPESTATUS": "0"}  # `${PIPESTATUS[0]}`: an exit code, never a path
PACK_MODULES = frozenset({"pytest", "ruff", "crapper", "dryer", "coverage"})
APS_TASKS = frozenset({"gherkin-parser", "gherkin-ir-dry-checker", "test"})  # never `gherkin-mutator`
READ_ONLY_GIT = frozenset({"status", "diff", "log", "show", "rev-parse", "ls-files", "blame", "grep"})
GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"})
VERSIONED = frozenset({"ruff", "pytest", "coverage", "bb", "git", "node", "java"})
SED_PRINT = re.compile(r"[0-9,$;p\s]+")


def reads_only_inside(
    command: str, cwd: Path, roots: tuple, pack: Pack | None = None, writes_ok: frozenset = frozenset()
) -> bool:
    """True when `command` only reads, or runs the pack's commands (given `pack`), and only under `roots`.

    A pack command that writes owned data (packtools.classify) passes only when its kind is in `writes_ok`.
    """
    if _unclear(command) or not _inside(cwd, roots):
        return False
    try:
        segments = shell._segments(shell._tokens(command))
    except shell.Unparseable:
        return False
    line = _Line(cwd, roots, pack, writes_ok)
    return all(line.reads(list(words), writes) for words, writes in segments)


class _Line:
    """The state of one command line: its variables and its working directory."""

    def __init__(self, cwd: Path, roots: tuple, pack: Pack | None = None, writes_ok: frozenset = frozenset()):
        self.names: dict = dict(SHELL_VARIABLES)
        if pack is not None:  # only what the session really exports (`/swarmforge-design:setup` sets PACK)
            self.names.update({name: pack.environ[name] for name in EXPORTED if pack.environ.get(name)})
        self.pack = pack
        self.writes_ok = writes_ok
        self.loops: set = set()  # loop variables bound to items outside the roots
        self.cwd = Path(os.path.normpath(cwd))
        self.roots = roots

    def reads(self, words: list, writes: tuple) -> bool:
        self._take_assignments(words)
        if writes and not self._into_scratch(writes):
            return False
        if words[:1] == ["for"] and len(words) > 2 and words[2] == "in":
            return self._bind_loop(words[1], words[3:])
        words = _without_keywords(words)
        if words[:1] in (["env"], ["time"], ["timeout"], ["nice"]) or words[:2] == ["uv", "run"]:
            return self._wrapped(words)
        if words[:1] in (["test"], ["["]):  # an existence test reads no file: any path (`[ -d /x/.codegraph ]`)
            return True
        if words[:1] in (["echo"], ["printf"]) and self._only_loop_unknowns(words[1:]):
            return True
        return not words or (self._runs_ok(words) and self._paths_ok(words[1:]) and self._follow_cd(words))

    def _into_scratch(self, targets: tuple) -> bool:
        """`… > $ARTIFACTS/x.txt`: a redirect into scratch (an artifacts root or `<PACK>/tmp`) keeps a line
        read-only; the guard has already held the target to the role's own write scope."""
        if self.pack is None:
            return False
        scratch = (*self.pack.every("artifacts"), self.pack.scratch)
        return all(
            _expand(target, self.names) is not None and _inside(self._resolve(target), scratch) for target in targets
        )

    def _bind_loop(self, name: str, items: list) -> bool:
        """`for d in a b c`: `$d` stands for a path inside the roots only when every item is one; else it is
        unknown, so a later command that uses it is unclear (an existence test still passes)."""
        if items and self._paths_ok(items):
            self.names[name] = _expand(items[0], self.names) or ""
        else:
            self.names.pop(name, None)
            self.loops.add(name)
        return True

    def _only_loop_unknowns(self, words: list) -> bool:
        """`echo "found $d"` where `$d` is an outside loop item: it prints the item, it reads nothing."""
        unknown = {match.group(1) for word in words for match in VARIABLE.finditer(word)} - set(self.names)
        return unknown <= self.loops and not any(word.startswith("~") for word in words)

    def _wrapped(self, words: list) -> bool:
        """`time …`, `timeout 30 …`, `nice -n 5 …`, `env [-C dir] [NAME=v] …`: judge the command they run."""
        cwd, inner = self.cwd, _unwrapped(words)
        if inner is None:
            return False
        directory, inner = inner
        if directory is not None:
            target = self._resolve(directory)
            if not (target.is_dir() and _inside(target, self.roots)):
                return False
            self.cwd = target  # `env -C` moves this one command only
        try:
            return self.reads(inner, ())
        finally:
            self.cwd = cwd

    def _follow_cd(self, words: list) -> bool:
        """A `cd` moves the base of the later relative paths, only into a directory that exists."""
        if os.path.basename(words[0]) != "cd" or len(words) < 2:
            return True
        target = self._resolve(words[1])
        if not target.is_dir():
            return False
        self.cwd = target
        return True

    def _runs_ok(self, words: list) -> bool:
        return _program_reads(words) or (self.pack is not None and self._pack_command(words))

    def _pack_command(self, words: list) -> bool:
        name = os.path.basename(words[0])
        checks = {"git": _git_reads, "ruff": self._ruff, "bb": self._bb_task, "rm": self._removes_scratch}
        if name in checks:
            return checks[name](words[1:])
        if shell.PYTHON.match(name):
            return self._python_tool(words[1:]) or self._acceptance(words)
        return (self._in_tools(words[0]) and self._tool_writes_ok(words)) or self._acceptance(words)

    def _python_tool(self, args: list) -> bool:
        if args[:1] == ["-m"]:
            return len(args) > 1 and args[1].split(".")[0] in PACK_MODULES
        target = next((arg for arg in args if not arg.startswith("-")), None)
        return target is not None and self._in_tools(target) and self._tool_writes_ok(["python3", *args])

    def _tool_writes_ok(self, words: list) -> bool:
        kind = packtools.classify(*shell._resolve(tuple(words)))
        return kind is None or kind in self.writes_ok

    def _bb_task(self, args: list) -> bool:
        """`bb --config <pack>/tools/shared/aps/bb.edn <task> …`: the APS tasks the pack vendors."""
        return args[:1] == ["--config"] and len(args) > 2 and self._in_tools(args[1]) and args[2] in APS_TASKS

    def _ruff(self, args: list) -> bool:
        """A check that reports; or, given the `format` right, a formatter on files the guard already judged."""
        return _ruff_checks(args) or ("format" in self.writes_ok and shell._ruff_rewrites(args))

    def _removes_scratch(self, args: list) -> bool:
        """`rm -f <files>` inside scratch (the protocol deletes a stale artifact first), or `rm -rf` of a
        Python cache folder (`__pycache__`, `.pytest_cache`, `.ruff_cache`) inside the workspace."""
        targets = [arg for arg in args if not arg.startswith("-")]
        flags = {arg for arg in args if arg.startswith("-")}
        if not targets or not flags <= {"-f", "-r", "-rf", "-fr", "-R"}:
            return False
        if flags <= {"-f"}:
            scratch = (*self.pack.every("artifacts"), self.pack.scratch)
            return all(_inside(self._resolve(target), scratch) for target in targets)
        return all(
            os.path.basename(self._resolve(target)) in CACHE_DIRS and _inside(self._resolve(target), self.roots)
            for target in targets
        )

    def _acceptance(self, words: list) -> bool:
        """A project's configured `acceptance_command`, as written (its `NAME=v` prefix aside), plus arguments."""
        for project in self.pack.projects:
            try:
                configured = shell._tokens(project.acceptance) if project.acceptance else []
            except shell.Unparseable:
                continue
            while configured and shell.ASSIGNMENT.match(configured[0]):
                configured.pop(0)
            if configured and words[: len(configured)] == configured:
                return True
        return False

    def _in_tools(self, word: str) -> bool:
        expanded = _expand(word, self.names)
        tools = (self.pack.root / "tools",)
        return expanded is not None and _inside(self._resolve(expanded), tools)

    def _take_assignments(self, words: list) -> None:
        """Drop the leading `NAME=value` words into the line's variables."""
        while words and shell.ASSIGNMENT.match(words[0]):
            name, value = words.pop(0).split("=", 1)
            expanded = _expand(value, self.names)
            if expanded is None:  # `A=$UNKNOWN/x`: a later `$A` is as unclear as `$UNKNOWN`
                self.names.pop(name, None)
            else:
                self.names[name] = expanded

    def _paths_ok(self, words: list) -> bool:
        return all(self._path_ok(word) for word in words)

    def _path_ok(self, word: str) -> bool:
        expanded = _expand(word, self.names)
        if expanded is None or expanded.startswith("~") or ".env" in expanded:
            return False
        if expanded.startswith("-") or expanded in ("/dev/null",):
            return True
        return _inside(self._resolve(expanded), self.roots)

    def _resolve(self, word: str) -> Path:
        expanded = _expand(word, self.names) or ""
        return Path(os.path.normpath(expanded if expanded.startswith("/") else self.cwd / expanded))


def _unclear(command: str) -> bool:
    """A heredoc, or a substitution outside single quotes: the line runs more than the words show."""
    if "<<" in command:
        return True
    return any(mark in _outside_single_quotes(command) for mark in UNCLEAR)


def _outside_single_quotes(command: str) -> str:
    """The text the shell may expand: everything but single-quoted spans (a `'` in double quotes is text)."""
    kept, quote, escaped = [], "", False
    for char in command:
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
        elif char in "'\"" and quote in ("", char):
            quote = "" if quote == char else char
            continue
        if quote != "'":
            kept.append(char)
    return "".join(kept)


def _unwrapped(words: list) -> tuple | None:
    """(the `env -C` directory or None, the wrapped command), or None when the wrapper is not understood."""
    name, rest = words[0], list(words[1:])
    if name == "uv":  # `uv run [--frozen|--no-sync] <command>`: the project's own toolchain
        rest = _drop_leading(rest[1:], UV_FLAGS, ())
        return (None, rest) if rest and not rest[0].startswith("-") else None
    if name == "env":
        return _env_command(rest)
    if name == "time":
        rest = rest[1:] if rest[:1] == ["-p"] else rest
        return (None, rest or ["true"])  # `time ( … )`: the subshell's commands are their own segments
    if name == "timeout":
        rest = _drop_leading(rest, (), ("-s", "-k", "--signal", "--kill-after"))[1:]  # then the duration
    else:  # nice
        rest = rest[2:] if rest[:1] == ["-n"] else rest
    return (None, rest) if rest else None


UV_FLAGS = ("--frozen", "--no-sync", "--locked", "--offline", "-q", "--quiet")


def _drop_leading(rest: list, flags: tuple, with_value: tuple) -> list:
    """`rest` without its leading options: `flags` alone, `with_value` with their value, any other `-x`."""
    while rest[:1] and rest[0].startswith("-"):
        rest = rest[2:] if rest[0] in with_value else rest[1:]
        if flags and rest[:1] and rest[0].startswith("-") and rest[0] not in flags:
            break
    return rest


def _env_command(rest: list) -> tuple | None:
    """`env [-C dir] [-u NAME] …`: (the directory, the command), or None for an option it does not know."""
    directory = None
    while rest[:1] and rest[0] in ("-C", "--chdir", "-u", "--unset"):
        directory = rest[1] if rest[0] in ("-C", "--chdir") and len(rest) > 1 else directory
        rest = rest[2:]
    if not rest or rest[0].startswith("-"):
        return None
    return directory, rest


def _without_keywords(words: list) -> list:
    while words and words[0] in KEYWORDS:
        words = words[1:]
    return words


def _inside(path: Path, roots: tuple) -> bool:
    return any(is_under(path, root) for root in roots)


def git_subcommand(args) -> str:
    """`git -C app status` → `status`: the first word that is neither an option nor an option's value."""
    skip = False
    for arg in args:
        if skip:
            skip = False
        elif arg in GIT_VALUE_OPTIONS:
            skip = True
        elif not arg.startswith("-"):
            return arg
    return ""


def _git_reads(args: list) -> bool:
    return git_subcommand(args) in READ_ONLY_GIT


def _ruff_checks(args: list) -> bool:
    """`ruff check …` without `--fix`, and `ruff format --check …`: they report, they do not write."""
    if args[:1] == ["check"]:
        return not any(arg.startswith(("--fix", "--unsafe-fixes", "--add-noqa")) for arg in args)
    return args[:1] == ["format"] and ("--check" in args or "--diff" in args)


def _program_reads(words: list) -> bool:
    program = os.path.basename(words[0])
    if program == "command":
        return words[1:2] in (["-v"], ["-V"])
    if program == "codegraph":  # tools/README.md › Search and navigation: the index answers, it never writes
        return words[1:2] in (["explore"], ["query"])
    if words[1:] in (["--version"], ["-V"]):
        return program in VERSIONED or shell.PYTHON.match(program) is not None
    if program == "sed":
        return _sed_prints(words[1:])
    return program in READ_ONLY and not (program == "find" and FIND_UNSAFE & set(words))


def _sed_prints(args: list) -> bool:
    """`sed -n 1,80p file`: a line-range print, with no in-place edit and no `w` or `e` command."""
    if "-n" not in args or any(arg.startswith(("-i", "--in-place")) for arg in args):
        return False
    scripts = [arg for arg in args if not arg.startswith("-")][:1]
    return bool(scripts) and SED_PRINT.fullmatch(scripts[0]) is not None


def _expand(word: str, names: dict) -> str | None:
    """`word` with the line's own variables filled in; None when it uses any other variable."""
    unknown = [match.group(1) for match in VARIABLE.finditer(word) if match.group(1) not in names]
    if unknown:
        return None
    return VARIABLE.sub(lambda match: names[match.group(1)], word)
