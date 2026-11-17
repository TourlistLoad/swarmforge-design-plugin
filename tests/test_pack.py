"""Finding the pack and resolving its config the way tools/shared/packconfig.py does."""

import json

from conftest import make_workspace
from sfd.pack import Pack, find_pack


def test_the_local_config_wins_and_each_project_resolves_against_its_own_root(workspace, pack):
    assert pack.config == workspace / "swarm-forge-lite/config/pack.local.json"
    app, svc = pack.projects
    assert (app.name, svc.name, pack.default) == ("app", "svc", "app")
    assert app.project == workspace / "app" and svc.project == workspace / "svc"
    assert app.artifacts == workspace / "swarm-forge-lite/tmp/app"  # the <PACK> token
    assert svc.artifacts == workspace / "swarm-forge-lite/tmp/svc"  # relative to its project
    assert app.design == workspace / "app/design" and svc.design is None
    assert pack.reports == workspace / "swarm-forge-lite/tmp/claude-reports"
    assert pack.problem == ""


def test_pack_project_selects_and_the_default_applies_otherwise(workspace):
    assert Pack.load(workspace, {}).selected.name == "app"
    chosen = Pack.load(workspace, {"PACK_PROJECT": "svc"})
    assert chosen.selected.name == "svc" and chosen.project == workspace / "svc"


def test_swarm_config_wins_then_the_legacy_file(workspace, tmp_path):
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"projects": {"x": {"project_root": "../app", "source_roots": ["src"]}}}))
    assert [p.name for p in Pack.load(workspace, {"SWARM_CONFIG": str(other)}).projects] == ["x"]
    (workspace / "swarm-forge-lite/config/pack.local.json").unlink()
    assert "legacy" in Pack.load(workspace, {}).problem  # the tracked legacy file, pointing nowhere


def test_a_0_1_config_is_one_project(workspace):
    (workspace / "swarm-forge-lite/config/pack.local.json").write_text(
        json.dumps({"project_root": "../app", "source_roots": ["src"], "docs_root": "docs"})
    )
    pack = Pack.load(workspace, {})
    assert [p.name for p in pack.projects] == ["app"] and pack.selected.sources == (workspace / "app/src",)


def test_the_pack_is_found_from_the_workspace_the_pack_and_a_project(workspace):
    root = workspace / "swarm-forge-lite"
    for where in (workspace, root, workspace / "app"):
        assert find_pack(where, {}) == root


def test_no_pack_no_config_and_a_broken_config(workspace, tmp_path_factory):
    assert Pack.load(tmp_path_factory.mktemp("empty"), {}) is None
    config = workspace / "swarm-forge-lite/config"
    (config / "pack.local.json").write_text("{")
    assert "does not parse" in Pack.load(workspace, {}).problem
    (config / "pack.local.json").unlink()
    (config / "pack.json").unlink()
    assert "install" in Pack.load(workspace, {}).problem


def test_every_owner_and_rel(workspace, pack):
    assert pack.every("sources") == (workspace / "app/src", workspace / "svc/server")
    assert pack.owner(workspace / "svc/server/a.py").name == "svc"
    assert pack.owner(workspace / "elsewhere") is None
    assert pack.rel(workspace / "app/src") == "app/src"
    assert make_workspace  # imported for other suites
