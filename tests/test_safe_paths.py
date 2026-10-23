"""入站路径校验的测试。

这些用例对应的是真实可用的攻击载荷：`../../x.py`、`C:\\temp\\x.py`、`..`、
`CON`。它们全部要在"生成任何路径"之前就被处理掉。
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from utils.safe_paths import (
    MAX_NAME_LENGTH,
    UnsafeName,
    ensure_within,
    safe_filename,
    safe_thread_id,
)


def _tmpdir() -> str:
    """不用 pytest 的 tmp_path：它对临时根目录有额外假设，这里只要一个空目录。"""
    return tempfile.mkdtemp(prefix="safe-paths-")


# --------------------------------------------------------------------------- #
# thread_id：会被拼进目录名
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("value", [
    "369c9e2f-c34a-481f-ad79-503805a8dd63",
    "session_001",
    "abc.def",
    "A",
])
def test_thread_id_accepts_uuid_and_slugs(value):
    assert safe_thread_id(value) == value


@pytest.mark.parametrize("value", [
    "",
    " ",
    ".",
    "..",
    "../evil",
    "a/b",
    "a\\b",
    "session x",
    "-leading-dash",
    "x" * 65,
])
def test_thread_id_rejects_traversal_and_junk(value):
    with pytest.raises(UnsafeName):
        safe_thread_id(value)


# --------------------------------------------------------------------------- #
# filename：会被拼进 open()
# --------------------------------------------------------------------------- #
def test_filename_drops_posix_directories():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("a/b/c.pdf") == "c.pdf"


def test_filename_drops_windows_directories():
    assert safe_filename("..\\..\\Windows\\System32\\evil.dll") == "evil.dll"
    assert safe_filename("C:\\temp\\report.pdf") == "report.pdf"
    # POSIX 上反斜杠不是分隔符，必须自己处理
    assert safe_filename("..\\..\\x.py") == "x.py"


def test_filename_keeps_chinese_and_spaces():
    assert safe_filename("经营周报 2026-03.pdf") == "经营周报 2026-03.pdf"


@pytest.mark.parametrize("value", [
    "",
    "/",
    "..",
    ".",
    ".hidden",
    ".env",
    "a:b.txt",
    "a*b.txt",
    "a\x00b.txt",
])
def test_filename_rejects_unsafe(value):
    with pytest.raises(UnsafeName):
        safe_filename(value)


@pytest.mark.parametrize("value", ["CON", "con.txt", "NUL", "com1.log"])
def test_filename_rejects_windows_device_names(value):
    with pytest.raises(UnsafeName):
        safe_filename(value)


def test_filename_length_cap():
    assert len(safe_filename("a" * MAX_NAME_LENGTH)) == MAX_NAME_LENGTH
    with pytest.raises(UnsafeName):
        safe_filename("a" * (MAX_NAME_LENGTH + 1))


# --------------------------------------------------------------------------- #
# 纵深防御
# --------------------------------------------------------------------------- #
def test_ensure_within_accepts_child():
    root = _tmpdir()
    try:
        target = ensure_within(root, Path(root) / "a.txt")
        assert target == (Path(root) / "a.txt").resolve()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ensure_within_rejects_parent():
    root = _tmpdir()
    try:
        with pytest.raises(UnsafeName):
            ensure_within(root, Path(root) / ".." / "escape.txt")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ensure_within_rejects_absolute_elsewhere():
    root = _tmpdir()
    try:
        with pytest.raises(UnsafeName):
            ensure_within(root, os.path.abspath(os.sep))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_upload_of_malicious_name_cannot_escape():
    """端到端语义：名字清洗后拼出来的路径一定还在目标目录里。"""
    root = _tmpdir()
    try:
        target = ensure_within(root, Path(root) / safe_filename("../../../../evil.py"))
        assert target.parent == Path(root).resolve()
        assert target.name == "evil.py"
    finally:
        shutil.rmtree(root, ignore_errors=True)
