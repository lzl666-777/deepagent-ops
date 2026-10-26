"""Core types: ``Auditor``, ``AuditReport`` and ``AuditIssue``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional


class _Skip:
    """Sentinel returned by a check that cannot verify a claim (e.g. missing data)."""

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "SKIP"


SKIP = _Skip()


@dataclass
class AuditIssue:
    """A single problem found by a check."""

    check: str
    field: str
    message: str
    severity: str = "error"  # "error" (fails the audit) | "warning"
    expected: Any = None
    actual: Any = None

    def __str__(self) -> str:
        return f"[{self.severity}] {self.check}({self.field}): {self.message}"


@dataclass
class AuditReport:
    """Result of running an :class:`Auditor`."""

    issues: List[AuditIssue] = field(default_factory=list)
    checked: int = 0
    skipped: int = 0

    @property
    def passed(self) -> bool:
        """True only when no ``error``-severity issue was found."""
        return not any(i.severity == "error" for i in self.issues)

    @property
    def errors(self) -> List[AuditIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[AuditIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def to_markdown(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        lines = [
            "## Audit Report",
            "",
            f"**Result:** {status}",
            f"**Checked:** {self.checked} | **Skipped:** {self.skipped} | **Issues:** {len(self.issues)}",
        ]
        if self.issues:
            lines += ["", "| Check | Field | Severity | Message |", "|---|---|---|---|"]
            for issue in self.issues:
                lines.append(
                    f"| {issue.check} | {issue.field} | {issue.severity} | {issue.message} |"
                )
        return "\n".join(lines)

    def __bool__(self) -> bool:
        return self.passed


class Auditor:
    """Runs a list of checks against a dict of agent claims.

    Args:
        checks: iterable of :class:`agent_audit.checks.Check` objects.

    Example::

        report = Auditor([Check.threshold("x", max=1)]).check({"x": 2})
        assert not report.passed
    """

    def __init__(self, checks: Iterable[Any]):
        self.checks = list(checks)

    def check(self, claims: dict, source: Optional[Any] = None) -> AuditReport:
        report = AuditReport()
        for check in self.checks:
            try:
                outcome = check.run(claims, source)
            except Exception as exc:  # a broken check must never crash the audit
                outcome = AuditIssue(
                    check=getattr(check, "name", "unknown"),
                    field="*",
                    message=f"check crashed: {type(exc).__name__}: {exc}",
                    severity="error",
                )
            if outcome is SKIP:
                report.skipped += 1
                continue
            if outcome is None:
                report.checked += 1
                continue
            if not isinstance(outcome, AuditIssue):
                # A custom check returning a string / bool / list used to be
                # appended as-is, and the next `report.passed` blew up with
                # AttributeError inside the caller's business code. Coerce it
                # here, fail closed, and say what happened.
                outcome = AuditIssue(
                    check=getattr(check, "name", "unknown"),
                    field="*",
                    message=(
                        f"check returned {type(outcome).__name__}, expected "
                        f"None/AuditIssue/SKIP: {outcome!r}"
                    ),
                    severity="error",
                )
            report.checked += 1
            report.issues.append(outcome)
        return report
