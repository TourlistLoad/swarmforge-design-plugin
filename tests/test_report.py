"""The SubagentStop check: exit statuses (or blocked), the test-reviewer's verdict, and the saved report."""

import json

from sfd.report import Report, problems, save


def test_a_report_names_its_commands_with_exit_statuses():
    assert problems(Report("coder", "Changed src/a.py. `python3 -m pytest -q` exit 0.")) == []
    assert problems(Report("coder", "Ran the tests; all green"))
    assert problems(Report("coder", "I changed things.")) and problems(Report("coder", "   "))


def test_a_blocked_report_needs_no_exit_status():
    report = Report("coder", "Blocked: the guard refused docs/specs/a.md; the designer owns it.")
    assert problems(report) == [] and report.outcome == "blocked"


def test_the_test_reviewer_gives_a_verdict():
    assert problems(Report("test-reviewer", "pytest exit 0. Nothing more."))
    accepted = Report("test-reviewer", "pytest exit 0. Accepted.")
    assert problems(accepted) == [] and accepted.outcome == "accept"
    assert Report("test-reviewer", "exit 0; rejected with 2 findings").outcome == "reject"


def test_save_keeps_the_report_the_progress_and_the_history(tmp_path):
    reports = tmp_path / "reports"
    save(Report("coder", "exit 0"), [], reports, "t1", "a1")
    save(Report("architect", "exit 1"), ["x"], reports, "t2")
    assert (reports / "coder.md").read_text() == "exit 0\n"
    progress = json.loads((reports / "progress.json").read_text())
    assert progress["role"] == "architect" and progress["ok"] is False
    assert len((reports / "history.jsonl").read_text().splitlines()) == 2


def test_a_report_that_says_nothing_blocked_it_is_done():
    report = Report("coder", "`pytest` exit 0. Nothing blocked me, and I need no decision.")
    assert report.outcome == "done"
    assert Report("coder", "exit 0. I was not blocked.").outcome == "done"
