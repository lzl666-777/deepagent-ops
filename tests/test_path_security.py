"""Regression tests for agent-tool path isolation.

The upload endpoint already used ``safe_paths``; the agent tools did not.  These
tests pin the boundary for the tools that read/write files on the model's behalf.
The paths do not need to exist; the resolver's job is to reject escapes before
any I/O happens.
"""

from pathlib import Path

import pytest

from utils.path_utils import PathEscape, resolve_path


def _session() -> Path:
    # The project root when pytest runs via the project's pyproject config.
    return Path.cwd() / "output" / "session_test"


def test_absolute_path_outside_session_is_rejected():
    with pytest.raises(PathEscape):
        resolve_path(r"C:\Windows\win.ini", str(_session()))


def test_parent_traversal_is_rejected():
    with pytest.raises(PathEscape):
        resolve_path("../../.env", str(_session()))


def test_relative_path_inside_session_is_allowed():
    resolved = resolve_path("report.md", str(_session()))
    assert resolved == str((_session() / "report.md").resolve())


def test_absolute_path_inside_session_is_allowed():
    target = _session() / "report.md"
    assert resolve_path(str(target), str(_session())) == str(target.resolve())


def test_upload_traversal_is_rejected():
    with pytest.raises(PathEscape):
        resolve_path("upload/../../secret.txt", str(_session()))


def test_upload_file_is_allowed():
    resolved = resolve_path("upload/report.pdf", str(_session()))
    assert resolved == str((Path.cwd() / "upload" / "report.pdf").resolve())


def test_without_session_absolute_outside_cwd_is_rejected():
    with pytest.raises(PathEscape):
        resolve_path(r"C:\Windows\win.ini", None)
