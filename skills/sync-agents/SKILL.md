---
name: sync-agents
description: Rebuild this plugin's role agents from the pack's protocol/*.md and constitution after a pack update, or change a role's model. Only when the operator asks.
argument-hint: "[--check] [--default MODEL:EFFORT] [--model ROLE=MODEL:EFFORT ...]"
disable-model-invocation: true
allowed-tools:
  - Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sfd" sync-agents *)
  - Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sfd" sync-agents)
---

Run exactly: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sfd" sync-agents $ARGUMENTS`

Report the roles it rebuilt. If it wrote any, tell the operator to run `/reload-plugins`. The default model of
every role is Haiku 5.5 at medium effort; `--model architect=opus:high` changes one role, `--default sonnet:high`
changes the rest.
