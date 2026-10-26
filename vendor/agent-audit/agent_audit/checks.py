"""Built-in audit checks.

Every check is a :class:`Check` instance. Running one returns:

* ``None``  -> the claim passed
* ``AuditIssue`` -> the claim failed (or produced a warning)
* ``SKIP``  -> the claim could not be verified (missing data)
"""

from __future__ import annotations

import ast
import operator
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional, Tuple

from .core import AuditIssue, SKIP

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_UNARY_OPS = {ast.USub: operator.neg, ast.UAdd: operator.pos}

#: ``**`` is allowed, but an unbounded exponent lets one model-generated formula
#: pin a worker: ``2 ** 10 ** 9`` burns seconds and hundreds of MB before it even
#: has to be printed. The AST allowlist prevents code execution, not exhaustion.
_MAX_EXPONENT = 64

_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S")


def _to_number(value: Any) -> Optional[float]:
    """Best-effort conversion to float. Returns ``None`` for non-numeric values."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").replace("%", "").strip())
        except ValueError:
            return None
    return None


def _to_datetime(value: Any) -> Optional[datetime]:
    """Best-effort conversion to a timezone-aware datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def expr_names(expr: str) -> set:
    """Names referenced by an arithmetic expression."""
    tree = ast.parse(expr, mode="eval")
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def safe_eval(expr: str, variables: dict) -> float:
    """Evaluate a simple arithmetic expression on named variables.

    Only numeric constants, names, ``+ - * / ** %`` and unary signs are allowed;
    calls, attributes, indexing, strings and comparisons are rejected, and the
    exponent of ``**`` is capped. This is safe to run on model-generated
    formulas without handing the model a way to execute code or exhaust a
    worker.
    """
    tree = ast.parse(expr, mode="eval")

    def _walk(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return _walk(node.body)
        if isinstance(node, ast.Constant):
            # A string constant used to slip through and made `consistency`
            # crash later, which `Auditor` then reported as a *failed claim*:
            # the audit blamed the data for a broken formula.
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError(f"only numeric constants are allowed, got {node.value!r}")
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise KeyError(f"unknown variable: {node.id}")
            return variables[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) is ast.Pow:
            base = _walk(node.left)
            exponent = _walk(node.right)
            if abs(exponent) > _MAX_EXPONENT:
                raise ValueError(f"exponent {exponent:g} exceeds the limit of {_MAX_EXPONENT}")
            return base ** exponent
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            return _BIN_OPS[type(node.op)](_walk(node.left), _walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](_walk(node.operand))
        raise ValueError(f"unsupported expression: {ast.dump(node)}")

    return _walk(tree)


# --------------------------------------------------------------------------- #
# Check
# --------------------------------------------------------------------------- #


class Check:
    """A single audit rule."""

    def __init__(self, name: str, fn: Callable[[dict, Any], Any]):
        self.name = name
        self._fn = fn

    def run(self, claims: dict, source: Any):
        return self._fn(claims, source)

    # ------------------------------------------------------------------ #
    # factories
    # ------------------------------------------------------------------ #
    @classmethod
    def threshold(
        cls,
        field: str,
        min: Optional[float] = None,
        max: Optional[float] = None,
        severity: str = "error",
        expect_range: Optional[Tuple[float, float]] = None,
    ) -> "Check":
        """Fail when ``claims[field]`` is outside ``[min, max]``.

        Pass ``expect_range`` when the scale of the field is known, so a value
        from a different scale is reported as an error instead of being compared
        against a bound it was never measured in::

            # a ratio field that receives a percentage
            Check.threshold("conversion_rate", max=1.0, expect_range=(0, 1))
            # -> claim 34.8 is out of range -> error, not a silent "exceeds max"

        It cannot tell ``0.348`` from ``34.8`` inside a ``(0, 100)`` range — units
        are a property of your schema, not of the library. When you have a
        ground-truth source, compare against it (``consistency``/``custom``):
        that is what catches a claim and its truth expressed in different units.
        """

        def _run(claims: dict, source: Any):
            value = _to_number(claims.get(field))
            if value is None:
                return SKIP
            if expect_range is not None:
                low, high = expect_range
                if not (low <= value <= high):
                    return AuditIssue(
                        f"threshold({field})", field,
                        f"value {value:g} is outside the expected scale "
                        f"[{low:g}, {high:g}] - the claim is in different units "
                        f"than the bound",
                        "error", expected=f"within [{low:g}, {high:g}]", actual=value,
                    )
            if max is not None and value > max:
                return AuditIssue(
                    f"threshold({field})", field, f"value {value:g} exceeds max {max:g}",
                    severity, expected=f"<= {max:g}", actual=value,
                )
            if min is not None and value < min:
                return AuditIssue(
                    f"threshold({field})", field, f"value {value:g} below min {min:g}",
                    severity, expected=f">= {min:g}", actual=value,
                )
            return None

        return cls(f"threshold({field})", _run)

    @classmethod
    def consistency(
        cls,
        target: str,
        formula: str,
        tolerance: float = 0.01,
        severity: str = "error",
    ) -> "Check":
        """Recompute ``formula`` and compare with ``claims[target]``.

        Missing formula variables are fetched from ``source`` when possible.

        Example::

            Check.consistency("revenue", formula="price * qty")
        """
        names = expr_names(formula)

        def _run(claims: dict, source: Any):
            actual = _to_number(claims.get(target))
            if actual is None:
                return SKIP

            variables = {
                k: n for k, v in claims.items() if (n := _to_number(v)) is not None
            }
            for name in names - set(variables):
                if source is None:
                    continue
                try:
                    value = _to_number(source.get(name))
                except Exception:
                    value = None
                if value is not None:
                    variables[name] = value

            if not names.issubset(variables):
                return SKIP

            try:
                expected = safe_eval(formula, variables)
            except Exception as exc:
                # A formula that cannot be evaluated is an audit *configuration*
                # error, not missing data. Returning SKIP here made the whole
                # report pass with `skipped += 1`, i.e. a typo in a safety rule
                # silently disabled the rule. Fail closed instead: the caller
                # must fix the formula before trusting the audit.
                return AuditIssue(
                    f"consistency({target})",
                    "*",
                    "audit configuration error: formula %r could not be evaluated: "
                    "%s: %s" % (formula, type(exc).__name__, exc),
                    "error",
                )

            if expected == 0:
                ok = abs(actual) <= tolerance
            else:
                ok = abs(actual - expected) / abs(expected) <= tolerance
            if not ok:
                return AuditIssue(
                    f"consistency({target})", target, f"{actual:g} != {formula} ({expected:g})",
                    severity, expected=round(expected, 6), actual=actual,
                )
            return None

        return cls(f"consistency({target})", _run)

    @classmethod
    def freshness(
        cls,
        field: str,
        max_age_days: float,
        now: Optional[datetime] = None,
        severity: str = "warning",
    ) -> "Check":
        """Warn when ``claims[field]`` (a date/timestamp) is older than ``max_age_days``.

        Example::

            Check.freshness("market_price", max_age_days=180)
        """

        def _run(claims: dict, source: Any):
            stamp = _to_datetime(claims.get(field))
            if stamp is None:
                return SKIP
            reference = now or datetime.now(timezone.utc)
            age_days = (reference - stamp).total_seconds() / 86400
            if age_days > max_age_days:
                return AuditIssue(
                    f"freshness({field})", field,
                    f"data is {age_days:.0f} days old (max {max_age_days:g})",
                    severity, expected=f"<= {max_age_days:g} days", actual=f"{age_days:.0f} days",
                )
            return None

        return cls(f"freshness({field})", _run)

    @classmethod
    def custom(cls, name: str, fn: Callable[[dict, Any], Any]) -> "Check":
        """User-defined check: ``fn(claims, source)`` -> ``None | AuditIssue | SKIP``."""
        return cls(name, fn)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Check({self.name!r})"
