"""Each role writes what protocol/README.md › Roles gives it, in every project, and nothing generated."""

import json

import pytest
from sfd.roles import config_change, policy_for, role_of


def refused(role, path, pack):
    return policy_for(role, pack).refusal(path, pack)


@pytest.mark.parametrize(
    ("role", "relative"),
    [
        ("designer", "app/docs/specs/01-labels.md"),
        ("designer", "svc/notes/specs/01-api.md"),
        ("designer", "app/design/runtime.json"),
        ("designer", "app/design/policy.json"),
        ("specifier", "app/tests/features/labels.feature"),
        ("specifier", "svc/checks/features/api.feature"),
        ("coder", "app/src/app/labels.py"),
        ("coder", "svc/server/api.py"),
        ("refactorer", "app/tests/unit/test_labels.py"),
        ("architect", "svc/checks/test_api.py"),
        ("test-reviewer", "swarm-forge-lite/tmp/app/review.md"),
        ("test-reviewer", "swarm-forge-lite/tmp/notes.md"),
    ],
)
def test_a_role_writes_its_own_roots(workspace, pack, role, relative):
    assert refused(role, workspace / relative, pack) is None


@pytest.mark.parametrize(
    ("role", "relative", "why"),
    [
        ("coder", "app/tests/features/labels.feature", "features"),
        ("coder", "svc/checks/features/api.feature", "features"),
        ("coder", "app/docs/specs/01-labels.md", "docs"),
        ("coder", "app/design/runtime.json", "design data"),
        ("designer", "app/src/app/labels.py", "writes specs"),
        ("designer", "app/docs/ARCHITECTURE.html", "generated view"),
        ("designer", "app/docs/README.md", "writes specs"),
        ("designer", "app/design/overlay.json", "class overlay"),
        ("designer", "swarm-forge-lite/architecture/svc/runtime.json", "harness"),
        ("designer", "swarm-forge-lite/config/pack.local.json", "pack config"),
        ("specifier", "app/src/app/labels.py", "writes features"),
        ("test-reviewer", "app/tests/unit/test_labels.py", "writes scratch"),
        ("coder", "swarm-forge-lite/tmp/app/acceptance/test_generated.py", "generated acceptance"),
        ("refactorer", "swarm-forge-lite/tmp/svc/.metrics/crap.edn", "analysis report"),
        ("architect", "swarm-forge-lite/protocol/coder.md", "harness"),
        ("architect", "swarm-forge-lite/PROJECT.md", "harness"),
        ("coder", "app/.claude/settings.json", "configuration"),
        ("orchestrator", "swarm-forge-lite/tmp/notes.md", "nothing"),
    ],
)
def test_a_role_is_refused_what_it_does_not_own(workspace, pack, role, relative, why):
    assert why in refused(role, workspace / relative, pack)


def test_the_designer_changes_only_specs_and_subsystems():
    before = {"default_project": "app", "projects": {"app": {"project_root": "../app", "specs": {}}}}
    specs = json.loads(json.dumps(before))
    specs["projects"]["app"]["specs"] = {"02-x.md": "x"}
    specs["projects"]["app"]["subsystems"] = [{"label": "x", "packages": ["x"]}]
    assert config_change(json.dumps(before), json.dumps(specs)) is None
    root = json.loads(json.dumps(before))
    root["projects"]["app"]["project_root"] = "../elsewhere"
    assert "only a project's" in config_change(json.dumps(before), json.dumps(root))
    assert "not valid JSON" in config_change(json.dumps(before), "{")
    assert "object" in config_change(json.dumps(before), "[]")


def test_role_of_names_only_this_plugin_s_agents():
    assert role_of("swarmforge-design:coder") == "coder"
    assert role_of("coder") == "coder"
    assert role_of("other-plugin:coder") is None
    assert role_of("swarmforge-design:hotfixer") is None
    assert role_of(None) is None


def test_only_the_orchestrator_may_run_more_than_read_only_git(pack):
    assert not policy_for("orchestrator", pack).read_only_git
    assert policy_for("coder", pack).read_only_git
    assert policy_for(None, pack) is None
