"""Path resolution for agent tools.

Every filename that reaches this module comes from the model or from a file the
model read (which may itself contain a prompt injection).  The only safe rule is
that the resolved path must stay inside the caller's session workspace.  The old
implementation deliberately kept absolute paths outside the session "as-is",
which turned ``read_file_content`` / ``generate_markdown`` into arbitrary
read/write primitives.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from utils.logger_utils import logger


class PathEscape(ValueError):
    """The resolved path is outside the allowed root."""


def _ensure_within(base: Path, candidate: Path) -> Path:
    """Resolve ``candidate`` and reject it unless it stays under ``base``."""
    base_resolved = base.resolve()
    candidate_resolved = candidate.resolve()
    if candidate_resolved != base_resolved and not candidate_resolved.is_relative_to(base_resolved):
        raise PathEscape(
            "路径越界：%s 不在 %s 内" % (candidate_resolved, base_resolved)
        )
    return candidate_resolved


def resolve_path(filename: str, session_dir: Optional[str] = None) -> str:
    """Resolve an agent-supplied path inside the session workspace.

    * virtual prefixes (``/workspace``, ``/mnt/data`` ...) are stripped;
    * ``upload/...`` is resolved under the project's upload directory, but only
      after the traversal is checked;
    * absolute paths outside the session are rejected;
    * ``..`` cannot escape the session;
    * without a session context, the current working directory is the root.

    Raises:
        PathEscape: if the path would leave the allowed root.
    """
    raw = str(filename).replace("\\", "/")

    # 1. Strip virtual prefixes used by different agent sandboxes.
    virtual_prefixes = ("/workspace", "/mnt/data", "/home/user", "/home/ubuntu")
    for prefix in virtual_prefixes:
        if raw.startswith(prefix):
            raw = raw[len(prefix):].lstrip("/")
            break

    # 2. Uploaded files live under <cwd>/upload, never under an arbitrary path.
    if "upload/" in raw:
        relative = raw[raw.find("upload/"):]
        upload_root = Path.cwd() / "upload"
        return str(_ensure_within(upload_root, upload_root / relative[len("upload/"):]))

    # 3. Without a session, keep the path inside the process working directory.
    if not session_dir:
        cwd = Path.cwd()
        return str(_ensure_within(cwd, cwd / raw))

    session = Path(session_dir).resolve()
    path = Path(raw)

    # 4. Absolute Windows/Unix paths are allowed only when already inside the
    #    session.  A Windows "/foo" without a drive is treated as session-relative.
    if path.is_absolute() or (os.name == "nt" and raw.startswith("/")):
        if os.name == "nt" and raw.startswith("/") and not path.drive:
            candidate = session / raw.lstrip("/")
        else:
            candidate = path
    else:
        parts = path.parts
        session_name = session.name
        # Accept the common "output/..." and "session_x/..." forms without
        # nesting session_x/session_x.
        if session_name in parts or (parts and parts[0] == "output"):
            candidate = session / path.name
        else:
            candidate = session / path

    resolved = _ensure_within(session, candidate)
    logger.debug("[path] %r -> %s (session=%s)", filename, resolved, session)
    return str(resolved)
