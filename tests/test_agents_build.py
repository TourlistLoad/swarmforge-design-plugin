"""Agents built from protocol/<role>.md and the constitution, with the operator's model choice."""

import io

from sfd.agents_build import build, render, run


def test_an_agent_holds_the_constitution_its_articles_and_its_role(workspace):
    root = workspace / "swarm-forge-lite"
    text = render("coder", root, {"*": "haiku:max"})
    head = text.split("---")[1]
    assert "model: haiku" in head and "effort: max" in head and "omitClaudeMd: true" in head
    assert "tools: Bash, Read, Edit, Write, Glob, Grep" in head
    assert text.index("# Communication") < text.index("# Engineering") < text.index("The coder role.")


def test_the_orchestrator_cannot_write_and_overrides_win(workspace):
    root = workspace / "swarm-forge-lite"
    text = render("orchestrator", root, {"*": "haiku:max", "orchestrator": "sonnet:high"})
    head = text.split("---")[1]
    assert "model: sonnet" in head and "effort: high" in head
    assert "Write" not in head.split("tools:")[1] and "omitClaudeMd" not in head
    assert len(build(root, {})) == 7


def test_run_writes_then_reports_up_to_date(workspace, tmp_path):
    out = tmp_path / "agents"
    stdout = io.StringIO()
    assert run(["--project", str(workspace), "--out", str(out)], {}, stdout) == 0
    assert len(list(out.glob("*.md"))) == 7
    assert run(["--project", str(workspace), "--out", str(out), "--check"], {}, io.StringIO()) == 0
    assert (
        run(["--project", str(workspace), "--out", str(out), "--check", "--default", "opus:high"], {}, io.StringIO())
        == 1
    )


def test_run_refuses_without_a_pack(tmp_path):
    stdout = io.StringIO()
    assert run(["--project", str(tmp_path)], {}, stdout) == 1 and "no design pack" in stdout.getvalue()


def test_agents_carry_the_tool_guides_and_a_digest_that_shows_staleness(workspace, tmp_path):
    from sfd.agents_build import digest, stale_note

    root = workspace / "swarm-forge-lite"
    (root / "tools/README.md").write_text("# Tools\n\nRun gate.py.")
    text = render("coder", root, {"*": "haiku:max"})
    assert '<reference file="$PACK/tools/README.md">' in text and "Run gate.py." in text
    assert f"<!-- pack digest: {digest(root)} -->" in text
    out = tmp_path / "agents"
    run(["--project", str(workspace), "--out", str(out)], {}, io.StringIO())
    assert stale_note(root, out) == ""
    (root / "protocol/coder.md").write_text("# coder\n\nChanged.")
    assert "sync-agents" in stale_note(root, out)
    assert stale_note(root, tmp_path / "none") == ""
