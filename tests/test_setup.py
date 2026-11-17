"""`sfd setup`: local settings added and removed exactly, the operator's own values kept."""

import io
import json

from sfd.setup import full_plan, merged, run, unmerged, with_excludes, without_excludes


def test_the_plan_names_the_pack_commands_env_and_edit_roots(pack):
    plan = full_plan(pack)
    assert "Bash(python3 swarm-forge-lite/tools/design/arch.py *)" in plan.allow
    assert "Bash(python3 $PACK/tools/gate.py *)" in plan.allow
    assert not any("update.py apply" in rule or "migrate.py" in rule for rule in plan.allow)
    assert "Bash(python3 tests/acceptance/run_acceptance.py*)" in plan.allow
    assert "Edit(/app/src/**)" in plan.allow and "Edit(/svc/server/**)" in plan.allow
    assert "Edit(/swarm-forge-lite/tmp/app/**)" in plan.allow and "Edit(/app/design/runtime.json)" in plan.allow
    assert "Edit(/app/tests/**)" in plan.allow and "Edit(/app/tests/features/**)" not in plan.allow
    assert plan.env == {"PACK": str(pack.root)}  # two projects: PROJECT depends on PACK_PROJECT


def test_merge_keeps_the_operator_s_values_and_undo_removes_only_ours(pack):
    mine = {"env": {"PACK": "/mine"}, "permissions": {"allow": ["Bash(make)"]}, "model": "opus"}
    plan = full_plan(pack)
    result = merged(mine, plan)
    assert result["env"]["PACK"] == "/mine"
    assert unmerged(result, plan) == {
        "env": {"PACK": "/mine"},
        "permissions": {"allow": ["Bash(make)"]},
        "model": "opus",
    }


def test_excludes_round_trip():
    text = with_excludes("*.pyc\n")
    assert ".claude/settings.local.json" in text and with_excludes(text) == text
    assert without_excludes(text) == "*.pyc\n"


def test_run_writes_and_undoes(workspace):
    (workspace / ".git/info").mkdir(parents=True)
    assert run(["--project", str(workspace)], {}, io.StringIO()) == 0
    settings = json.loads((workspace / ".claude/settings.local.json").read_text())
    assert settings["subagentPromptCacheTtl"] == "1h" and "agent" not in settings
    assert run(["--project", str(workspace), "--undo"], {}, io.StringIO()) == 0
    assert not (workspace / ".claude/settings.local.json").exists()
    assert "swarmforge-design" not in (workspace / ".git/info/exclude").read_text()


def test_one_project_also_exports_project(tmp_path):
    from conftest import make_workspace
    from sfd.pack import Pack

    workspace = make_workspace(tmp_path, {"projects": {"one": {"project_root": "../app", "source_roots": ["src"]}}})
    plan = full_plan(Pack.load(workspace.resolve(), {}))
    assert plan.env["PROJECT"] == str(workspace.resolve() / "app")


def test_run_refuses_a_pack_without_a_config(workspace):
    for name in ("pack.local.json", "pack.json"):
        (workspace / "swarm-forge-lite/config" / name).unlink()
    stdout = io.StringIO()
    assert run(["--project", str(workspace)], {}, stdout) == 1 and "install" in stdout.getvalue()
