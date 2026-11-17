---
name: setup
description: Write this workspace's local Claude Code settings for the design pack — allow rules for the commands of tools/README.md and the roots the roles write, PACK for every shell command (and PROJECT when there is one project), the status line, the 1-hour subagent cache. Only when the operator asks. Pass --undo to remove them.
argument-hint: "[--dry-run] [--undo] [--no-permissions] [--no-env] [--no-statusline] [--no-cache-ttl] [--default-agent]"
disable-model-invocation: true
allowed-tools:
  - Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sfd" setup *)
  - Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sfd" setup)
---

Run exactly: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sfd" setup $ARGUMENTS`

Report what it changed, in one short list. The settings take effect in the next session (restart Claude Code,
or `/reload-plugins` for the agents). Nothing tracked by git changes: the file is `.claude/settings.local.json`.
