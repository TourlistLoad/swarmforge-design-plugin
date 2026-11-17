"""The pack's own commands that write, by what they write (tools/README.md › Pack plumbing, Design surface).

Every other command under `<PACK>/tools/` reads or writes scratch only: `doctor.py`, `gate.py`, `arch.py
env|ls|show|deps|validate|diff|render`, `install.py inspect`, `update.py check|trial`, `umlview
scan|validate|render|ls|show`, the Gherkin parser. These change something the operator or one role owns:

- `lifecycle`: `install.py apply`, `update.py apply`, `migrate.py` (without `--dry-run`): the harness and
  its wiring, the operator's call ("`apply` only on an explicit yes").
- `overlay`: `arch.py classes add|remove|annotate`: the designer's class overlay.
- `policy`: `umlview init` and `umlview policy <edit>`: the designer's dependency policy.
"""

from __future__ import annotations

OVERLAY_VERBS = frozenset({"add", "remove", "annotate"})
POLICY_READS = frozenset({"show"})


def classify(program: str, args: tuple) -> str | None:
    """`lifecycle`, `overlay`, `policy`, or None for a command that only reads or writes scratch."""
    words = [arg for arg in args if not arg.startswith("-")]
    dry = "--dry-run" in args
    if program == "update.py":
        return "lifecycle" if words[:1] == ["apply"] else None
    if program == "install.py":
        return "lifecycle" if words[:1] == ["apply"] and not dry else None
    if program == "migrate.py":
        return None if dry else "lifecycle"
    if program == "arch.py":
        return "overlay" if words[:1] == ["classes"] and words[1:2] and words[1] in OVERLAY_VERBS else None
    if program == "umlview":
        if words[:1] == ["init"]:
            return "policy"
        if words[:1] == ["policy"] and not (words[1:2] and words[1] in POLICY_READS):
            return "policy"
    return None


OWNER = {"overlay": "designer", "policy": "designer"}
