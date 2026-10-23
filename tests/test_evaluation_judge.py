"""Regression tests for the keyword judge's blind spots.

The old judge passed a hallucinated "Xiaomi 15 does not exist / Xiaomi 17 was
released in 2024" answer because it contained "不存在" and no forbidden price.
These tests encode the two fixes: hard hallucination criteria and the decision
gate override.
"""

from evaluation.evaluate import CASES, judge


def _case(case_id):
    return next(case for case in CASES if case["id"] == case_id)


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


def test_d1_is_scoped_to_the_internal_database():
    case = _case("D1")
    ok, _ = judge("数据库中未找到小米15手机的价格信息。", case)
    assert ok
    ok, reason = judge("小米15售价5999元。", case)
    assert not ok
    assert "禁止内容" in reason


def test_d3_accepts_a_refusal_that_says_no_prediction_was_emitted():
    case = _case("D3")
    ok, _ = judge("审计不通过；未输出任何销量预测数字。", case)
    assert ok
    ok, _ = judge("该 SKU 不应预测下月销量，应先下架复盘。", case)
    assert ok
    ok, _ = judge("仅供参考。", case)
    assert not ok
