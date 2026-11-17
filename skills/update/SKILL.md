---
name: update
description: Update the installed design pack the way README › Update says — update.py check, then trial, then apply only on the operator's explicit yes — then rebuild the role agents. Only when the operator asks to update the harness.
disable-model-invocation: true
---

Update the design pack, never by a blind pull ($PACK/README.md › Update):

1. `python3 $PACK/tools/update.py check`: what is available, grouped by risk. A dirty harness or a diverged
   branch is refused; report the files and stop.
2. `python3 $PACK/tools/update.py trial`: the upstream harness against this project, in a disposable worktree.
   Report the gates it ran and their exit status.
3. Ask the operator with `AskUserQuestion` whether to apply, with the risk groups from step 1. Only on a yes:
   `python3 $PACK/tools/update.py apply --yes` (the guard asks once more: it changes the harness).
4. After an apply, run `/swarmforge-design:sync-agents` so each role agent carries the new
   `protocol/<role>.md` and constitution, then tell the operator to run `/reload-plugins`. Do not commit.
