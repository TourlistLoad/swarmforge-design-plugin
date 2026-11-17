---
name: install
description: Install the design pack for one project the way INSTALL.md › Part 1 says — tools/install.py inspect, one round of questions, an answers file, a dry run, apply, doctor — then refresh this workspace's settings. Only when the operator asks to install or wire the pack.
argument-hint: "[project folder]"
disable-model-invocation: true
---

Install the design pack for one project, following `$PACK/INSTALL.md` › Part 1 exactly. Project folder, if
given: $ARGUMENTS. The session start names PACK and the config that resolved.

1. If no folder is given, ask for it with `AskUserQuestion`. Then run
   `python3 $PACK/tools/install.py inspect --root <folder>` and read the brief it prints
   (`$PACK/tmp/install-brief.md`). Every key is `fact`, `guess` or `missing`.
2. Ask once: one `AskUserQuestion` call with the detected root, your recommendation for each `guess`, and only
   the `missing` keys as questions, each with its recommendation first. Keep `design_root` only if the project
   repository accepts a new folder. Never invent a value for a key nobody can answer: say what would find it.
3. Write the answers file with the skeleton from the brief to `$PACK/tmp/install.json` (scratch, gitignored).
4. `python3 $PACK/tools/install.py apply --answers $PACK/tmp/install.json --dry-run`, show the plan, then run it
   without `--dry-run` (the guard asks you to confirm: this is the operator's install). Never edit the tracked
   `config/pack.json`; `apply` writes `config/pack.local.json`.
5. `python3 $PACK/tools/doctor.py --project <name>`: report every `fail` row with its remedy and the exit status.
6. Run `/swarmforge-design:setup` so PACK and the allow rules follow the new config, and say the one thing a
   human still writes: `$PACK/PROJECT.md`, the environment record every role reads. Do not commit.
