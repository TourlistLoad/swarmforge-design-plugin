"""Splitting a shell line into simple commands and the paths they write."""

import pytest
from sfd.shell import Unparseable, parse


def test_parse_splits_control_operators_and_records_redirect_targets():
    commands = parse("cd app && python3 -m pytest -q 2>&1 | tail -3 > out.txt")
    assert [command.program for command in commands] == ["cd", "pytest", "tail"]
    assert commands[2].writes == ("out.txt",)
    assert commands[1].writes == ()


def test_parse_unwraps_env_timeout_bash_c_and_lane():
    commands = parse("FOO=1 timeout 30 bash -c 'ruff check .' ; tools/shared/lane a1 python3 -m coverage run")
    assert [command.program for command in commands] == ["ruff", "coverage"]


def test_parse_reads_find_exec_as_a_second_command():
    commands = parse("find . -name '*.pyc' -exec rm {} +")
    assert [command.program for command in commands] == ["find", "rm"]


def test_sed_in_place_writes_its_files_but_not_its_script():
    (command,) = parse("sed -i -e 's/a/b/' one.py two.py")
    assert command.written_paths() == ("one.py", "two.py")


def test_parse_skips_wrapper_options_and_their_values():
    commands = parse("timeout -s KILL 30 nice -n 5 env -u HOME -- ruff check")
    assert [command.program for command in commands] == ["ruff"]


def test_parse_refuses_an_unclosed_quote():
    with pytest.raises(Unparseable, match="No closing quotation"):
        parse("echo 'oops")
