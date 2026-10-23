"""Tests for the deterministic final decision gate.

The gate is the application-level answer to the audit subagent's fail-open
behaviour: a decision without a machine-readable receipt, or with a receipt the
deterministic audit rejects, never reaches the user.
"""

from datetime import date

from tools.audit_core import Truth
from tools.decision_gate import (
    RECEIPT_MARKER,
    extract_receipt,
    gate_final_answer,
    looks_like_decision,
)


def _truth(product: str = "便携榨汁杯") -> Truth:
    return Truth(
        product_name=product,
        sku="JB-USB-300",
        category="家居厨房",
        cost=11.59,
        price=19.99,
        gross_margin=42.0,
        sales_qty=2200,
        sales_amount=43978.0,
        returned_qty=480,
        return_rate=21.82,
        on_hand=1200,
        in_transit=300,
        sales90_qty=900,
        turnover_days=150.0,
        data_as_of=date(2026, 3, 31),
    )


def _receipt(claims=None, product="便携榨汁杯") -> str:
    import json

    return "%s\n%s" % (
        RECEIPT_MARKER,
        json.dumps({
            "product_name": product,
            "claims": claims if claims is not None else {
                "gross_margin": 42.0,
                "return_rate": 21.82,
                "turnover_days": 150.0,
            },
        }, ensure_ascii=False),
    )


def test_looks_like_decision_is_narrow():
    assert looks_like_decision("最终决策建议：NO-GO")
    assert looks_like_decision("给出 GO/NO-GO 建议")
    assert not looks_like_decision("数据库里有哪些商品？")


def test_non_decision_passes_through():
    result = gate_final_answer("数据库里有 8 个商品。", truth_loader=lambda _: _truth())
    assert result.allowed
    assert result.text == "数据库里有 8 个商品。"


def test_decision_without_receipt_is_blocked():
    result = gate_final_answer("最终决策建议：NO-GO", truth_loader=lambda _: _truth())
    assert not result.allowed
    assert result.reason == "missing_receipt"
    assert "决策门禁" in result.text


def test_decision_with_valid_receipt_passes():
    text = "最终决策建议：NO-GO\n\n" + _receipt()
    result = gate_final_answer(text, truth_loader=lambda _: _truth())
    assert result.allowed, result.text
    assert result.outcome is not None
    assert result.outcome.passed


def test_decision_with_wrong_number_is_blocked():
    text = "最终决策建议：NO-GO\n\n" + _receipt({
        "gross_margin": 42.0,
        "return_rate": 8.2,
        "turnover_days": 150.0,
    })
    result = gate_final_answer(text, truth_loader=lambda _: _truth())
    assert not result.allowed
    assert result.reason == "audit_failed"
    assert "21.82" in result.text


def test_decision_with_missing_required_claims_is_blocked():
    text = "最终决策建议：NO-GO\n\n" + _receipt({"return_rate": 21.82})
    result = gate_final_answer(text, truth_loader=lambda _: _truth())
    assert not result.allowed
    assert result.reason == "audit_failed"
    assert "无法复核" in result.text


def test_truth_unavailable_fails_closed():
    def boom(_product):
        raise RuntimeError("db down")

    text = "最终决策建议：NO-GO\n\n" + _receipt()
    result = gate_final_answer(text, truth_loader=boom)
    assert not result.allowed
    assert result.reason == "truth_unavailable"
    assert "无法" in result.text


def test_extract_receipt_tolerates_prose_around_json():
    text = "前言\n" + _receipt() + "\n结尾"
    payload = extract_receipt(text)
    assert payload is not None
    assert payload["product_name"] == "便携榨汁杯"
