"""sfd -- the swarmforge-design plugin's hooks, status line, setup and agent build.

The design-boosted pack is instructions only: `constitution.md`, `protocol/<role>.md`, `config/pack.json`
and the commands in `tools/README.md`. One module per job:

- ``pack``          find the pack and resolve `config/pack.json`
- ``shell``         split a shell line into simple commands
- ``roles``         what each role may write (protocol/README.md › Roles)
- ``readonly``      a shell line that only reads, or runs the pack's own commands
- ``guard``         PreToolUse: deny, ask, allow, or run a dispatch in the foreground
- ``report``        SubagentStop: check the prose report and keep it
- ``context``       SessionStart and SubagentStart facts
- ``agents_build``  build the role agents from `protocol/*.md`
- ``setup``         opt-in local settings
- ``statusline``    the status lines
- ``cli``           hook entry point
"""
