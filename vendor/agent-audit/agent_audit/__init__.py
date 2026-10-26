"""agent-audit: verify what your AI agent claims.

Quick start::

    from agent_audit import Auditor, Check

    auditor = Auditor(checks=[
        Check.threshold("return_rate", max=8.0, expect_range=(0, 100)),
        Check.consistency("revenue", formula="price * qty"),
        Check.freshness("market_price", max_age_days=180),
    ])
    report = auditor.check(claims={
        "return_rate": 34.8,
        "revenue": 542060,
        "price": 7.99,
        "qty": 23000,
        "market_price": "2025-01-01",
    })
    print(report.passed)          # False
    print(report.to_markdown())   # structured report
"""

from .checks import Check, safe_eval
from .core import AuditIssue, AuditReport, Auditor, SKIP
from .sources import CallableSource, DataSource, DictSource

__version__ = "0.1.2"

__all__ = [
    "Auditor",
    "AuditReport",
    "AuditIssue",
    "Check",
    "SKIP",
    "safe_eval",
    "DataSource",
    "DictSource",
    "CallableSource",
    "__version__",
]
