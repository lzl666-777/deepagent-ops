"""入站路径安全：所有来自 HTTP 的名字，在落到文件系统前都要过这里。

威胁模型很简单：`file.filename` 和 `thread_id` 都来自客户端，而它们最后都会参与
`pathlib` 拼接并 `open()`。一个 `../../x.py` 就能以服务进程的身份写到任意位置——
不需要任何前置条件，比 SQL 注入更容易得手，也更难事后发现。

单独成模块的原因：`api/server.py` 依赖 FastAPI、MySQL、LLM，导入即需要凭据；
校验逻辑放在这里，测试就不必把整个应用拉起来。
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Union

PathLike = Union[str, "Path"]

#: thread_id 只接受 uuid / slug 形态（项目里它来自 uuid4()，前端回传不会变形）。
_THREAD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

#: 文件名里不允许出现的字符：控制字符、Windows 保留字符、两种路径分隔符。
_UNSAFE_NAME_CHARS = re.compile(r'[\x00-\x1f\x7f<>:"|?*\\/]')

#: Windows 上这些名字表示设备，`open()` 会挂起或写入设备。
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    "%s%d" % (prefix, i) for prefix in ("COM", "LPT") for i in range(1, 10)
}

MAX_NAME_LENGTH = 128


class UnsafeName(ValueError):
    """名字不合法。调用方应转成 400，而不是 500。"""


def safe_thread_id(value: str) -> str:
    """校验会话 ID，它会被拼进目录名（`output/session_<id>`、`upload/session_<id>`）。"""
    if not isinstance(value, str):
        raise UnsafeName("thread_id 必须是字符串")
    value = value.strip()
    if not value or value in (".", "..") or not _THREAD_ID.match(value):
        raise UnsafeName(
            "thread_id 非法：只允许字母、数字、点、下划线、连字符，长度 1-64"
        )
    return value


def safe_filename(value: str) -> str:
    """把客户端给的文件名压成"一个纯文件名"，不带任何目录成分。"""
    if not isinstance(value, str):
        raise UnsafeName("文件名必须是字符串")

    # Windows 客户端可能带反斜杠，而 POSIX 上 Path 不把 ``\\`` 当分隔符，
    # 所以先自己统一，再取最后一段。这一步保证结果里不含分隔符。
    name = value.replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFC", name).strip()

    if not name or name in (".", ".."):
        raise UnsafeName("文件名为空或非法")
    if name.startswith("."):
        raise UnsafeName("不允许写入隐藏文件")
    if _UNSAFE_NAME_CHARS.search(name):
        raise UnsafeName("文件名包含非法字符")
    if name.split(".")[0].upper() in _RESERVED_NAMES:
        raise UnsafeName("文件名是系统保留名")
    if len(name) > MAX_NAME_LENGTH:
        raise UnsafeName("文件名过长（最多 %d 个字符）" % MAX_NAME_LENGTH)
    return name


def ensure_within(base: PathLike, target: PathLike) -> Path:
    """解析后确认 target 仍在 base 里。纵深防御：即使上面漏了，这里也拦得住。"""
    base_path = Path(base).resolve()
    target_path = Path(target).resolve()
    if target_path != base_path and not target_path.is_relative_to(base_path):
        raise UnsafeName("路径越界：%s 不在 %s 内" % (target_path, base_path))
    return target_path
