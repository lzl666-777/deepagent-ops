"""把审计核心接到真实数据上，并暴露成一个 agent 工具。

本文件只做两件事：从 MySQL 取基准值、把结果包成工具。
判断逻辑和渲染全部在 `tools/audit_core.py`，那里不碰数据库，因此可以离线测试。
"""

from __future__ import annotations

import json
from typing import Any, Dict

from langchain_core.tools import tool
from mysql.connector import connect

from tools.audit_core import DECISION_REQUIRED_METRICS, Truth, audit_claims, render
from tools.mysql_tools import get_db_config

MAX_PRODUCT_MATCHES = 5


# --------------------------------------------------------------------------- #
# 取数
# --------------------------------------------------------------------------- #
def collect_truth(product_name: str) -> Truth:
    """重新查库，算出审计用的基准值。

    一次连接、四条查询。审计要独立于分析师的实现（见 audit_core 的模块说明），
    所以这里自己写 SQL，不复用 `business_tools` 里的查询。

    :raises LookupError: 商品不存在或有歧义
    """
    name = (product_name or "").strip()
    if not name:
        raise LookupError("商品名不能为空")

    with connect(**get_db_config()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT product_id, sku, product_name, category, purchase_cost, sale_price, gross_margin "
                "FROM products WHERE product_name LIKE %s OR sku LIKE %s ORDER BY product_id LIMIT %s",
                ("%" + name + "%", "%" + name + "%", MAX_PRODUCT_MATCHES),
            )
            rows = cur.fetchall()
            if not rows:
                raise LookupError("未找到商品：%s" % name)
            if len(rows) > 1:
                candidates = "、".join("%s(%s)" % (row[2], row[1]) for row in rows)
                raise LookupError("匹配到多个商品：%s，请提供更精确的名称或 SKU" % candidates)

            product_id, sku, product_name, category, cost, price, margin = rows[0]

            cur.execute(
                "SELECT COALESCE(SUM(quantity_on_hand),0), COALESCE(SUM(quantity_in_transit),0) "
                "FROM inventory WHERE product_id=%s",
                (product_id,),
            )
            on_hand, in_transit = cur.fetchone()

            cur.execute(
                "SELECT COALESCE(SUM(quantity_sold),0), COALESCE(SUM(total_amount),0), "
                "COALESCE(SUM(CASE WHEN is_returned=1 THEN quantity_sold ELSE 0 END),0), "
                "MAX(order_date) FROM orders WHERE product_id=%s",
                (product_id,),
            )
            sold, amount, returned, data_as_of = cur.fetchone()

            sales90 = 0
            if data_as_of is not None:
                # 与分析师同口径：以数据最新日期为基准往前推 90 天
                cur.execute(
                    "SELECT COALESCE(SUM(quantity_sold),0) FROM orders "
                    "WHERE product_id=%s AND order_date >= DATE_SUB(%s, INTERVAL 90 DAY)",
                    (product_id, data_as_of),
                )
                sales90 = cur.fetchone()[0]

    total_stock = int(on_hand) + int(in_transit)
    sales_qty = int(sold)
    returned_qty = int(returned)
    # mysql-connector returns SUM(...) as Decimal; Decimal / float raises.
    sales90 = int(sales90 or 0)
    daily_avg = sales90 / 90.0
    # Recompute the margin from cost/price instead of trusting the stored
    # column. The audit is supposed to be independent of the data it checks;
    # if the stored margin is stale, using it as "truth" would flag a correct
    # report and bless an incorrect one.
    cost_f = float(cost or 0)
    price_f = float(price or 0)
    computed_margin = ((1 - cost_f / price_f) * 100.0) if price_f else float(margin or 0)
    return Truth(
        product_name=product_name,
        sku=sku,
        category=category or "",
        cost=cost_f,
        price=price_f,
        gross_margin=computed_margin,
        sales_qty=sales_qty,
        sales_amount=float(amount or 0),
        returned_qty=returned_qty,
        return_rate=(returned_qty / sales_qty * 100.0) if sales_qty else 0.0,
        on_hand=int(on_hand),
        in_transit=int(in_transit),
        sales90_qty=int(sales90),
        turnover_days=(total_stock / daily_avg) if daily_avg > 0 else None,
        data_as_of=data_as_of,
    )


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def _parse_claims(raw: Any) -> tuple[Dict[str, Any], str]:
    """模型有时会把 dict 序列化成 JSON 字符串传进来。

    Returns ``(claims, error)``. An empty dict is not a valid claim set for a
    decision gate: the caller must not be able to skip verification by sending
    nothing or malformed JSON.
    """
    if raw is None:
        return {}, "claims 为空"
    if isinstance(raw, dict):
        return raw, "" if raw else "claims 为空"
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}, "claims 不是合法 JSON"
        if not isinstance(parsed, dict):
            return {}, "claims 必须是 JSON 对象"
        return parsed, "" if parsed else "claims 为空"
    return {}, "claims 必须是 dict 或 JSON 对象"


@tool
def verify_claims(product_name: str, claims: dict) -> str:
    """用数据库重算并核对报告里的关键数字（确定性审计，不靠模型心算）。

    在任何给出 GO/NO-GO、定价、备货建议之前调用它。数据分析师报上来的每个
    关键数字都放进 claims；本工具会重新查库、重新计算，逐项比对。

    Args:
        product_name: 商品名称或 SKU，例如 '便携榨汁杯' 或 'JB-USB-300'。
        claims: 报告中出现的数字，键可用中文或英文：
            - 毛利率 / gross_margin
            - 退货率 / return_rate
            - 库存周转天数 / turnover_days
            - 销量 / sales_qty、退货量 / returned_qty、销售额 / sales_amount
            比率一律用百分数（21.82 表示 21.82%）。没有把握的项不要填。

    Returns:
        审计结论（通过 / 不通过）、逐条问题清单（含数据库基准值）、基准值明细。
    """
    parsed, parse_error = _parse_claims(claims)
    if parse_error:
        return (
            "【审计结论】无法复核\n\n"
            "审计输入无效：%s。\n"
            "按审计要求：无法复核时不得给出决策，结论必须为不通过。" % parse_error
        )
    try:
        truth = collect_truth(product_name)
    except LookupError as exc:
        return (
            "【审计结论】无法复核\n\n"
            "无法取到数据库基准值：%s。\n"
            "按审计要求：无法复核时不得给出决策，结论必须为不通过。" % exc
        )
    except Exception as exc:  # 数据库不可用时不要让整个 agent 崩掉
        return (
            "【审计结论】无法复核\n\n"
            "数据库不可用：%s: %s。\n"
            "按审计要求：无法复核时不得给出决策，结论必须为不通过。"
            % (type(exc).__name__, exc)
        )
    return render(audit_claims(
        parsed, truth, required=DECISION_REQUIRED_METRICS,
    ))


if __name__ == "__main__":
    # 需要可用的 MySQL；只做人工冒烟
    print(verify_claims.invoke({
        "product_name": "便携榨汁杯",
        "claims": {"毛利率": 42.0, "退货率": 21.82},
    }))
