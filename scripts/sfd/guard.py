"""PreToolUse guard: the pack's rules a tool call can break, enforced before the call runs.

- A role writes only what protocol/README.md › Roles gives it (roles.py), for Edit/Write and shell writes.
- Git: the operator owns commits (workflow.md › Commits). A role runs read-only git only. The orchestrator
  "never commits, amends, stashes, or pushes". In the operator's own session, git that changes history or
  branches asks first.
- No session scans `$HOME` or the whole filesystem.
- The orchestrator dispatches the pack's roles only, and every role dispatch runs in the foreground: the
  chain is sequential ("roles run one at a time because they share the same files").
- Mutation testing is refused: "not part of this pack. Do not run, install or imitate it."
- The pack's lifecycle (`install.py apply`, `update.py apply`, `migrate.py`) is the operator's: a role is
  refused, the orchestrator and the operator are asked. The overlay (`arch classes add|remove|annotate`)
  and the policy (`umlview init|policy …`) are the designer's.
- The designer may change its project's `specs` and `subsystems` in the live config, and nothing else there.
- A shell line that only reads, or runs the pack's own commands, inside the workspace runs unasked.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import packtools, readonly, shell
from .pack import Pack, is_under
from .roles import ROLES, Policy, config_change, policy_for, role_of

EDIT_TOOLS = frozenset({"Edit", "Write", "NotebookEdit", "MultiEdit"})
READ_ONLY_GIT = frozenset(
    {"status", "log", "diff", "show", "rev-parse", "rev-list", "ls-files", "ls-tree", "grep", "blame"}
)
OPERATOR_GIT = frozenset(
    {
        "commit",
        "push",
        "pull",
        "fetch",
        "checkout",
        "switch",
        "restore",
        "rebase",
        "merge",
        "reset",
        "revert",
        "cherry-pick",
        "stash",
        "tag",
        "branch",
        "worktree",
        "clean",
        "am",
    }
)
NEVER_ORCHESTRATOR_GIT = frozenset({"commit", "push", "stash", "reset", "rebase", "am"})
MUTATION = frozenset({"gherkin-mutator", "mutmut", "cosmic-ray", "mutatest"})
ROLE_AGENTS = frozenset(f"swarmforge-design:{role}" for role in ROLES if role != "orchestrator")


@dataclass(frozen=True)
class Verdict:
    decision: str = "allow"  # allow | ask | deny
    reason: str = ""
    updated_input: dict | None = None
    explicit: bool = False  # an "allow" that answers Claude Code's permission prompt

    @property
    def allowed(self) -> bool:
        return self.decision != "deny"

    def as_output(self) -> dict | None:
        if self.decision == "allow" and self.updated_input is None and not self.explicit:
            return None
        output = {
            "hookEventName": "PreToolUse",
            "permissionDecision": self.decision,
            "permissionDecisionReason": self.reason,
        }
        if self.updated_input is not None:
            output["updatedInput"] = self.updated_input
        return {"hookSpecificOutput": output}


ALLOW = Verdict()


def deny(reason: str) -> Verdict:
    return Verdict("deny", reason)


def ask(reason: str) -> Verdict:
    return Verdict("ask", reason)


@dataclass(frozen=True)
class Call:
    policy: Policy | None
    pack: Pack
    cwd: Path
    names: dict = field(default_factory=dict)  # the line's shell variables, for a shell write's target


def judge(payload: dict, pack: Pack) -> Verdict:
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    call = Call(policy_for(role_of(payload.get("agent_type")), pack), pack, Path(payload.get("cwd") or pack.where))
    if tool == "Bash":
        return judge_bash(str(tool_input.get("command", "")), call)
    if tool in EDIT_TOOLS:
        target = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        return judge_write(target, call, lambda text: _edited(tool, tool_input, text))
    if tool == "Agent":
        return judge_agent(tool_input, call)
    return ALLOW


def judge_agent(tool_input: dict, call: Call) -> Verdict:
    target = str(tool_input.get("subagent_type") or "")
    if call.policy is not None and call.policy.name == "orchestrator" and target not in ROLE_AGENTS:
        return deny(
            f"The orchestrator dispatches the pack's roles only (swarmforge-design:<role>), not "
            f"{target or 'a general agent'}."
        )
    if tool_input.get("isolation") == "worktree":
        return ask("The pack has no worktrees (README › Deliberately Absent); confirm this isolated run.")
    if target in ROLE_AGENTS and tool_input.get("run_in_background") is not False:
        return Verdict(
            "allow",
            "A role runs in the foreground: the chain is sequential.",
            {**tool_input, "run_in_background": False},
        )
    return ALLOW


def judge_bash(command: str, call: Call) -> Verdict:
    try:
        segments = shell._segments(shell._tokens(command))
    except shell.Unparseable:
        return ALLOW
    line = _LineState(call)
    verdicts = []
    for words, writes in segments:
        line.assign(words)
        here = replace(call, cwd=line.cwd, names=dict(line.names))
        verdicts += [_judge_command(part, here) for part in shell._unwrap(words, writes)]
        line.follow_cd(words)
    for decision in ("deny", "ask"):
        for verdict in verdicts:
            if verdict.decision == decision:
                return verdict
    writes_ok = _writes_ok(call.policy)
    if verdicts and readonly.reads_only_inside(command, call.cwd, call.pack.workspace_roots, call.pack, writes_ok):
        return Verdict("allow", "swarmforge-design guard: a read-only line or the pack's own commands.", explicit=True)
    return ALLOW


CODE_ROLES = frozenset({"coder", "refactorer", "architect"})


def _writes_ok(policy: Policy | None) -> frozenset:
    """The writing pack commands a line may hold and still run unasked, once the guard has judged its targets:
    the overlay and policy for the designer, the formatter for the roles that own source and tests."""
    if policy is None:
        return frozenset({*packtools.OWNER, "format"})
    if policy.name == "designer":
        return frozenset(packtools.OWNER)
    return frozenset({"format"}) if policy.name in CODE_ROLES else frozenset()


class _LineState:
    """A command line's own variables (`ART=$PACK/tmp/x; rm -f "$ART"/a.*`) and its `cd`s, in order."""

    def __init__(self, call: Call):
        self.cwd = call.cwd
        self.names = {name: call.pack.environ[name] for name in readonly.EXPORTED if call.pack.environ.get(name)}

    def assign(self, words: list) -> None:
        for word in words:
            if not shell.ASSIGNMENT.match(word):
                break
            name, value = word.split("=", 1)
            expanded = readonly._expand(value, self.names)
            if expanded is None:
                self.names.pop(name, None)
            else:
                self.names[name] = expanded

    def follow_cd(self, words: list) -> None:
        words = [word for word in words if not shell.ASSIGNMENT.match(word)]
        if words[:1] != ["cd"] or len(words) < 2:
            return
        target = readonly._expand(words[1], self.names)
        self.cwd = _absolute(target, self.cwd) if target and not target.startswith("~") else self.cwd


def judge_write(target: str, call: Call, edit=None) -> Verdict:
    """`edit(current text) -> new text` is the file's content after an Edit/Write; None for a shell write."""
    if call.policy is None or not target:
        return ALLOW
    path = _absolute(target, call.cwd)
    if call.policy.name == "designer" and path == call.pack.config and edit is not None:
        return _judge_config_edit(path, edit, call)
    why = call.policy.refusal(path, call.pack)
    if why is None:
        return ALLOW
    return deny(
        f"The {call.policy.name} may not write {call.pack.rel(path)}: {why}. Stop and report it as "
        "blocked; the file's owner or the operator makes this change."
    )


def _judge_config_edit(path: Path, edit, call: Call) -> Verdict:
    try:
        before = path.read_text(encoding="utf-8")
    except OSError as error:
        return deny(f"The designer may not create {path.name}: {error}. The operator installs the config.")
    after = edit(before)
    why = "the edit does not apply to the current file" if after is None else config_change(before, after)
    if why is None:
        return ALLOW
    return deny(f"The designer may not make this change to {call.pack.rel(path)}: {why}.")


def _edited(tool: str, tool_input: dict, text: str) -> str | None:
    """The file after this Edit/MultiEdit/Write, or None when an edit's old text is not in it."""
    if tool == "Write":
        return str(tool_input.get("content") or "")
    edits = tool_input.get("edits") if tool == "MultiEdit" else [tool_input]
    for change in edits or []:
        old, new = str(change.get("old_string") or ""), str(change.get("new_string") or "")
        if not old or old not in text:
            return None
        text = text.replace(old, new) if change.get("replace_all") else text.replace(old, new, 1)
    return text


def _judge_tool(command: shell.SimpleCommand, call: Call) -> Verdict:
    kind = packtools.classify(command.program, command.args)
    policy = call.policy
    if kind == "lifecycle":
        if policy is not None and policy.name != "orchestrator":
            return deny(
                f"`{command.program} {' '.join(command.args)}` changes the harness or its wiring: the "
                "operator's call. Report it; do not run it."
            )
        return ask(
            f"`{command.program}` changes the installed harness (README › Update): run it only on the "
            "operator's explicit yes."
        )
    if kind in packtools.OWNER and policy is not None and policy.name != packtools.OWNER[kind]:
        return deny(
            f"The {kind} is the {packtools.OWNER[kind]}'s (protocol/README.md › Roles): the "
            f"{policy.name} reports what it needs instead."
        )
    return ALLOW


def _judge_command(command: shell.SimpleCommand, call: Call) -> Verdict:
    if command.program == "find" and _searches_outside(command.args, call):
        return deny("Do not scan $HOME or the whole filesystem; search a path inside the pack or the project.")
    if MUTATION & {command.program, *command.args}:
        return deny(
            "Mutation testing is not part of this pack (engineering.md › Acceptance Pipeline): do not "
            "run, install or imitate it. The test-reviewer names the wrong implementation instead."
        )
    git = _judge_git(readonly.git_subcommand(command.args), call) if command.program == "git" else ALLOW
    for verdict in (git, _judge_tool(command, call)):
        if verdict.decision != "allow":
            return verdict
    return _judge_targets(command, call)


def _judge_targets(command: shell.SimpleCommand, call: Call) -> Verdict:
    for target in command.written_paths():
        expanded = readonly._expand(target, call.names)
        if expanded is None or _clears_scratch(command, expanded, call):
            continue  # an unseen variable: Claude Code's own permission check decides
        verdict = judge_write(expanded, call)
        if not verdict.allowed:
            return verdict
    return ALLOW


def _clears_scratch(command: shell.SimpleCommand, target: str, call: Call) -> bool:
    """A role deletes a stale generated file under scratch before it regenerates it (tools/README.md ›
    For Project-Side Runners: "delete a feature's stale IR, dry report and generated module")."""
    if os.path.basename(command.words[0]) not in ("rm", "unlink") or call.policy is None:
        return False
    if call.policy.name == "orchestrator":
        return False
    path = _absolute(target, call.cwd)
    if path.name in readonly.CACHE_DIRS:  # a Python cache folder anywhere in the workspace
        return any(is_under(path, root) for root in call.pack.workspace_roots)
    return any(is_under(path, root) for root in (*call.pack.every("artifacts"), call.pack.scratch))


def _judge_git(subcommand: str, call: Call) -> Verdict:
    policy = call.policy
    if policy is not None and policy.read_only_git and subcommand not in READ_ONLY_GIT:
        return deny(f"A role runs read-only git only, not `git {subcommand}`: the operator owns git.")
    if policy is not None and subcommand in NEVER_ORCHESTRATOR_GIT:
        return deny(f"The orchestrator never runs `git {subcommand}`: the operator owns git history.")
    if subcommand in OPERATOR_GIT:
        return ask(f"`git {subcommand}` is the operator's call (workflow.md › Commits); confirm it, or decline.")
    return ALLOW


def _searches_outside(args: tuple, call: Call) -> bool:
    roots = [arg for arg in args if not arg.startswith("-")][:1]
    if not roots:
        return False
    if roots[0].startswith(("~", "$HOME", "${HOME}")):
        return True
    start = _absolute(roots[0], call.cwd)
    return not any(is_under(start, root) for root in call.pack.workspace_roots)


def _absolute(target: str, cwd: Path) -> Path:
    path = Path(target).expanduser()
    return (path if path.is_absolute() else cwd / path).resolve()
