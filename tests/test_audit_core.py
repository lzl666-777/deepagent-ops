"""审计核心的单元测试（纯逻辑，不需要 MySQL / LLM）。

这些用例证明的是审计能做到两件原来做不到的事：
1. 报告里的数错了，能指出来，并且指出数据库里的正确值；
2. 报告越了 SOP 红线但数字是真的，判"数据通过 + 红线告警"，而不是混为一谈。
"""

from datetime import date, datetime, timezone

from tools.audit_core import (
    ALIASES,
    METRICS,
    Truth,
    audit_claims,
    canonicalise,
    truth_metrics,
)


def _truth(**overrides) -> Truth:
    """便携榨汁杯的基准值（成本/售价/毛利来自 sql/db.sql；订单聚合为演示口径）。"""
    base = dict(
        product_name="便携榨汁杯",
        sku="JB-USB-300",
        category="家居厨房",
        cost=11.59,
        price=19.99,
        gross_margin=42.00,
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
    base.update(overrides)
    return Truth(**base)


TRUE_CLAIMS = {
    "gross_margin": 42.00,
    "return_rate": 21.82,
    "turnover_days": 150.0,
    "sales_qty": 2200,
    "returned_qty": 480,
    "sales_amount": 43978.0,
}


# --------------------------------------------------------------------------- #
# 数字是真的 vs 数字被改了
# --------------------------------------------------------------------------- #
def test_true_report_passes_data_check():
    outcome = audit_claims(TRUE_CLAIMS, _truth())
    assert outcome.passed
    assert outcome.report.errors == []


def test_true_but_over_red_line_is_a_warning_not_an_error():
    """退货率 21.82% 是真的，但它越过 8% 红线。

    这是业务发现，不是数据错误：``passed`` 表示"数据可信"，红线单独告警。
    如果这里判 error，审计就在替分析师做业务判断。
    """
    outcome = audit_claims(TRUE_CLAIMS, _truth())
    fields = [issue.field for issue in outcome.report.warnings]
    assert "return_rate" in fields
    assert all("SOP" not in issue.check for issue in outcome.report.errors)


def test_understated_return_rate_is_caught():
    """agent-audit README 里的那个故事：报告写 8.2%，实际 21.82%。"""
    outcome = audit_claims({"return_rate": 8.2}, _truth())
    assert not outcome.passed
    message = outcome.report.errors[0].message
    assert "8.2" in message and "21.82" in message


def test_red_line_is_evaluated_on_truth_not_on_the_claim():
    """少报的数字不该决定红线告警：告警要按真值说 21.82%。

    否则分析师把 21.82 写成 8.2 时，告警会变成“8.2 超过上限 8”，
    既没用又误导。
    """
    outcome = audit_claims({"return_rate": 8.2}, _truth())
    sop = next(i for i in outcome.report.warnings if i.check == "threshold(return_rate)")
    assert sop.actual == 21.82
    assert "21.82" in sop.message


def test_fraction_claim_is_named_as_a_unit_error():
    outcome = audit_claims({"return_rate": 0.2182}, _truth())
    assert not outcome.passed
    assert "百分数/小数混用" in outcome.report.errors[0].message


def test_wrong_margin_is_caught():
    outcome = audit_claims({"gross_margin": 55.0}, _truth())
    assert not outcome.passed
    # 两条独立的检查都会命中：报告自身不自洽，且与数据库不符
    checks = {issue.check for issue in outcome.report.errors}
    assert "truth(gross_margin)" in checks
    assert "consistency(gross_margin)" in checks
    truth_issue = next(i for i in outcome.report.errors if i.check == "truth(gross_margin)")
    assert truth_issue.expected == 42.0


def test_counts_must_be_exact():
    outcome = audit_claims({"sales_qty": 2199}, _truth())
    assert not outcome.passed
    assert outcome.report.errors[0].field == "sales_qty"


def test_internally_inconsistent_report_is_caught_even_without_truth():
    """毛利率和成本/售价对不上：这条只靠报告自身就能发现。"""
    outcome = audit_claims(
        {"gross_margin": 55.0, "cost": 11.59, "price": 19.99}, _truth()
    )
    checks = [issue.check for issue in outcome.report.errors]
    assert any(c.startswith("consistency(") for c in checks)


# --------------------------------------------------------------------------- #
# 缺数据 ≠ 出错
# --------------------------------------------------------------------------- #
def test_missing_claims_are_skipped_not_failed():
    outcome = audit_claims({}, _truth())
    assert outcome.passed                      # 没有数字可查 ≠ 数字是错的
    assert outcome.report.errors == []
    assert outcome.report.skipped >= len(METRICS)


def test_unverifiable_metric_is_skipped():
    """无动销商品没有周转天数，报了这个数也不该判错。"""
    truth = _truth(turnover_days=None, sales90_qty=0)
    outcome = audit_claims({"turnover_days": 999}, truth)
    assert outcome.passed


def test_unknown_keys_are_reported_not_silently_dropped():
    outcome = audit_claims({"转化率": 3.1, "return_rate": 21.82}, _truth())
    assert outcome.unknown == ["转化率"]
    assert outcome.passed


# --------------------------------------------------------------------------- #
# 键名与单位约定
# --------------------------------------------------------------------------- #
def test_chinese_aliases_are_normalised():
    normalised, unknown = canonicalise({"毛利率": 42.0, "退货率": 21.82, "周转天数": 150})
    assert normalised == {"gross_margin": 42.0, "return_rate": 21.82, "turnover_days": 150}
    assert unknown == []


def test_every_alias_points_at_a_real_metric():
    for alias, key in ALIASES.items():
        assert key in METRICS, alias


def test_truth_metrics_cover_every_metric():
    values = truth_metrics(_truth())
    assert set(values) == set(METRICS)


# --------------------------------------------------------------------------- #
# 数据新鲜度
# --------------------------------------------------------------------------- #
def test_stale_data_warns_but_passes():
    outcome = audit_claims(
        TRUE_CLAIMS,
        _truth(data_as_of=date(2025, 1, 1)),
        now=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    assert outcome.passed
    assert any(issue.check.startswith("freshness(") for issue in outcome.report.warnings)


def test_fresh_data_does_not_warn():
    outcome = audit_claims(
        TRUE_CLAIMS,
        _truth(data_as_of=date(2026, 9, 20)),
        now=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    assert not any(issue.check.startswith("freshness(") for issue in outcome.report.warnings)
