# swarmforge-design 1.1: the SwarmForge Lite design pack for Claude Code

A Claude Code plugin that runs the [dsh-swarmforge-design-boosted](https://github.com/bananaback/swarm-forge-lite-design-boosted/tree/dsh-swarmforge-design-boosted)
pack, **version 0.2.0** (built and tested against `89b9d3a`; a 0.1 pack at `ddb16ca` still loads). The pack
is instructions only: seven roles, one at a time per project, orchestrator → designer → specifier → coder →
test-reviewer → refactorer → architect, with the chains of `protocol/orchestrator.md`.

The plugin **changes no file in the pack's repository**. It ships no `CLAUDE.md` and no `.claude/` files.
The pack's `constitution.md`, `constitution/articles/` and `protocol/<role>.md` stay the single source;
`agents/` is built from them.

This folder is both the plugin and a one-plugin marketplace.

## Install (inside Claude Code)

Unpack this folder somewhere you keep, e.g. `~/claude-plugins/swarmforge-design`. Open Claude Code in the
workspace root (the folder that holds `swarm-forge-lite/` and the projects beside it), then:

```
/plugin marketplace add ~/claude-plugins/swarmforge-design
/plugin install swarmforge-design@swarmforge-design      # "local" scope
/reload-plugins
/swarmforge-design:install ../myproject                  # the pack's INSTALL.md › Part 1
/swarmforge-design:setup
```

Then start the pipeline with `claude --agent swarmforge-design:orchestrator`.

**Needs:** Claude Code 2.1+, `python3` 3.11+ (dryer, crapper), and the pack's tools (`ruff`, `pytest`,
`coverage`, `bb`, `tree-sitter-language-pack`). `python3 $PACK/tools/doctor.py` says what is missing.

## Use

| Entry point | What it does |
|---|---|
| `claude --agent swarmforge-design:orchestrator` | The pipeline. The orchestrator has no Write/Edit tool and may dispatch only the pack's roles |
| `/swarmforge-design:swarm <task>` | The orchestrator's procedure in a normal session (no guard on the orchestrator itself) |
| `/swarmforge-design:install [dir]` | `install.py inspect`, one round of questions, `apply --dry-run`, `apply`, `doctor` |
| `/swarmforge-design:update` | `update.py check`, `trial`, `apply --yes` only on your yes, then `sync-agents` |
| `/swarmforge-design:verify-pack [project]` | `doctor`, `arch.py env`, the toolchain, `gate.py --list`, the design gates, the contract suite |
| `/swarmforge-design:setup` | Local settings a plugin cannot ship (below) |
| `/swarmforge-design:sync-agents` | Rebuild `agents/` after a pack update |

## How the pack maps to Claude Code

| The pack | Claude Code (this plugin) |
|---|---|
| `protocol/<role>.md` + constitution + 3 articles | `agents/<role>.md`, built verbatim by `sync-agents` |
| read step 3: `PROJECT.md` | in every role's start context (hook), so no read is spent on it |
| config: `SWARM_CONFIG` → `pack.local.json` → `pack.json`, `<PACK>`, `projects`, `PACK_PROJECT` | the same rule; every session and role starts with each project's absolute roots and which one is the default |
| "dispatch one role at a time" | `Agent` with `subagent_type: swarmforge-design:<role>`; the guard forces `run_in_background: false` |
| a child that stopped early: "re-dispatch with `Continue`" | `SendMessage` to its agent id |
| the orchestrator "writes nothing, never commits" | no Write/Edit tool; the guard denies `git commit/push/stash/reset/rebase/am` and any non-role agent |
| protocol/README › Roles (who writes what) | the guard, for Edit/Write and shell writes, in every project: designer → `<docs_root>/specs/`, `<design_root>/{runtime,policy}.json`, its project's `specs`/`subsystems` in the live config (any other config change is refused); specifier → features; coder/refactorer/architect → source + tests; test-reviewer → scratch only |
| generated files are never hand-edited | the guard refuses `*.html` under docs, `.metrics/`, generated acceptance, and `overlay.json` (written by `arch classes add\|remove\|annotate`, the designer's only) |
| the harness and the legacy `architecture/` are never written in an installed pack | the guard refuses every file in the pack except `tmp/` |
| `install.py apply`, `update.py apply`, `migrate.py`: the operator's call | a role is refused; the orchestrator and the operator are asked |
| "Mutation testing is not part of this pack" | the guard refuses `gherkin-mutator`, `mutmut`, `cosmic-ray` |
| "Report every command with its exit status" | a SubagentStop hook sends a report back once when it names no exit status (or the test-reviewer gives no verdict), and saves every report under `$PACK/tmp/claude-reports/` |
| `gate.py <name>`, `doctor.py`, `arch.py`, `umlview`, the Gherkin parser, `codegraph explore`, `uv run …`, read-only git, `rm -f` of stale scratch | run without a permission prompt when every path stays inside the workspace |

## Models

Every role defaults to **Haiku 5.5, effort max**. Change one role and rebuild:

```
python3 scripts/sfd sync-agents --model architect=opus:high --model designer=sonnet:high
```

`--default MODEL[:EFFORT]` changes every other role. Then `/reload-plugins`.

## setup

A plugin may not set permissions, environment variables, the status line or the subagent cache TTL.
`/swarmforge-design:setup` adds them to the workspace's `.claude/settings.local.json` (kept out of git, and
listed in `.git/info/exclude`): rules for the pack's read-only commands, Edit rules for the roles' roots,
`Read(**/.env)` deny, `PACK` (and `PROJECT` when the config has one project: with several, `$PROJECT` depends
on `PACK_PROJECT`), the status line, and `subagentPromptCacheTtl: 1h`. `--undo` removes exactly that; your own
values always win. Run it again after `install` or a config change.

## Tests

```
python3 -m pytest -q tests      # on a fake two-project pack
ruff check . && ruff format --check .
```
