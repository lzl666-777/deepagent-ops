"""Regression tests for the keyword judge's blind spots.

The old judge passed a hallucinated "Xiaomi 15 does not exist / Xiaomi 17 was
released in 2024" answer because it contained "不存在" and no forbidden price.
These tests encode the two fixes: hard hallucination criteria and the decision
gate override.
"""

from evaluation.evaluate import judge


def test_gate_blocked_is_a_failure_even_if_keywords_match():
    case = {"pass_if": [["仅供参考"]], "fail_if": []}
    ok, reason = judge("仅供参考", case, gate_allowed=False, gate_reason="missing_receipt")
    assert not ok
    assert "决策门禁" in reason


def test_known_xiaomi_hallucination_is_rejected():
    answer = "小米15并不存在。小米17系列在2024年10月发布。"
    case = {"pass_if": [["不存在"]], "fail_if": ["小米17", "2024年10月"]}
    ok, reason = judge(answer, case)
    assert not ok
    assert "禁止内容" in reason


def test_generic_boilerplate_cannot_mask_a_100_percent_claim():
    answer = "2025年9月退货率100%，因此不建议继续。仅供参考。"
    case = {"pass_if": [["仅供参考"]], "fail_if": ["100%"]}
    ok, reason = judge(answer, case)
    assert not ok
    assert "禁止内容" in reason
