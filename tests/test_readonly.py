"""Lines the guard lets run unasked: reads inside the workspace, and the pack's own commands."""

import pytest
from sfd.readonly import reads_only_inside


def passes(line, workspace, pack, cwd=None):
    return reads_only_inside(line, cwd or workspace, pack.workspace_roots, pack)


@pytest.mark.parametrize(
    "line",
    [
        "ls $PACK/../app/src && grep -rn Labels $PACK/../app/docs | sort",
        "cd swarm-forge-lite && sed -n 1,40p protocol/coder.md",
        "python3 $PACK/tools/design/arch.py docs validate --source-root $PACK/../app/src",
        (
            'A=$PACK/tmp; rm -f "$A/labels.json"; $PACK/tools/shared/gherkin-parser $PACK/../app/tests/features/a.feature '
            '"$A/labels.json" && bb --config $PACK/tools/shared/aps/bb.edn gherkin-ir-dry-checker "$A/labels.json"'
        ),
        "cd app && python3 -m pytest -q tests/unit; echo exit ${PIPESTATUS[0]}",
        "cd svc && PACK_PROJECT=svc python3 checks/run_acceptance.py",
        "rm -f $PACK/tmp/svc/api.json && codegraph explore LabelSet",
        "cd app && uv run --frozen ruff check .",
        "cd app && python3 tests/acceptance/run_acceptance.py --verbose",
        "ruff check $PACK/../app/src && ruff format --check $PACK/../app/src",
        "git -C app status --short && git -C app diff --stat",
    ],
)
def test_pack_commands_and_reads_pass(workspace, pack, line):
    assert passes(line, workspace, pack)


@pytest.mark.parametrize(
    "line",
    [
        "ruff check --fix $PACK/../app/src",
        "rm -f $PACK/../app/src/app/labels.py",
        "rm -rf $PACK/tmp",
        "bb --config $PACK/tools/shared/aps/bb.edn gherkin-mutator x.json",
        "cat ~/.ssh/id_rsa",
        "cat $PACK/../app/.env",
        "ls $(pwd)",
        "cat /etc/passwd",
        "python3 -m pip install x",
        "git -C app commit -m x",
        "echo x > $PACK/../app/src/a.py",
        "ls > $UNSET/x.txt",
        "ls $UNKNOWN/src",
        "for d in / /etc; do ls $d; done",
    ],
)
def test_writes_outside_paths_and_unclear_lines_do_not(workspace, pack, line):
    assert not passes(line, workspace, pack)


def test_variables_count_only_when_the_session_exports_them(workspace):
    from sfd.pack import Pack

    bare = Pack.load(workspace, {})
    assert not reads_only_inside("cat $PACK/protocol/coder.md", workspace, bare.workspace_roots, bare)


def test_without_a_pack_only_plain_reads_pass(workspace):
    assert reads_only_inside("ls src", workspace, (workspace,))
    assert not reads_only_inside("python3 -m pytest", workspace, (workspace,))


@pytest.mark.parametrize(
    "line",
    [
        "env -C $PACK/../app python3 -m pytest -q tests/unit; echo EXIT=$?",
        "env -C $PACK/../app python3 tests/acceptance/run_acceptance.py",
        "env -C $PACK/../app PYTHONPATH=$PACK/tools/shared python3 -m dryer --source-root $PACK/../app/src",
        "cd app && time python3 -m pytest -q tests/unit",
        "timeout 60 ruff check $PACK/../app/src",
        "command -v ruff; command -v bb; python3 --version; ruff --version; date '+%H:%M'",
        "cd app && ruff check --show-settings src > $PACK/tmp/app/ruff.txt 2>&1; grep -c path $PACK/tmp/app/ruff.txt",
        'for d in $PACK / /tmp; do if [ -d "$d/.codegraph" ]; then echo "index at $d"; fi; done',
    ],
)
def test_wrappers_and_version_checks_pass(workspace, pack, line):
    assert passes(line, workspace, pack)


@pytest.mark.parametrize(
    "line",
    ["env -C /tmp ls", "env -i rm -rf $PACK/../app", "time rm $PACK/../app/src/a.py", "command rm x", "make --version"],
)
def test_wrapped_writes_and_outside_dirs_do_not(workspace, pack, line):
    assert not passes(line, workspace, pack)
