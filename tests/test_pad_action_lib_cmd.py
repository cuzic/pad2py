"""`pad_action_lib.cmd_actions`の単体テスト。

実機対象は`cmd.exe`(Windows専用)だが、このロジック層自体は持続的セッション+
非ブロッキング読み取りという仕組みを検証するものなので、Linuxでも動く`sh`を
`shell_command=`で注入してテストする。
"""
from __future__ import annotations

import time

import pytest

from dump_daemon.pad_action_lib import cmd_actions as cmd


def _open_sh_session(**kwargs) -> cmd.CmdSession:
    return cmd.open_cmd_session(shell_command=["sh"], **kwargs)


def test_open_cmd_session_missing_directory_raises(tmp_path) -> None:
    with pytest.raises(cmd.WorkingDirectoryDoesNotExist):
        cmd.open_cmd_session(directory=str(tmp_path / "missing"), shell_command=["sh"])


def test_write_then_read_returns_combined_output_by_default() -> None:
    session = _open_sh_session()
    try:
        session.write("echo out-line")
        session.write("echo err-line 1>&2")
        time.sleep(0.3)
        combined = session.read()
        assert "out-line" in combined
        assert "err-line" in combined
    finally:
        session.close()


def test_read_can_split_stdout_and_stderr() -> None:
    session = _open_sh_session()
    try:
        session.write("echo out-line")
        session.write("echo err-line 1>&2")
        time.sleep(0.3)
        stdout_text, stderr_text = session.read(split_output_and_error=True)
        assert "out-line" in stdout_text
        assert "err-line" in stderr_text
        assert "err-line" not in stdout_text
    finally:
        session.close()


def test_persistent_session_keeps_state_across_writes() -> None:
    session = _open_sh_session()
    try:
        session.write("X=hello")
        session.write("echo $X")
        time.sleep(0.3)
        assert "hello" in session.read()
    finally:
        session.close()


def test_wait_for_text_blocks_until_marker_appears() -> None:
    session = _open_sh_session()
    try:
        session.write("sleep 0.2; echo marker-found")
        result = session.wait_for_text("marker-found", timeout=2)
        assert "marker-found" in result
    finally:
        session.close()


def test_wait_for_text_regex() -> None:
    session = _open_sh_session()
    try:
        session.write("echo code=42")
        result = session.wait_for_text(r"code=\d+", timeout=2, is_regex=True)
        assert "code=42" in result
    finally:
        session.close()


def test_wait_for_text_times_out() -> None:
    session = _open_sh_session()
    try:
        with pytest.raises(cmd.TimeoutExpiredError):
            session.wait_for_text("never-appears", timeout=0.3)
    finally:
        session.close()


def test_write_after_close_raises_session_closed() -> None:
    session = _open_sh_session()
    session.close()
    with pytest.raises(cmd.SessionClosedError):
        session.write("echo x")


def test_close_is_idempotent_and_does_not_raise() -> None:
    session = _open_sh_session()
    session.close()
    session.close()  # 2回目も例外を投げない(ベストエフォート)
