"""SubagentStop: check that a role's report is a report, and keep it.

The pack has no answer template: "End with a short report in plain prose … No template and no header
tokens" (communication.md › Reporting). What it does require is checkable: each command that proves the
work, with the exit status it returned, unless the role says it is blocked; and the test-reviewer's
verdict. A report that misses them is sent back once. Every report is saved under the artifacts root
(`reports/<role>.md`, plus `progress.json` and `history.jsonl`) for the orchestrator's resume and the
status line; the artifacts root is scratch, outside the project's git.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

EXIT = re.compile(
    r"\bexit(?:ed)?(?:\s+(?:status|code))?\s*(?:[:=]|with|of)?\s*\d+|=>\s*exit\b|\bexit\s+0\b", re.IGNORECASE
)
BLOCKED = re.compile(r"\bblocked\b|\bcannot proceed\b|\bneed(?:s)? (?:a|the) decision\b", re.IGNORECASE)
NOT_BLOCKED = re.compile(
    r"\b(?:nothing|not|never|no longer|un)\s*(?:is\s+|was\s+|has\s+been\s+)?blocked\b|\bno\s+blocker", re.IGNORECASE
)
VERDICT = re.compile(r"\b(accept(?:ed)?|reject(?:ed)?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Report:
    role: str
    text: str

    @property
    def blocked(self) -> bool:
        return bool(BLOCKED.search(NOT_BLOCKED.sub("", self.text)))

    @property
    def verdict(self) -> str:
        found = VERDICT.findall(self.text)
        return found[-1].lower().replace("ed", "") if found else ""

    @property
    def outcome(self) -> str:
        if self.role == "test-reviewer" and self.verdict:
            return self.verdict
        return "blocked" if self.blocked else "done"


def problems(report: Report) -> list:
    """What the report misses, as fix instructions; empty when it is a report."""
    found = []
    if not report.text.strip():
        return ["the report is empty"]
    if not report.blocked and not EXIT.search(report.text):
        found.append(
            "name each command you ran with its exit status (`… exit 0`), or say in one sentence "
            "that you are blocked and on what"
        )
    if report.role == "test-reviewer" and not report.verdict:
        found.append("give the verdict in one sentence: accepted, or rejected with the count of findings")
    return found


def block_reason(report: Report, found: list) -> str:
    return (
        f"Report check for the {report.role}: {'; '.join(found)}. End with your Report section "
        "(communication.md › Reporting): what you changed by file, each command with its exit status, and "
        "what you could not do. Plain prose, no template."
    )


def save(report: Report, found: list, reports: Path, at: str, agent_id: str = "") -> Path:
    reports.mkdir(parents=True, exist_ok=True)
    message = reports / f"{report.role}.md"
    message.write_text(report.text.rstrip() + "\n")
    entry = {
        "role": report.role,
        "outcome": report.outcome,
        "ok": not found,
        "problems": found,
        "at": at,
        "agent_id": agent_id,
        "message": str(message),
    }
    (reports / "progress.json").write_text(json.dumps(entry, indent=2) + "\n")
    with (reports / "history.jsonl").open("a", encoding="utf-8") as history:
        history.write(json.dumps(entry) + "\n")
    return message
