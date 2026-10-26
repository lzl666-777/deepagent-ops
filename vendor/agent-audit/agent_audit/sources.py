"""Data sources: how the auditor fetches ground truth when a check needs it."""

from __future__ import annotations

from typing import Any, Callable, Dict, Protocol


class DataSource(Protocol):
    """Anything that can resolve a field name to a ground-truth value."""

    def get(self, field: str) -> Any:
        ...


class DictSource:
    """Wrap a plain dict as a data source."""

    def __init__(self, data: Dict[str, Any]):
        self._data = dict(data)

    def get(self, field: str) -> Any:
        return self._data.get(field)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"DictSource({list(self._data)!r})"


class CallableSource:
    """Wrap a function ``fn(field) -> value`` as a data source (e.g. a SQL lookup)."""

    def __init__(self, fn: Callable[[str], Any]):
        self._fn = fn

    def get(self, field: str) -> Any:
        return self._fn(field)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"CallableSource({getattr(self._fn, '__name__', 'fn')})"
