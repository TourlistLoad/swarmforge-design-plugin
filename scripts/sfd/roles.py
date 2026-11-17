"""What each role may write: the pack's own table (protocol/README.md › Roles), made enforceable.

| Role          | Writes                                                                                  |
|---------------|-----------------------------------------------------------------------------------------|
| orchestrator  | nothing in the project                                                                  |
| designer      | `<docs_root>/specs/`, `<design_root>/{runtime,policy}.json` (and the overlay through   |
|               | `arch classes add|remove|annotate`), its project's `specs`/`subsystems` in the config  |
| specifier     | the `.feature` files                                                                    |
| coder         | source, tests, generated acceptance (through the generator)                            |
| test-reviewer | nothing but findings under the artifacts root                                           |
| refactorer    | source, tests                                                                           |
| architect     | source, tests                                                                           |

One pack serves several projects, so each root is the union over the config's `projects`: a role writes
its kind of file in any project, and the brief names which. Every role may write scratch under an
artifacts root (workflow.md › Scratch Files). Generated files are never hand-edited (engineering.md): the
rendered views (`*.html` under a docs root), the analysis reports (`.metrics/`), the generated acceptance
tests, and the overlay. Features belong to the specifier and docs and design data to the designer even
where a test path holds them. Nobody writes the pack's harness, its legacy `architecture/`, `PROJECT.md`
(the operator's record) or Claude Code's configuration. The config itself is judged by `config_change`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .pack import Pack, is_under

PLUGIN_NAME = "swarmforge-design"
ROLES = ("orchestrator", "designer", "specifier", "coder", "test-reviewer", "refactorer", "architect")
WORKERS = tuple(role for role in ROLES if role != "orchestrator")
DESIGNER_CONFIG_KEYS = frozenset({"specs", "subsystems"})
AUTHORED_DESIGN = ("runtime.json", "policy.json")


@dataclass(frozen=True)
class Policy:
    """One role: the roots it writes, and whether its git is read-only."""

    name: str
    roots: tuple  # ((label, Path), ...)
    read_only_git: bool = True

    def refusal(self, path: Path, pack: Pack) -> str | None:
        """Why `path` is not this role's to write, or None."""
        for label, matches in _forbidden(pack, self.name):
            if matches(path):
                return f"it is {label}"
        if any(is_under(path, root) for _, root in self.roots):
            return None
        kinds = ", ".join(dict.fromkeys(label for label, _ in self.roots)) or "nothing"
        return f"the {self.name} writes {kinds}"

    def describe(self) -> str:
        return "; ".join(f"{label} {path}" for label, path in self.roots) or "nothing"


def role_of(agent_type: str | None) -> str | None:
    """The role behind `swarmforge-design:<role>`; another plugin's agent with a role's name is not one."""
    if not agent_type:
        return None
    plugin, _, name = agent_type.rpartition(":")
    if plugin not in ("", PLUGIN_NAME):
        return None
    return name if name in ROLES else None


def policy_for(role: str | None, pack: Pack) -> Policy | None:
    """The role's policy; None for the operator's own session and for other agents."""
    if role is None:
        return None
    code = _labelled("source", pack.every("sources")) + _labelled("tests", pack.every("tests"))
    design = tuple(
        ("design data", project.design / name)
        for project in pack.projects
        if project.design
        for name in AUTHORED_DESIGN
    )
    roots = {
        "orchestrator": (),
        "designer": _labelled("specs", tuple(docs / "specs" for docs in pack.every("docs"))) + design,
        "specifier": _labelled("features", pack.every("features")),
        "coder": code,
        "test-reviewer": (),
        "refactorer": code,
        "architect": code,
    }[role]
    scratch = _labelled("scratch", (*pack.every("artifacts"), pack.scratch)) if role != "orchestrator" else ()
    return Policy(role, roots + scratch, read_only_git=role != "orchestrator")


def _labelled(label: str, paths: tuple) -> tuple:
    return tuple((label, path) for path in paths)


def _forbidden(pack: Pack, role: str) -> list:
    """(label, predicate) pairs refused to `role` wherever its roots reach."""
    artifacts = pack.every("artifacts")
    rules = [
        ("Claude Code's configuration or this plugin", lambda path: any(is_under(path, m) for m in pack.meta())),
        (
            "the pack config (only the designer changes its project's specs and subsystems)",
            lambda path: path == pack.config,
        ),
        ("a generated view (render it with arch.py)", lambda path: _generated_view(path, pack)),
        ("an analysis report", lambda path: any(is_under(path, root / ".metrics") for root in artifacts)),
        (
            "a generated acceptance test (run the generator)",
            lambda path: any(is_under(path, root / "acceptance") for root in artifacts),
        ),
        ("the class overlay (write it with arch classes add|remove|annotate)", lambda path: _overlay(path, pack)),
    ]
    if role != "specifier":
        rules.append(("the specifier's features", lambda path: _inside_any(path, pack.every("features"))))
    if role != "designer":
        rules.append(("the designer's docs", lambda path: _inside_any(path, pack.every("docs"))))
        rules.append(("the designer's design data", lambda path: _inside_any(path, pack.every("design"))))
    rules.append(("the pack's harness (changes go upstream)", lambda path: _harness(path, pack)))
    return rules


def _inside_any(path: Path, roots: tuple) -> bool:
    return any(is_under(path, root) for root in roots)


def _generated_view(path: Path, pack: Pack) -> bool:
    return path.suffix == ".html" and _inside_any(path, pack.every("docs"))


def _overlay(path: Path, pack: Pack) -> bool:
    return path.name == "overlay.json" and _inside_any(path, pack.every("design"))


def _harness(path: Path, pack: Pack) -> bool:
    """Inside the pack, but not its scratch (`tmp/`, an artifacts root) and not a project inside it."""
    if not is_under(path, pack.root) or is_under(path, pack.scratch):
        return False
    keep = (
        *pack.every("artifacts"),
        *pack.every("design"),
        *(project.project for project in pack.projects if project.project != pack.root),
    )
    return not any(is_under(path, root) and root != pack.root for root in keep)


def config_change(before: str, after: str) -> str | None:
    """Why `after` is not a designer's change of `before`, or None: only `projects.<p>.specs|subsystems`."""
    try:
        old, new = json.loads(before), json.loads(after)
    except ValueError as error:
        return f"the result is not valid JSON ({error})"
    if not (isinstance(old, dict) and isinstance(new, dict)):
        return "the config must stay a JSON object"
    if _without_design_keys(old) != _without_design_keys(new):
        return "only a project's `specs` and `subsystems` may change; the rest is the operator's wiring"
    return None


def _without_design_keys(config: dict) -> dict:
    projects = config.get("projects")
    if not isinstance(projects, dict):
        return {key: value for key, value in config.items() if key not in DESIGNER_CONFIG_KEYS}
    trimmed = {
        name: {key: value for key, value in entry.items() if key not in DESIGNER_CONFIG_KEYS}
        if isinstance(entry, dict)
        else entry
        for name, entry in projects.items()
    }
    return {**config, "projects": trimmed}
