"""The PreToolUse guard: ownership, git, mutation, scans, and the sequential chain."""

import pytest
from sfd.guard import judge


def payload(tool, tool_input, agent=None, cwd=None):
    return {"tool_name": tool, "tool_input": tool_input, "agent_type": agent, "cwd": str(cwd) if cwd else None}


def test_edits_follow_the_role_table(workspace, pack):
    feature = str(workspace / "app/tests/features/a.feature")
    assert judge(payload("Write", {"file_path": feature}, "swarmforge-design:specifier"), pack).allowed
    verdict = judge(payload("Edit", {"file_path": feature}, "swarmforge-design:coder"), pack)
    assert verdict.decision == "deny" and "specifier's features" in verdict.reason


def test_the_operator_s_session_writes_anything(workspace, pack):
    target = str(workspace / "swarm-forge-lite/protocol/coder.md")
    assert judge(payload("Write", {"file_path": target}), pack).as_output() is None


def test_shell_writes_are_held_to_the_same_table(workspace, pack):
    line = f"echo x > {workspace}/app/docs/specs/a.md"
    assert judge(payload("Bash", {"command": line}, "swarmforge-design:coder", workspace), pack).decision == "deny"


@pytest.mark.parametrize(
    "line", ["bb --config tools/shared/aps/bb.edn gherkin-mutator x.json", "pip install mutmut", "mutmut run"]
)
def test_mutation_testing_is_refused(workspace, pack, line):
    verdict = judge(payload("Bash", {"command": line}, "swarmforge-design:coder", workspace / "swarm-forge-lite"), pack)
    assert verdict.decision == "deny" and "Mutation" in verdict.reason


def test_git_roles_read_the_orchestrator_never_commits_the_operator_is_asked(workspace, pack):
    def decide(line, agent):
        return judge(payload("Bash", {"command": line}, agent, workspace), pack).decision

    assert decide("git commit -m x", "swarmforge-design:coder") == "deny"
    assert decide("git -C app checkout -b x", "swarmforge-design:architect") == "deny"
    assert decide("git commit -m x", "swarmforge-design:orchestrator") == "deny"
    assert decide("git checkout main", "swarmforge-design:orchestrator") == "ask"
    assert decide("git push", None) == "ask"
    assert decide("git status", "swarmforge-design:coder") == "allow"


def test_scans_outside_the_workspace_are_refused(workspace, pack):
    assert judge(payload("Bash", {"command": "find ~ -name x"}, None, workspace), pack).decision == "deny"
    assert judge(payload("Bash", {"command": "find / -name x"}, None, workspace), pack).decision == "deny"


def test_a_role_dispatch_runs_in_the_foreground(pack):
    tool_input = {"subagent_type": "swarmforge-design:coder", "prompt": "brief"}
    output = judge(payload("Agent", tool_input, "swarmforge-design:orchestrator"), pack).as_output()
    assert output["hookSpecificOutput"]["updatedInput"]["run_in_background"] is False
    already = {**tool_input, "run_in_background": False}
    assert judge(payload("Agent", already, "swarmforge-design:orchestrator"), pack).as_output() is None


def test_the_orchestrator_dispatches_the_pack_s_roles_only(pack):
    for target in ("general-purpose", "swarmforge-design:orchestrator", ""):
        verdict = judge(payload("Agent", {"subagent_type": target}, "swarmforge-design:orchestrator"), pack)
        assert verdict.decision == "deny"
    worktree = {"subagent_type": "swarmforge-design:coder", "isolation": "worktree"}
    assert judge(payload("Agent", worktree, "swarmforge-design:orchestrator"), pack).decision == "ask"


def test_a_read_only_line_is_allowed_explicitly(workspace, pack):
    line = "ls $PACK/tmp && cat $PACK/protocol/coder.md | head -5"
    output = judge(payload("Bash", {"command": line}, "swarmforge-design:coder", workspace), pack).as_output()
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def decide(line, agent, workspace, pack):
    return judge(payload("Bash", {"command": line}, agent, workspace), pack).decision


@pytest.mark.parametrize(
    "line",
    [
        "python3 $PACK/tools/update.py apply --yes",
        "python3 $PACK/tools/migrate.py",
        "python3 $PACK/tools/install.py apply --answers a.json",
    ],
)
def test_the_lifecycle_is_the_operator_s(workspace, pack, line):
    assert decide(line, "swarmforge-design:architect", workspace, pack) == "deny"
    assert decide(line, "swarmforge-design:orchestrator", workspace, pack) == "ask"
    assert decide(line, None, workspace, pack) == "ask"


def test_read_only_lifecycle_and_gates_run_unasked(workspace, pack):
    for line in (
        "python3 $PACK/tools/update.py check",
        "python3 $PACK/tools/migrate.py --dry-run",
        "PACK_PROJECT=svc python3 $PACK/tools/doctor.py",
        "PACK_PROJECT=app python3 $PACK/tools/gate.py unit",
        "python3 $PACK/tools/install.py apply --answers a.json --dry-run",
    ):
        verdict = judge(payload("Bash", {"command": line}, "swarmforge-design:coder", workspace), pack)
        assert verdict.explicit, line


def test_the_overlay_and_policy_are_the_designer_s(workspace, pack):
    add = "PACK_PROJECT=app python3 $PACK/tools/design/arch.py classes add node Labels --subsystem labels"
    assert decide(add, "swarmforge-design:coder", workspace, pack) == "deny"
    assert judge(payload("Bash", {"command": add}, "swarmforge-design:designer", workspace), pack).explicit
    assert decide("python3 $PACK/tools/umlview init", "swarmforge-design:architect", workspace, pack) == "deny"
    assert decide("python3 $PACK/tools/umlview policy show", "swarmforge-design:architect", workspace, pack) == "allow"


def test_the_designer_edits_only_its_specs_and_subsystems_in_the_config(workspace, pack):
    config = workspace / "swarm-forge-lite/config/pack.local.json"
    text = config.read_text()
    specs = text.replace('"specs": {"01-labels.md": "labels"}', '"specs": {"01-labels.md": "labels", "02-x.md": "x"}')
    good = {"file_path": str(config), "old_string": text, "new_string": specs}
    assert judge(payload("Edit", good, "swarmforge-design:designer"), pack).allowed
    root = {"file_path": str(config), "old_string": '"../svc"', "new_string": '"../other"'}
    assert judge(payload("Edit", root, "swarmforge-design:designer"), pack).decision == "deny"
    stale = {"file_path": str(config), "old_string": "not in the file", "new_string": "x"}
    assert "does not apply" in judge(payload("Edit", stale, "swarmforge-design:designer"), pack).reason
    assert (
        judge(
            payload("Write", {"file_path": str(config), "content": "{}"}, "swarmforge-design:designer"), pack
        ).decision
        == "deny"
    )
    multi = {"file_path": str(config), "edits": [{"old_string": text, "new_string": specs}]}
    assert judge(payload("MultiEdit", multi, "swarmforge-design:designer"), pack).allowed
    assert judge(payload("Edit", good, "swarmforge-design:coder"), pack).decision == "deny"
    shell = f"sed -i s/labels/x/ {config}"
    assert decide(shell, "swarmforge-design:designer", workspace, pack) == "deny"


def test_a_shell_write_follows_the_line_s_variables_and_cd(workspace, pack):
    art = 'ART=$PACK/tmp/app; rm -f "$ART"/labels.*; PACK=x'
    assert judge(payload("Bash", {"command": art}, "swarmforge-design:coder", workspace), pack).allowed
    into_docs = "D=$PACK/../app/docs; echo x > $D/specs/a.md"
    assert decide(into_docs, "swarmforge-design:coder", workspace, pack) == "deny"
    relative = "cd app/docs && echo x > specs/a.md"
    assert decide(relative, "swarmforge-design:coder", workspace, pack) == "deny"
    unseen = "rm -f $NOT_EXPORTED/x"
    assert judge(payload("Bash", {"command": unseen}, "swarmforge-design:coder", workspace), pack).as_output() is None


def test_a_role_clears_a_stale_report_but_never_writes_one(workspace, pack):
    clear = "rm -f $PACK/tmp/app/.metrics/dry.edn $PACK/tmp/app/acceptance/test_x.py"
    verdict = judge(payload("Bash", {"command": clear}, "swarmforge-design:refactorer", workspace), pack)
    assert verdict.allowed and verdict.explicit
    forge = "echo '{}' > $PACK/tmp/app/.metrics/dry.edn"
    assert decide(forge, "swarmforge-design:refactorer", workspace, pack) == "deny"
    assert decide(clear, "swarmforge-design:orchestrator", workspace, pack) == "deny"


def test_the_formatter_runs_unasked_on_code_but_never_on_another_owner_s_files(workspace, pack):
    fmt = "cd app && ruff format src/app tests/unit"
    assert judge(payload("Bash", {"command": fmt}, "swarmforge-design:coder", workspace), pack).explicit
    assert decide("cd app && ruff format docs", "swarmforge-design:coder", workspace, pack) == "deny"
    assert decide(fmt, "swarmforge-design:specifier", workspace, pack) == "deny"
    assert not judge(payload("Bash", {"command": fmt}, "swarmforge-design:test-reviewer", workspace), pack).explicit


def test_cache_folders_and_timed_subshells(workspace, pack):
    line = "cd app && rm -rf tests/__pycache__ .pytest_cache && time (python3 -m pytest -q tests/unit)"
    assert judge(payload("Bash", {"command": line}, "swarmforge-design:coder", workspace), pack).explicit
    assert not judge(
        payload("Bash", {"command": "rm -rf app/src"}, "swarmforge-design:coder", workspace), pack
    ).explicit
