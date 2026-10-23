"""演示：把"再问一遍模型"换成"重算一遍"。

不需要 MySQL、不需要 API Key。基准值取自 `sql/db.sql` 的种子数据（成本 / 售价 /
毛利率是真实值），订单聚合按评测集 B1 的口径（退货率 21.82%）。
真实运行时，这些基准值由 `tools.audit_tools.collect_truth()` 从 MySQL 现查。

运行：
    python examples/audit_demo.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.audit_core import Truth, audit_claims, render  # noqa: E402

TRUTH = Truth(
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


def short(outcome) -> str:
    """一句话摘要：结论 + 每条问题的字段。"""
    verdict = "通过" if outcome.passed else "不通过"
    lines = ["【审计结论】" + verdict]
    for issue in outcome.report.issues:
        lines.append("  [%s] %-22s %s" % (issue.severity, issue.field, issue.message))
    return "\n".join(lines)


def main() -> None:
    print("=" * 72)
    print("基准值（数据库重算）：毛利率 42.00%，退货率 21.82%，周转 150 天，销量 2200")
    print("=" * 72)

    print("\n场景 A：分析师如实报告")
    a = audit_claims(
        {"毛利率": 42.0, "退货率": 21.82, "库存周转天数": 150.0},
        TRUTH,
    )
    print(short(a))
    print("  ↑ 数字是真的 → 数据审计通过；但 21.82% 越过 8% 红线 → 单独告警。")
    print("    红线越线是业务发现，不是数据错误，两件事不能混。")


    print("\n场景 B：分析师把退货率少报了（8.2% 而不是 21.82%）")
    b = audit_claims(
        {"毛利率": 42.0, "退货率": 8.2, "库存周转天数": 150.0},
        TRUTH,
    )
    print(short(b))


    print("\n场景 C：分析师用了小数（0.2182 而不是 21.82）")
    c = audit_claims({"毛利率": 42.0, "退货率": 0.2182, "库存周转天数": 150.0}, TRUTH)
    print(short(c))


    print("\n" + "=" * 72)
    print("同样的输入，交给审计专员子 agent 时它看到的文本：")
    print("=" * 72)
    print(render(b))


if __name__ == "__main__":
    main()
