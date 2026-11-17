"""The hook entry points end to end: stdin payload in, hook answer out."""

import io
import json

from sfd.cli import main


def call(name, payload, environ):
    stdout = io.StringIO()
    assert main([name], io.StringIO(json.dumps(payload)), stdout, environ) == 0
    text = stdout.getvalue().strip()
    return json.loads(text) if text.startswith("{") else text


def test_session_start_and_subagent_start(workspace):
    env = {"CLAUDE_PROJECT_DIR": str(workspace)}
    answer = call("context", {"hook_event_name": "SessionStart"}, env)
    assert "swarmforge-design" in answer["hookSpecificOutput"]["additionalContext"]
    answer = call("context", {"hook_event_name": "SubagentStart", "agent_type": "swarmforge-design:coder"}, env)
    assert "`coder` role" in answer["hookSpecificOutput"]["additionalContext"]


def test_report_blocks_once_then_lets_go(workspace):
    env = {"CLAUDE_PROJECT_DIR": str(workspace)}
    stop = {"agent_type": "swarmforge-design:coder", "last_assistant_message": "done"}
    assert call("report", stop, env)["decision"] == "block"
    assert call("report", {**stop, "stop_hook_active": True}, env) == ""
    assert (workspace / "swarm-forge-lite/tmp/claude-reports/coder.md").is_file()


def test_no_pack_means_no_opinion_and_a_status_line_note(tmp_path):
    env = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
    assert call("guard", {"tool_name": "Bash", "tool_input": {"command": "git push"}}, env) == ""
    assert "no design pack" in call("statusline", {}, env)


def test_a_broken_payload_never_breaks_the_session(workspace):
    stdout = io.StringIO()
    assert main(["guard"], io.StringIO("{"), stdout, {"CLAUDE_PROJECT_DIR": str(workspace)}) == 0
    assert stdout.getvalue() == ""


def test_statusline_and_subagent_rows(workspace):
    env = {"CLAUDE_PROJECT_DIR": str(workspace)}
    assert "design pack idle" in call("statusline", {"model": {"display_name": "Haiku"}}, env)
    tasks = {
        "tasks": [
            {"id": "1", "agentType": "swarmforge-design:coder", "model": "claude-haiku-5-5", "effort": "max"},
            {"id": "2", "agentType": "Explore"},
        ]
    }
    row = call("subagentstatus", tasks, env)
    assert row["content"].startswith("coder · haiku max")
