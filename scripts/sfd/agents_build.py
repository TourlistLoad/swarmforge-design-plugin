"""`sfd sync-agents`: build the plugin's agents from the pack's own `protocol/<role>.md`.

The pack defines its roles in `protocol/*.md` and nowhere else ("Do not look for agent definitions in
`.opencode/`"). Each agent is: Claude Code frontmatter, a short Claude Code mapping, the constitution and
its three articles verbatim, and the role file verbatim, so a brief's read steps 1-3 cost nothing. It
writes into the plugin's folder only. Run it after a pack update, then `/reload-plugins`.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

from .context import MAPPING
from .pack import PLUGIN_ROOT, Pack, find_pack
from .roles import ROLES

# The operator's choice: every role on Haiku 5.5 at medium effort. Override one role with --model.
DEFAULT_MODEL = "haiku:medium"
DESCRIPTIONS = {
    "orchestrator": "Decides the chain, dispatches the design pack's roles one at a time, and is the only one who "
    "talks to the operator. Run it as the main conversation with `claude --agent swarmforge-design:orchestrator`.",
    "designer": "Owns intent, behavior, class design and the design views: the subsystem spec, the runtime model, "
    "the class overlay and policy, and its project's specs and subsystems in the pack config.",
    "specifier": "Turns the designer's note into one .feature and runs the Gherkin parser and dry-checker.",
    "coder": "Builds the acceptance pipeline and implements the behavior test-first, with unit tests.",
    "test-reviewer": "Gives the independent verdict on the coder's tests: accept or reject, findings only.",
    "refactorer": "Improves coverage, property tests, duplication and CRAP without changing behavior.",
    "architect": "Checks boundaries and dependency direction, then runs the terminal gate in full.",
}
COLORS = {
    "orchestrator": "purple",
    "designer": "pink",
    "specifier": "yellow",
    "coder": "orange",
    "test-reviewer": "red",
    "refactorer": "cyan",
    "architect": "blue",
}
TAIL = " A swarmforge-design role: the orchestrator dispatches it; never use it for other work."
WORKER_TOOLS = ("Bash", "Read", "Edit", "Write", "Glob", "Grep")
ORCHESTRATOR_TOOLS = ("Agent", "SendMessage", "AskUserQuestion", "Bash", "Read", "Glob", "Grep")
ARTICLE_LINE = re.compile(r"`(constitution/articles/[^`]+\.md)`")
REFERENCES = ("tools/README.md", "tools/design/README.md")  # every brief's read steps 6-7: every role reads them
DIGEST = re.compile(r"<!-- pack digest: ([0-9a-f]{12}) -->")


def model_and_effort(role: str, overrides: dict) -> tuple:
    chosen = overrides.get(role) or overrides.get("*") or DEFAULT_MODEL
    name, _, effort = chosen.partition(":")
    return name, effort or None


def articles(root: Path) -> list:
    """The articles in the order `constitution.md` names them, else every article by name."""
    try:
        named = ARTICLE_LINE.findall((root / "constitution.md").read_text())
    except OSError:
        named = []
    listed = [root / name for name in dict.fromkeys(named) if (root / name).is_file()]
    return listed or sorted((root / "constitution" / "articles").glob("*.md"))


def tools_for(role: str, skills: bool) -> str:
    tools = ORCHESTRATOR_TOOLS if role == "orchestrator" else WORKER_TOOLS
    return ", ".join(tools + (("Skill",) if skills else ()))


def render(role: str, root: Path, overrides: dict, skills: bool = False) -> str:
    model, effort = model_and_effort(role, overrides)
    front = [
        f"name: {role}",
        f'description: "{(DESCRIPTIONS[role] + ("" if role == "orchestrator" else TAIL))}"',
        f"model: {model}",
    ]
    front += [f"effort: {effort}"] if effort else []
    front += [f"color: {COLORS[role]}", f"tools: {tools_for(role, skills)}"]
    front += ["omitClaudeMd: true"] if role != "orchestrator" else []
    constitution = [(root / "constitution.md"), *articles(root)]
    pack_text = "\n\n".join(f"# $PACK/{path.relative_to(root)}\n\n{path.read_text().strip()}" for path in constitution)
    role_text = (root / "protocol" / f"{role}.md").read_text().strip()
    references = [
        f'<reference file="$PACK/{name}">\n{(root / name).read_text().strip()}\n</reference>'
        for name in REFERENCES
        if (root / name).is_file()
    ]
    return "\n".join(
        [
            "---",
            *front,
            "---",
            (
                f"<!-- Built by `sfd sync-agents` from protocol/{role}.md, the constitution and the tool guides. Do "
                "not edit: change the pack, then run /swarmforge-design:sync-agents. -->"
            ),
            f"<!-- pack digest: {digest(root)} -->",
            "",
            "<claude_code>",
            _preamble(role),
            "</claude_code>",
            "",
            "<constitution>",
            pack_text,
            "</constitution>",
            "",
            f'<role file="$PACK/protocol/{role}.md">',
            role_text,
            "</role>",
            "",
            *references,
            "",
        ]
    )


def digest(root: Path) -> str:
    """One hash over every pack file an agent carries, so a pack update shows up as stale agents."""
    names = ["constitution.md", *(str(p.relative_to(root)) for p in articles(root))]
    names += [f"protocol/{role}.md" for role in ROLES] + list(REFERENCES)
    hashed = hashlib.sha256()
    for name in names:
        path = root / name
        hashed.update(name.encode() + b"\0" + (path.read_bytes() if path.is_file() else b"") + b"\0")
    return hashed.hexdigest()[:12]


def stale_note(root: Path, agents: Path = PLUGIN_ROOT / "agents") -> str:
    """A line for the session start when the built agents carry another version of the pack, else ""."""
    try:
        found = {DIGEST.search(path.read_text()) for path in agents.glob("*.md")}
    except OSError:
        return ""
    built = {match.group(1) for match in found if match}
    if not built or built == {digest(root)}:
        return ""
    return (
        "Warning: the role agents were built from another version of the pack's protocol and guides. Run "
        "/swarmforge-design:sync-agents, then /reload-plugins, before dispatching."
    )


def _preamble(role: str) -> str:
    lines = [f"You run under Claude Code as the plugin agent `swarmforge-design:{role}`.", MAPPING]
    if role == "orchestrator":
        lines.append(
            "You have no Write or Edit tool: you write nothing in the project. Dispatch "
            "`swarmforge-design:<role>` with the brief shape of your role file; a guard refuses any other "
            "agent type. Each role's report is saved under $PACK/tmp/claude-reports/. Every role agent carries "
            "the constitution, the articles, its own role file and both tool guides, and gets PROJECT.md at "
            "start: keep the read order in the brief, but mark steps 1-4, 6 and 7 `(in your system prompt)` so "
            "the role reads only the config and the task's own files. Step 5 names the config file that "
            "resolved (CONFIG in your session start, usually `config/pack.local.json`), not the tracked legacy "
            "`config/pack.json`."
        )
    else:
        lines.append(
            "Above you, verbatim: the constitution, its three articles, your role file, and below them "
            "`tools/README.md` and `tools/design/README.md`. Your start context holds `PROJECT.md` and the resolved "
            "config. When a brief's read order names any of these, they are read: do not open them again. Read "
            "the config file itself only for a key the start context does not show (specs, subsystems, gates). "
            "A guard hook refuses what your role may not write or run: treat a refusal as a blocked report, as "
            "workflow.md › Failure says."
        )
    return "\n".join(lines)


def build(root: Path, overrides: dict, skills: bool = False) -> dict:
    return {
        role: render(role, root, overrides, skills) for role in ROLES if (root / "protocol" / f"{role}.md").is_file()
    }


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="sfd sync-agents", description=__doc__.splitlines()[0])
    cli.add_argument("--project", type=Path, help="where Claude Code runs (default: CLAUDE_PROJECT_DIR or cwd)")
    cli.add_argument("--out", type=Path, default=PLUGIN_ROOT / "agents")
    cli.add_argument("--check", action="store_true", help="write nothing; exit 1 when an agent is out of date")
    cli.add_argument(
        "--model",
        action="append",
        default=[],
        metavar="ROLE=MODEL[:EFFORT]",
        help="one role's model, e.g. architect=opus:high (repeatable)",
    )
    cli.add_argument(
        "--default",
        default=DEFAULT_MODEL,
        metavar="MODEL[:EFFORT]",
        help=f"every other role's model (default {DEFAULT_MODEL})",
    )
    cli.add_argument(
        "--skills",
        choices=("auto", "on", "off"),
        default="auto",
        help="give the roles the Skill tool: auto = when the workspace has .claude/skills/*/SKILL.md",
    )
    return cli


def run(argv: list, environ: dict, stdout) -> int:
    options = parser().parse_args(argv)
    where = Path(options.project or environ.get("CLAUDE_PROJECT_DIR") or ".").resolve()
    root = find_pack(where, environ)
    if root is None:
        stdout.write(f"sync-agents: no design pack (constitution.md, protocol/orchestrator.md) at {where}\n")
        return 1
    overrides = dict(item.split("=", 1) for item in options.model if "=" in item)
    overrides["*"] = options.default
    pack = Pack.load(where, environ)
    skills = options.skills == "on" or (options.skills == "auto" and _has_skills(where, pack))
    built = build(root, overrides, skills)
    stale = [role for role, text in built.items() if _current(options.out / f"{role}.md") != text]
    stdout.write(
        f"sync-agents: {len(built)} roles from {root}/protocol; {len(stale)} out of date: "
        f"{', '.join(stale) or 'none'}\n"
    )
    if options.check:
        return 1 if stale else 0
    options.out.mkdir(parents=True, exist_ok=True)
    for role in stale:
        (options.out / f"{role}.md").write_text(built[role])
    if stale:
        stdout.write("  - written; run /reload-plugins (or restart Claude Code) to load them\n")
    return 0


def _has_skills(where: Path, pack: Pack | None) -> bool:
    bases = [where] + ([project.project for project in pack.projects] if pack else [])
    return any(any((base / ".claude" / "skills").glob("*/SKILL.md")) for base in bases)


def _current(path: Path) -> str | None:
    return path.read_text() if path.is_file() else None
