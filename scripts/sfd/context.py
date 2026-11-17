"""SessionStart and SubagentStart: the resolved paths every brief and command needs.

tools/README.md writes its commands with `$PACK`, `PACK_PROJECT=<project>` and the roots of the selected
project, and warns that a relative `--source-root` "analyzes nothing and still exits 0". So every session
and every role starts with the config file that resolved and each project's absolute roots. A role also
gets `PROJECT.md`, step 3 of every brief's read order, so it does not spend a read on it. Claude Code caps
a hook's text at 10,000 characters; every text here stays under it.
"""

from __future__ import annotations

from pathlib import Path

from .pack import Pack, Project
from .roles import policy_for

CAP = 9_500
PROJECT_MD_CAP = 4_000
ENTRY_POINTS = (
    "`claude --agent swarmforge-design:orchestrator`",
    "/swarmforge-design:swarm <task>",
    "/swarmforge-design:install",
    "/swarmforge-design:update",
    "/swarmforge-design:verify-pack",
    "/swarmforge-design:setup",
    "/swarmforge-design:sync-agents",
)

MAPPING = """\
The pack is written for any agent host. In Claude Code:
- A role is the plugin agent `swarmforge-design:<role>`: its system prompt holds the constitution, the three \
articles, `protocol/<role>.md`, `tools/README.md` and `tools/design/README.md`, verbatim, and its start context \
holds `PROJECT.md` and the resolved config. In a brief's read order those steps are done.
- The orchestrator dispatches with the `Agent` tool, in the foreground, one role at a time per project, and \
asks the operator with `AskUserQuestion`. A child that stopped early is continued with `SendMessage` \
(`Continue`) to its agent id; that runs in the background, so end the turn and act on its completion notice.
- Run the commands of `tools/README.md` as written, each prefixed `PACK_PROJECT=<project>`. `$PACK` is \
exported by `/swarmforge-design:setup`; else use the absolute paths below. Every `--source-root` is absolute.
- No `codegraph` on PATH means no index: locate code with Glob, or Grep on a named path (engineering.md › \
Navigation).
- Change a file with Write or Edit, not through the shell (`cat > f <<EOF`): a shell write asks the \
operator and stops the run."""


def paths_text(pack: Pack) -> str:
    lines = [
        "Resolved by the pack's config rule (absolute):",
        f"PACK       {pack.root}",
        f"CONFIG     {pack.config or 'none'}",
    ]
    if pack.projects:
        default = pack.default or "none"
        lines.append(f"Projects ({pack.selector} selects one; unset means default_project = {default}):")
        lines += [_project_text(project, pack) for project in pack.projects]
    if pack.problem:
        lines.append(
            f"Config problem: {pack.problem}. Run `python3 $PACK/tools/doctor.py`; the install is "
            "the operator's (/swarmforge-design:install)."
        )
    return "\n".join(lines)


def _project_text(project: Project, pack: Pack) -> str:
    mark = " (default)" if project.name == pack.default else ""
    rows = [f"    {label:<9} {path}" for label, path in project.rows()]
    if project.design is None:
        rows.append(f"    DESIGN    legacy {pack.architecture / project.name} (read-only: no design_root)")
    if project.acceptance:
        rows.append(f"    ACCEPT    {project.acceptance}  (run from PROJECT)")
    return "\n".join([f"  {project.name}{mark}", *rows])


def last_report(pack: Pack) -> str:
    progress = pack.reports / "progress.json"
    try:
        text = progress.read_text()
    except OSError:
        return "No role report is recorded yet."
    return f"Last role report: {progress.parent}/ (progress.json: {text.strip()[:400]})"


def project_record(pack: Pack) -> str:
    """`PROJECT.md`, the environment record every role reads third, or a note that it is missing."""
    record = pack.root / "PROJECT.md"
    try:
        text = record.read_text(encoding="utf-8").strip()
    except OSError:
        return f"{record} does not exist yet (the operator writes it; doctor warns). Say so if the task needs it."
    if len(text) > PROJECT_MD_CAP:
        text = text[:PROJECT_MD_CAP] + f"\n[… cut: read {record} for the rest.]"
    return f'<project_md path="{record}">\n{text}\n</project_md>'


def session_context(pack: Pack, agent: bool, session_id: str = "") -> str:
    head = ["swarmforge-design plugin: the SwarmForge Lite design pack under Claude Code. The repository is unchanged."]
    if not agent:  # an agent run as the main conversation has the mapping in its system prompt
        head += [MAPPING, "Entry points: " + " · ".join(ENTRY_POINTS) + "."]
    tail = [f"Claude Code session id: {session_id}"] if session_id else []
    return fit("\n".join([*head, paths_text(pack), last_report(pack), *tail]))


def subagent_context(role: str, pack: Pack) -> str:
    policy = policy_for(role, pack)
    kinds = ", ".join(dict.fromkeys(label for label, _ in policy.roots)) or "nothing"
    return fit(
        "\n".join(
            [
                f"This subagent is the `{role}` role (plugin agent `swarmforge-design:{role}`).",
                (
                    f"Write scope enforced by the guard hook: {kinds}, in the projects above. Generated files (rendered "
                    "views, .metrics, generated acceptance tests, the class overlay) are written by their tools only."
                ),
                (
                    "A SubagentStop hook checks that your report names each command with its exit status (or says you "
                    f"are blocked) and saves it under {pack.reports}/."
                ),
                paths_text(pack),
                project_record(pack),
            ]
        )
    )


def fit(text: str) -> str:
    if len(text) <= CAP:
        return text
    tail = "\n[… cut: read the config for the rest.]"
    return text[: CAP - len(tail)] + tail


def hook_output(event: str, text: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def project_dir(payload: dict, environ: dict) -> Path:
    workspace = payload.get("workspace") or {}
    return Path(environ.get("CLAUDE_PROJECT_DIR") or workspace.get("project_dir") or payload.get("cwd") or ".")
