"""Shared fixtures: the plugin's `scripts/` on the path, and a fake design pack beside a fake project."""

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sfd.pack import Pack
from sfd.roles import ROLES

CONFIG = {
    "selector_env": "PACK_PROJECT",
    "default_project": "app",
    "projects": {
        "app": {
            "project_root": "../app",
            "source_roots": ["src"],
            "test_paths": ["tests"],
            "unit_paths": "tests/unit",
            "lint_paths": ".",
            "features": "tests/features",
            "docs_root": "docs",
            "design_root": "design",
            "specs": {"01-labels.md": "labels"},
            "subsystems": [{"number": "01", "label": "labels", "packages": ["labels"]}],
            "acceptance_command": "python3 tests/acceptance/run_acceptance.py",
            "artifacts_root": "<PACK>/tmp/app",
        },
        "svc": {
            "project_root": "../svc",
            "source_roots": ["server"],
            "test_paths": ["checks"],
            "features": "checks/features",
            "docs_root": "notes",
            "acceptance_command": "PACK_PROJECT=svc python3 checks/run_acceptance.py",
            "artifacts_root": "../swarm-forge-lite/tmp/svc",
        },
    },
}
CONSTITUTION = """# Constitution

Read these articles:

- `constitution/articles/communication.md`
- `constitution/articles/engineering.md`
"""


def make_workspace(base: Path, config: dict | None = None) -> Path:
    """`<base>/swarm-forge-lite` (the pack) beside `<base>/app` (the project)."""
    pack = base / "swarm-forge-lite"
    for folder in (
        "protocol",
        "config",
        "constitution/articles",
        "tools/design",
        "tools/shared/aps",
        "architecture/svc",
        "tmp",
    ):
        (pack / folder).mkdir(parents=True, exist_ok=True)
    (pack / "constitution.md").write_text(CONSTITUTION)
    (pack / "constitution/articles/communication.md").write_text("# Communication\n\nReport in prose.")
    (pack / "constitution/articles/engineering.md").write_text("# Engineering\n\nNo mutation testing.")
    for role in ROLES:
        (pack / "protocol" / f"{role}.md").write_text(f"# {role}\n\nThe {role} role.")
    (pack / "config/pack.local.json").write_text(json.dumps(config or CONFIG))
    (pack / "config/pack.json").write_text(json.dumps({"projects": {"legacy": {"project_root": "../nowhere"}}}))
    (pack / "tools/design/arch.py").write_text("")
    (pack / "tools/shared/gherkin-parser").write_text("")
    (pack / "tools/shared/aps/bb.edn").write_text("{}")
    for tool in ("gate.py", "doctor.py", "install.py", "update.py", "migrate.py"):
        (pack / "tools" / tool).write_text("")
    (pack / "architecture/svc/runtime.json").write_text("{}")
    (pack / "PROJECT.md").write_text("# Project\n\nThe app runs on a laptop; svc on a Jetson.")
    app = base / "app"
    for folder in ("src/app", "tests/unit", "tests/features", "tests/acceptance", "docs/specs", "design"):
        (app / folder).mkdir(parents=True, exist_ok=True)
    for folder in ("server", "checks/features", "notes/specs"):
        (base / "svc" / folder).mkdir(parents=True, exist_ok=True)
    return base


@pytest.fixture
def workspace(tmp_path) -> Path:
    return make_workspace(tmp_path).resolve()


@pytest.fixture
def pack(workspace) -> Pack:
    """The pack as a session sees it after `/swarmforge-design:setup`: PACK exported."""
    return Pack.load(workspace, {"PACK": str(workspace / "swarm-forge-lite")})
