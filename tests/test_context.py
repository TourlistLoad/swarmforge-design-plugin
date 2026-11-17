"""Session and subagent context: resolved paths, the mapping, and the hook cap."""

from sfd.context import CAP, fit, session_context, subagent_context


def test_the_operator_s_session_gets_the_mapping_and_paths(workspace, pack):
    text = session_context(pack, agent=False, session_id="s1")
    assert "Claude Code" in text and str(pack.project) in text and "session id: s1" in text
    assert "pack.local.json" in text and "PACK_PROJECT selects" in text
    assert "/swarmforge-design:setup" in text
    assert "Entry points" not in session_context(pack, agent=True)


def test_a_role_gets_its_write_scope_every_project_and_project_md(workspace, pack):
    text = subagent_context("specifier", pack)
    assert "features" in text and str(workspace / "svc/checks/features") in text
    assert "app (default)" in text and "legacy" in text and "Jetson" in text


def test_a_missing_project_md_is_named(workspace, pack):
    (workspace / "swarm-forge-lite/PROJECT.md").unlink()
    assert "does not exist yet" in subagent_context("coder", pack)


def test_the_last_report_is_named(pack):
    pack.reports.mkdir(parents=True)
    (pack.reports / "progress.json").write_text('{"role": "coder"}')
    assert '"role": "coder"' in session_context(pack, agent=True)


def test_text_stays_under_the_cap():
    assert len(fit("x" * 20_000)) <= CAP
    assert fit("short") == "short"
