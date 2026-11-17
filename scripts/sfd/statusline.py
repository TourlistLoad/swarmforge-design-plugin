"""The status lines: the last role report next to the model, and one row per role in the agent panel."""

from __future__ import annotations

import json
import time
from pathlib import Path

ICON = "⚒"
PREFIX = "swarmforge-design:"


def load_progress(reports: Path) -> dict | None:
    try:
        return json.loads((reports / "progress.json").read_text())
    except (OSError, ValueError):
        return None


def render(session: dict, progress: dict | None) -> str:
    """`⚒ <role> <outcome> │ <model> · ctx <n>%`."""
    if not progress:
        state = "design pack idle"
    else:
        state = f"{progress.get('role', '?')} {progress.get('outcome', '')}".rstrip()
        state += "" if progress.get("ok", True) else " ⚠ report"
    model = (session.get("model") or {}).get("display_name") or "model ?"
    used = (session.get("context_window") or {}).get("used_percentage")
    return f"{ICON} {state} │ {model if used is None else f'{model} · ctx {round(used)}%'}"


def subagent_rows(payload: dict, now_ms: float | None = None) -> str:
    """subagentStatusLine: `coder · haiku max · 2m14s · <label>` for each role row; other rows keep the default."""
    now = time.time() * 1000 if now_ms is None else now_ms
    lines = []
    for task in payload.get("tasks") or []:
        agent = str(task.get("agentType") or "")
        if not agent.startswith(PREFIX) or "id" not in task:
            continue
        parts = [agent[len(PREFIX) :], _model_effort(task), _elapsed(task, now), str(task.get("label") or "")]
        lines.append(json.dumps({"id": task["id"], "content": " · ".join(part for part in parts if part)}))
    return "\n".join(lines)


def _model_effort(task: dict) -> str:
    model = str(task.get("model") or "")
    family = next((name for name in ("opus", "sonnet", "haiku", "fable", "mythos") if name in model), model)
    effort = task.get("effort")
    return f"{family} {effort}".strip() if effort else family


def _elapsed(task: dict, now: float) -> str:
    start = task.get("startTime")
    if not isinstance(start, (int, float)):
        return ""
    seconds = max(0, int((now - start) / 1000))
    return f"{seconds // 60}m{seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"
