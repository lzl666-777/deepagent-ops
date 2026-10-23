"""Deterministic final gate for decision answers.

The audit subagent is still an LLM: it can forget to call ``verify_claims`` or
write a confident conclusion that contradicts the tool result. This module is
the last line of defence at the application boundary:

* a decision answer must contain a machine-readable receipt::

      【决策回执】
      {"product_name": "便携榨汁杯", "claims": {"gross_margin": 42.0, ...}}

* the receipt is checked against :func:`tools.audit_tools.collect_truth` and
  :func:`tools.audit_core.audit_claims` with the required decision metrics;
* if the receipt is missing, malformed, the DB is unavailable, or the audit is
  not verified, the answer is replaced with a fail-closed message.

This is intentionally *not* another prompt instruction: the model cannot get a
decision through by ignoring an instruction. The only way through is a receipt
that the deterministic audit accepts.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from tools.audit_core import (
    DECISION_REQUIRED_METRICS,
    AuditOutcome,
    Truth,
    audit_claims,
    render,
)
from tools.audit_tools import collect_truth

RECEIPT_MARKER = "【决策回执】"

#: Phrases that make an answer a decision rather than a lookup.  Keep this
#: narrow: a normal data question should not be forced through a gate.
_DECISION_PATTERNS = (
    r"GO\s*/\s*NO-?GO",
    r"最终决策",
    r"决策建议",
    r"备货策略",
    r"备货建议",
    r"定价策略",
    r"建议下架",
    r"不建议跟进",
)


@dataclass
class GateResult:
    allowed: bool
    text: str
    outcome: Optional[AuditOutcome] = None
    reason: str = ""


def looks_like_decision(text: str) -> bool:
    if not text:
        return False
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in _DECISION_PATTERNS)


def extract_receipt(text: str) -> Optional[Dict[str, Any]]:
    """Parse the JSON object following the last receipt marker."""
    if not text or RECEIPT_MARKER not in text:
        return None
    tail = text.rsplit(RECEIPT_MARKER, 1)[1]
    start = tail.find("{")
    end = tail.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        payload = json.loads(tail[start:end + 1])
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _blocked(reason: str) -> str:
    return (
        "【决策门禁】无法给出决策\n\n"
        "%s\n\n"
        "按审计要求：没有可复核的【决策回执】或审计未通过时，不得给出 "
        "GO/NO-GO、定价、备货或下架结论。请先让数据分析师给出数字，"
        "再提交带 product_name 与 claims 的决策回执。" % reason
    )


def gate_final_answer(
    text: str,
    truth_loader: Callable[[str], Truth] = collect_truth,
) -> GateResult:
    """Apply the deterministic gate to a final answer.

    Args:
        text: final model answer.
        truth_loader: injectable for tests; production uses MySQL.
    """
    if not looks_like_decision(text):
        return GateResult(True, text)

    receipt = extract_receipt(text)
    if not receipt:
        return GateResult(
            False, _blocked("答案里没有找到可解析的【决策回执】。"),
            reason="missing_receipt",
        )

    product = str(receipt.get("product_name") or "").strip()
    claims = receipt.get("claims")
    if not product:
        return GateResult(False, _blocked("决策回执缺少 product_name。"), reason="missing_product")
    if not isinstance(claims, dict) or not claims:
        return GateResult(False, _blocked("决策回执缺少 claims。"), reason="missing_claims")

    try:
        truth = truth_loader(product)
    except Exception as exc:  # DB unavailable / product ambiguous: fail closed
        return GateResult(
            False,
            _blocked("无法取到数据库基准值：%s: %s。" % (type(exc).__name__, exc)),
            reason="truth_unavailable",
        )

    outcome = audit_claims(
        claims, truth, required=DECISION_REQUIRED_METRICS,
    )
    if not outcome.passed:
        return GateResult(
            False,
            render(outcome),
            outcome=outcome,
            reason="audit_failed",
        )
    return GateResult(True, text, outcome=outcome)
