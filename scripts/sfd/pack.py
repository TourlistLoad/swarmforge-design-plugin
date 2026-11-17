"""Find the design-boosted pack and resolve its config, the one place its paths live.

A pack is a folder with `constitution.md` and `protocol/orchestrator.md`. Its config follows the pack's own
rule (`tools/shared/packconfig.py`): `SWARM_CONFIG`, then `config/pack.local.json`, then the tracked legacy
`config/pack.json`; a value may carry the `<PACK>` token. One pack serves several projects (`projects`
map, `PACK_PROJECT` selects one, else `default_project`); a 0.1 config with no `projects` map is one
project. Every path follows `tools/README.md`: `project_root` resolves against the pack, every other path
against that project. Claude Code may run in the folder that holds the pack, in the pack, or in a project
with the pack beside it. Where no pack is found, every hook stays silent.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PACK_DIR_NAME = "swarm-forge-lite"
PACK_ENV = "SWARM_PACK"
CONFIG_ENV = "SWARM_CONFIG"
TOKEN = "<PACK>"
META_NAMES = (".claude", "CLAUDE.md", "CLAUDE.local.md")
CONFIG_NAMES = ("pack.local.json", "pack.json")


def is_pack(path: Path) -> bool:
    return all((path / name).is_file() for name in ("constitution.md", "protocol/orchestrator.md"))


def find_pack(where: Path, environ) -> Path | None:
    """`SWARM_PACK`, else `<where>/swarm-forge-lite`, `<where>` itself, a child, or a sibling of `<where>`."""
    chosen = environ.get(PACK_ENV)
    candidates = [Path(chosen).expanduser()] if chosen else _candidates(Path(where))
    for candidate in candidates:
        if is_pack(candidate):
            return candidate.resolve()
    return None


def config_path(root: Path, environ) -> Path | None:
    """The config this run uses, in the pack's own precedence order."""
    requested = str(environ.get(CONFIG_ENV) or "").strip()
    if requested:
        return Path(requested).expanduser().resolve()
    return next((root / "config" / name for name in CONFIG_NAMES if (root / "config" / name).is_file()), None)


def _candidates(where: Path) -> list:
    return [where / PACK_DIR_NAME, where, *_children(where), where.parent / PACK_DIR_NAME]


def _children(where: Path) -> list:
    try:
        return sorted(child for child in where.iterdir() if child.is_dir() and not child.name.startswith("."))
    except OSError:
        return []


def is_under(path: Path, root: Path | None) -> bool:
    return root is not None and (path == root or root in path.parents)


@dataclass(frozen=True)
class Project:
    """One entry of the `projects` map, every path absolute."""

    name: str
    project: Path
    sources: tuple = ()
    tests: tuple = ()
    unit: Path | None = None
    lint: Path | None = None
    features: Path | None = None
    artifacts: Path | None = None
    docs: Path | None = None
    design: Path | None = None  # `<PROJECT>/<design_root>`; None: the legacy `<PACK>/architecture/<name>/`
    acceptance: str = ""
    problem: str = ""

    @classmethod
    def from_entry(cls, name: str, root: Path, entry: dict) -> Project:
        project = _resolve(root, entry.get("project_root", ".."))

        def under(value):
            return _resolve(project, value) if value else None

        problem = (
            "" if project.is_dir() else f"project {name}: project_root {entry.get('project_root')!r} is not a folder"
        )
        return cls(
            name=name,
            project=project,
            sources=tuple(under(value) for value in entry.get("source_roots") or ()),
            tests=tuple(under(value) for value in entry.get("test_paths") or ()),
            unit=under(entry.get("unit_paths")),
            lint=under(entry.get("lint_paths")),
            features=under(entry.get("features")),
            artifacts=under(entry.get("artifacts_root") or "tmp"),
            docs=under(entry.get("docs_root") or "docs"),
            design=under(entry.get("design_root")),
            acceptance=str(entry.get("acceptance_command") or ""),
            problem=problem,
        )

    def rows(self) -> list:
        rows = [("PROJECT", self.project)]
        rows += [("SOURCE", root) for root in self.sources] + [("TESTS", root) for root in self.tests]
        rows += [("UNIT", self.unit), ("LINT", self.lint), ("FEATURES", self.features), ("DOCS", self.docs)]
        rows += [("DESIGN", self.design), ("ARTIFACTS", self.artifacts)]
        return [(label, path) for label, path in rows if path is not None]


@dataclass(frozen=True)
class Pack:
    """The pack, its config file, and every project the config names."""

    where: Path  # the folder Claude Code runs in
    root: Path  # $PACK
    config: Path | None = None
    projects: tuple = ()
    default: str = ""
    selector: str = "PACK_PROJECT"
    problem: str = ""  # why the config does not resolve, else ""
    environ: dict = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def load(cls, where: Path, environ=None) -> Pack | None:
        environ = dict(os.environ if environ is None else environ)
        root = find_pack(Path(where), environ)
        if root is None:
            return None
        where = Path(where).resolve()
        config = config_path(root, environ)
        if config is None:
            return cls(
                where,
                root,
                problem="no pack config: run tools/install.py (/swarmforge-design:install)",
                environ=environ,
            )
        try:
            data = _expand(json.loads(config.read_text(encoding="utf-8")), root)
        except (OSError, ValueError) as error:
            return cls(where, root, config, problem=f"{config.name} does not parse: {error}", environ=environ)
        return cls.from_config(where, root, data, config, environ)

    @classmethod
    def from_config(cls, where: Path, root: Path, data: dict, config: Path | None = None, environ=None) -> Pack:
        if not isinstance(data.get("projects"), dict):  # the 0.1 shape: one project, no map
            name = Path(str(data.get("project_root", "project"))).name or "project"
            data = {"default_project": name, "projects": {name: data}}
        projects = tuple(Project.from_entry(name, root, entry) for name, entry in data["projects"].items())
        default = str(data.get("default_project") or (projects[0].name if len(projects) == 1 else ""))
        problems = [project.problem for project in projects if project.problem]
        if default and default not in {project.name for project in projects}:
            problems.append(f"default_project {default!r} is not configured")
        return cls(
            where,
            root,
            config,
            projects,
            default,
            str(data.get("selector_env") or "PACK_PROJECT"),
            "; ".join(problems),
            dict(environ or {}),
        )

    # -- selection --------------------------------------------------------------------------------------

    @property
    def selected(self) -> Project | None:
        """The project `PACK_PROJECT` names, else `default_project`; None when neither resolves."""
        wanted = str(self.environ.get(self.selector) or "").strip() or self.default
        return next((project for project in self.projects if project.name == wanted), None)

    @property
    def project(self) -> Path:
        chosen = self.selected
        return chosen.project if chosen else self.root.parent

    def every(self, attribute: str) -> tuple:
        """One root kind across every project (`sources` and `tests` flattened), without None."""
        found = []
        for project in self.projects:
            value = getattr(project, attribute)
            found.extend(value if isinstance(value, tuple) else [value])
        return tuple(dict.fromkeys(path for path in found if path is not None))

    def owner(self, path: Path) -> Project | None:
        """The project whose tree holds `path` (the deepest project root wins)."""
        holding = [project for project in self.projects if is_under(path, project.project)]
        return max(holding, key=lambda project: len(project.project.parts), default=None)

    # -- the pack's own places --------------------------------------------------------------------------

    @property
    def architecture(self) -> Path:
        """The legacy, read-only design location (`architecture/<project>/`)."""
        return self.root / "architecture"

    @property
    def scratch(self) -> Path:
        """`<PACK>/tmp`: gitignored scratch the pack already keeps."""
        return self.root / "tmp"

    @property
    def reports(self) -> Path:
        """Where the plugin keeps each role's last report."""
        return self.scratch / "claude-reports"

    @property
    def workspace_roots(self) -> tuple:
        """Where a session may read and run commands: here, the pack, and every project."""
        return tuple(dict.fromkeys((self.where, self.root, *(project.project for project in self.projects))))

    def meta(self) -> tuple:
        """Agent configuration nobody but the operator edits: Claude Code's own files and this plugin."""
        bases = dict.fromkeys((self.where, *(project.project for project in self.projects)))
        return tuple(base / name for base in bases for name in META_NAMES) + (PLUGIN_ROOT, Path.home() / ".claude")

    def rel(self, path: Path) -> str:
        """`path` relative to where Claude Code runs, when it is inside; else absolute."""
        try:
            return str(Path(path).relative_to(self.where)) or "."
        except ValueError:
            return str(path)


def _expand(value, root: Path):
    """`<PACK>` replaced in every string, recursively, as packconfig.expand does."""
    if isinstance(value, str):
        return value.replace(TOKEN, str(root))
    if isinstance(value, list):
        return [_expand(item, root) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item, root) for key, item in value.items()}
    return value


def _resolve(base: Path, value: str) -> Path:
    path = Path(str(value)).expanduser()
    return Path(os.path.normpath(path if path.is_absolute() else base / path))
