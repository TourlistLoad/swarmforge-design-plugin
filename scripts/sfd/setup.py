"""`sfd setup`: the per-workspace settings a plugin cannot ship, written where git never looks.

A plugin may not set permission rules, environment variables, the status line or the subagent cache TTL.
This command adds them to the workspace's `.claude/settings.local.json` (personal settings, which Claude Code
keeps out of git) and lists that file in `.git/info/exclude` when the workspace is a git checkout. It sets
`PACK` for every shell command (and `PROJECT` when the config has one project), so the commands of
`tools/README.md` run exactly as written.
`--undo` removes exactly what it adds.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, replace
from pathlib import Path

from .pack import PLUGIN_ROOT, Pack, is_under

SETTINGS = Path(".claude") / "settings.local.json"
EXCLUDE_MARK = "# swarmforge-design plugin (sfd setup): local files git must not see"
EXCLUDE_LINES = (".claude/settings.local.json",)
CACHE_TTL = "1h"
ORCHESTRATOR = "swarmforge-design:orchestrator"
DENY = ("Read(**/.env)", "Read(**/.env.*)")
TEMPORARY_ROOT = "claude-plugin-session-"  # where Claude Code unpacks a `--plugin-dir <zip>` plugin


@dataclass(frozen=True)
class Plan:
    """What setup adds; an empty or None part is left alone."""

    allow: tuple = ()
    deny: tuple = ()
    env: dict | None = None
    statusline: dict | None = None
    cache_ttl: str | None = None
    agent: str | None = None


VERSION_CHECKS = tuple(f"Bash({tool} --version)" for tool in ("git", "ruff", "pytest", "coverage", "bb"))
MODULES = ("pytest", "coverage", "dryer", "crapper")


def full_plan(pack: Pack, plugin_root: Path = PLUGIN_ROOT) -> Plan:
    tools = [rule for prefix in _prefixes(pack) for rule in _tool_rules(prefix)]
    tools += [f"Bash(python3 -m {module} *)" for module in MODULES]
    tools += [f"Bash(PYTHONPATH=* python3 -m {module} *)" for module in ("dryer", "crapper")]
    tools += ["Bash(ruff check *)", "Bash(ruff format --check *)", "Bash(codegraph explore *)", *VERSION_CHECKS]
    tools += [f"Bash({project.acceptance}*)" for project in pack.projects if project.acceptance]
    tools += edit_rules(pack)
    env = {"PACK": str(pack.root)}
    if len(pack.projects) == 1:  # with several projects `$PROJECT` depends on PACK_PROJECT: not exported
        env["PROJECT"] = str(pack.projects[0].project)
    command = f'python3 "{plugin_root / "scripts" / "sfd"}" statusline'
    return Plan(
        tuple(dict.fromkeys(tools)), DENY, env, {"type": "command", "command": command}, CACHE_TTL, ORCHESTRATOR
    )


def _prefixes(pack: Pack) -> list:
    """The pack as a command names it: relative to where Claude Code runs, absolute, and `$PACK`."""
    shown = pack.rel(pack.root)
    prefixes = ["" if shown == "." else shown + "/"]
    if str(pack.root) != shown:
        prefixes.append(f"{pack.root}/")
    return [*prefixes, "$PACK/"]


def _tool_rules(prefix: str) -> list:
    """The pack's read-only entry points (tools/README.md); the guard judges the rest."""
    return [
        f"Bash(python3 {prefix}tools/gate.py *)",
        f"Bash(python3 {prefix}tools/doctor.py*)",
        f"Bash(python3 {prefix}tools/design/arch.py *)",
        f"Bash(python3 {prefix}tools/umlview *)",
        f"Bash(python3 {prefix}tools/install.py inspect *)",
        f"Bash(python3 {prefix}tools/update.py check*)",
        f"Bash(python3 {prefix}tools/update.py trial*)",
        f"Bash({prefix}tools/shared/gherkin-parser *)",
        f"Bash(bb --config {prefix}tools/shared/aps/bb.edn *)",
    ]


def edit_rules(pack: Pack) -> list:
    """File edits in the roots the roles write; the guard still holds each role to its own."""
    specs = [docs / "specs" for docs in pack.every("docs")]
    roots = [*specs, *pack.every("features"), *pack.every("sources"), *pack.every("tests"), *pack.every("artifacts")]
    kept = []
    for root in dict.fromkeys(roots):
        if not any(is_under(root, other) for other in kept):
            kept = [other for other in kept if not is_under(other, root)] + [root]
    rules = [f"Edit({_edit_root(pack, root)}/**)" for root in kept]
    designs = [design / name for design in pack.every("design") for name in ("runtime.json", "policy.json")]
    return rules + [f"Edit({_edit_root(pack, path)})" for path in designs]


def _edit_root(pack: Pack, root: Path) -> str:
    return f"/{pack.rel(root)}" if is_under(root, pack.where) else f"/{root}"


def chosen_plan(full: Plan, options) -> Plan:
    return replace(
        full,
        allow=() if options.no_permissions else full.allow,
        deny=() if options.no_permissions else full.deny,
        env=None if options.no_env else full.env,
        statusline=None if options.no_statusline else full.statusline,
        cache_ttl=None if options.no_cache_ttl else full.cache_ttl,
        agent=full.agent if options.default_agent else None,
    )


def merged(settings: dict, plan: Plan) -> dict:
    """`settings` with the plan added; the operator's own values always win."""
    out = json.loads(json.dumps(settings))
    for key, rules in (("allow", plan.allow), ("deny", plan.deny)):
        if rules:
            current = out.setdefault("permissions", {}).setdefault(key, [])
            current.extend(rule for rule in rules if rule not in current)
    for name, value in (plan.env or {}).items():
        out.setdefault("env", {}).setdefault(name, value)
    for key, value in (
        ("statusLine", plan.statusline),
        ("subagentPromptCacheTtl", plan.cache_ttl),
        ("agent", plan.agent),
    ):
        if value is not None:
            out.setdefault(key, value)
    return out


def unmerged(settings: dict, plan: Plan) -> dict:
    """`settings` without anything the plan would add; other values stay."""
    out = json.loads(json.dumps(settings))
    permissions = out.get("permissions", {})
    for key, rules in (("allow", plan.allow), ("deny", plan.deny)):
        kept = [rule for rule in permissions.get(key, []) if rule not in rules]
        if kept:
            permissions[key] = kept
        else:
            permissions.pop(key, None)
    if not permissions:
        out.pop("permissions", None)
    env = out.get("env", {})
    for name, value in (plan.env or {}).items():
        if env.get(name) == value:
            env.pop(name)
    if "env" in out and not env:
        out.pop("env")
    for key, value in (
        ("statusLine", plan.statusline),
        ("subagentPromptCacheTtl", plan.cache_ttl),
        ("agent", plan.agent),
    ):
        if value is not None and out.get(key) == value:
            out.pop(key)
    return out


def with_excludes(text: str) -> str:
    if EXCLUDE_MARK in text:
        return text
    body = text if not text or text.endswith("\n") else text + "\n"
    return body + "\n".join((EXCLUDE_MARK, *EXCLUDE_LINES)) + "\n"


def without_excludes(text: str) -> str:
    lines = text.splitlines()
    if EXCLUDE_MARK not in lines:
        return text
    start = lines.index(EXCLUDE_MARK)
    end = start + 1
    while end < len(lines) and lines[end] in EXCLUDE_LINES:
        end += 1
    kept = lines[:start] + lines[end:]
    return "\n".join(kept) + ("\n" if kept else "")


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="sfd setup", description=__doc__.splitlines()[0])
    cli.add_argument("--project", type=Path, help="the workspace root (default: CLAUDE_PROJECT_DIR or cwd)")
    cli.add_argument("--dry-run", action="store_true", help="print the result, write nothing")
    cli.add_argument("--undo", action="store_true", help="remove what setup added")
    cli.add_argument("--no-permissions", action="store_true", help="skip the allow and deny rules")
    cli.add_argument("--no-env", action="store_true", help="skip the PACK (and PROJECT) variables")
    cli.add_argument("--no-statusline", action="store_true", help="skip the status line")
    cli.add_argument("--no-cache-ttl", action="store_true", help="skip subagentPromptCacheTtl")
    cli.add_argument(
        "--default-agent", action="store_true", help=f"also start every session in this workspace as {ORCHESTRATOR}"
    )
    return cli


def run(argv: list, environ: dict, stdout) -> int:
    options = parser().parse_args(argv)
    where = Path(options.project or environ.get("CLAUDE_PROJECT_DIR") or ".").resolve()
    pack = Pack.load(where, environ)
    if pack is None:
        return _refuse(stdout, f"no design pack at {where} (expected {where}/swarm-forge-lite)")
    if not pack.projects:
        return _refuse(stdout, f"{pack.problem or 'the pack config names no project'}; run /swarmforge-design:install")
    settings_file = where / SETTINGS
    current = _read_settings(settings_file)
    if current is None:
        return _refuse(stdout, f"{settings_file} is not valid JSON; fix it first")
    full = full_plan(pack)
    result = unmerged(current, full) if options.undo else merged(current, chosen_plan(full, options))
    exclude = where / ".git" / "info" / "exclude"
    verb = "would " if options.dry_run else ""
    lines = rule_changes(current, result, verb) + value_changes(current, result, full, verb)
    lines.append(exclude_change(exclude, verb, options.undo))
    lines += temporary_root_note(PLUGIN_ROOT, result)
    stdout.write("\n".join([f"setup: {settings_file}", *(f"  - {line}" for line in lines)]) + "\n")
    if options.dry_run:
        stdout.write(json.dumps(result, indent=2) + "\n")
        return 0
    _write_settings(settings_file, result)
    _write_excludes(exclude, options.undo)
    return 0


def rule_changes(before: dict, after: dict, verb: str) -> list:
    lines = []
    for key in ("allow", "deny"):
        old = set(before.get("permissions", {}).get(key, []))
        new = set(after.get("permissions", {}).get(key, []))
        if new != old:
            change = "add" if len(new) > len(old) else "remove"
            lines.append(f"{verb}{change} {abs(len(new) - len(old))} permissions.{key} rule(s)")
    return lines


def value_changes(before: dict, after: dict, full: Plan, verb: str) -> list:
    ours = {"statusLine": full.statusline, "subagentPromptCacheTtl": full.cache_ttl, "agent": full.agent}
    lines = [f"{verb}update env ({', '.join(full.env or {})})"] if before.get("env") != after.get("env") else []
    for key, value in ours.items():
        if before.get(key) != after.get(key):
            lines.append(f"{verb}{'set' if key in after else 'remove'} {key}")
        elif key in before and before[key] != value:
            lines.append(f"kept your own {key}")
    return lines


def temporary_root_note(plugin_root: Path, result: dict) -> list:
    """A plugin loaded with `--plugin-dir <zip>` runs from a folder that ends with the session."""
    if TEMPORARY_ROOT not in str(plugin_root) or "statusLine" not in result:
        return []
    return [
        (
            f"note: this plugin runs from a temporary folder ({plugin_root}); install it, then run setup again, "
            "or the status line stops working when this session ends"
        )
    ]


def exclude_change(exclude: Path, verb: str, undo: bool) -> str:
    if not exclude.parent.parent.is_dir():
        return "not a git checkout: no .git/info/exclude to update"
    return f"{verb}{'remove' if undo else 'list'} {', '.join(EXCLUDE_LINES)} in {exclude}"


def _refuse(stdout, why: str) -> int:
    stdout.write(f"setup: {why}; nothing written\n")
    return 1


def _read_settings(settings_file: Path) -> dict | None:
    """The current local settings ({} when the file is absent), or None when it is not valid JSON."""
    try:
        return json.loads(settings_file.read_text()) if settings_file.is_file() else {}
    except ValueError:
        return None


def _write_settings(settings_file: Path, result: dict) -> None:
    if not result:
        settings_file.unlink(missing_ok=True)
        return
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(result, indent=2) + "\n")


def _write_excludes(exclude: Path, undo: bool) -> None:
    if not exclude.parent.parent.is_dir():
        return
    text = exclude.read_text() if exclude.is_file() else ""
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text(without_excludes(text) if undo else with_excludes(text))
