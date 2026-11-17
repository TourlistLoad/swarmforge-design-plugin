---
name: verify-pack
description: Check that the design pack can run here — doctor, the selected project's resolved paths, the toolchain, the pack's own contract suite and the design gates — and report a table. Changes nothing. Use after installing or updating the pack.
argument-hint: "[project]"
disable-model-invocation: true
---

Verify from the folder Claude Code runs in. Change nothing. Run each command once, one per Bash call, with
`PACK_PROJECT=<project>` in front when a project is given ($ARGUMENTS) or the config has more than one.

1. `python3 $PACK/tools/doctor.py` (add `--project <project>`): every row and the exit status. A `fail` row
   names its remedy; a missing config points to `/swarmforge-design:install`.
2. `python3 $PACK/tools/design/arch.py env`: which config, project, class root, docs and design folder resolved.
   A `warning:` line means the legacy `architecture/<project>/` is read.
3. Toolchain (tools/README.md): `python3 --version` (3.11 or later for dryer and crapper), `ruff --version`,
   `python3 -m pytest --version`, `python3 -m coverage --version`, `bb --version`, and
   `python3 -c "import tree_sitter_language_pack; print('analyzers available')"`.
4. `python3 $PACK/tools/gate.py --list`, then the design gates: `python3 $PACK/tools/design/arch.py classes
   validate`, `… runtime validate`, `… docs validate`.
5. The harness's own suite, from the pack folder: `python3 -m pytest -q` (the contract suite). Some contract
   tests read the configured projects' real trees: a failure that names a missing project tree is the
   workspace, not the harness. Say which.

Report a table: check, command, exit status, and a one-line note. Name anything you could not run.
