"""Composition root: one stdin JSON payload in, one hook answer out.

    python3 <plugin>/scripts/sfd context         # SessionStart, SubagentStart
    python3 <plugin>/scripts/sfd guard           # PreToolUse
    python3 <plugin>/scripts/sfd report          # SubagentStop
    python3 <plugin>/scripts/sfd statusline      # statusLine command (wired by `setup`)
    python3 <plugin>/scripts/sfd subagentstatus  # subagentStatusLine (plugin settings.json)
    python3 <plugin>/scripts/sfd setup [...]     # opt-in local settings; not a hook
    python3 <plugin>/scripts/sfd sync-agents     # rebuild agents/ from the pack's protocol/*.md

Outside a workspace with the design pack every hook answers "no opinion". A hook never breaks the session:
an internal error goes to stderr and the answer is "no opinion" (the status line prints a fallback).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

from . import agents_build, context, guard, report, setup, statusline
from .pack import Pack
from .roles import role_of

USAGE = (
    "usage: sfd {context|guard|report|statusline|subagentstatus} < hook-input.json | setup [...] | sync-agents [...]"
)


def run_guard(payload: dict, pack: Pack, environ: dict) -> dict | None:
    return guard.judge(payload, pack).as_output()


def run_report(payload: dict, pack: Pack, environ: dict) -> dict | None:
    role = role_of(payload.get("agent_type"))
    if role is None or role == "orchestrator":
        return None
    message = report.Report(role, str(payload.get("last_assistant_message") or ""))
    found = report.problems(message)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report.save(message, found, pack.reports, stamp, str(payload.get("agent_id") or ""))
    if found and not payload.get("stop_hook_active"):
        return {"decision": "block", "reason": report.block_reason(message, found)}
    return None


def run_context(payload: dict, pack: Pack, environ: dict) -> dict | None:
    event = payload.get("hook_event_name", "")
    role = role_of(payload.get("agent_type"))
    if event == "SessionStart":
        text = context.session_context(pack, role is not None, str(payload.get("session_id") or ""))
        note = agents_build.stale_note(pack.root)
        return context.hook_output(event, f"{note}\n{text}" if note else text)
    if event == "SubagentStart" and role is not None:
        return context.hook_output(event, context.subagent_context(role, pack))
    return None


def run_statusline(payload: dict, pack: Pack, environ: dict) -> str:
    return statusline.render(payload, statusline.load_progress(pack.reports))


def run_subagentstatus(payload: dict, pack: Pack, environ: dict) -> str:
    return statusline.subagent_rows(payload)


COMMANDS = {
    "context": run_context,
    "guard": run_guard,
    "report": run_report,
    "statusline": run_statusline,
    "subagentstatus": run_subagentstatus,
}
FALLBACK = {"statusline": f"{statusline.ICON} swarmforge-design (status unavailable)"}
NO_PACK = {"statusline": f"{statusline.ICON} swarmforge-design: no design pack in this folder"}


def main(argv: list, stdin=None, stdout=None, environ=None) -> int:
    name, args = (argv[0], list(argv[1:])) if argv else ("", [])
    environ = os.environ if environ is None else environ
    if name == "setup":
        return setup.run(args, environ, stdout or sys.stdout)
    if name == "sync-agents":
        return agents_build.run(args, environ, stdout or sys.stdout)
    if name not in COMMANDS:
        print(USAGE, file=sys.stderr)
        return 2
    _emit(_answer(name, stdin or sys.stdin, environ), stdout or sys.stdout)
    return 0


def _answer(name: str, stdin, environ):
    try:
        payload = json.loads(stdin.read() or "{}")
        pack = Pack.load(context.project_dir(payload, environ), environ)
        if pack is None:
            return NO_PACK.get(name)
        return COMMANDS[name](payload, pack, environ)
    except Exception as error:  # noqa: BLE001 (a broken hook must not break the session)
        print(f"sfd {name}: {error}", file=sys.stderr)
        return FALLBACK.get(name)


def _emit(answer, stdout) -> None:
    if isinstance(answer, str):
        stdout.write(answer + "\n")
    elif answer:
        stdout.write(json.dumps(answer) + "\n")
