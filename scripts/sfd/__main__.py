"""Run a hook or a command: `python3 <plugin>/scripts/sfd <command> [args]`."""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sfd.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
