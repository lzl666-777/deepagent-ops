# 业务化分析工具：把《跨境电商选品 SOP》的业务规则固化在代码里
# 供「经营数据分析师」和「审计专员」两个子 agent 使用。
# 设计原则：
#   1. 所有 SQL 只读（SELECT）且参数化，防注入；
#   2. 业务公式（周转率、退货率、降价空间）在 Python 里计算，不交给 LLM 心算；
#   3. SOP 红线（毛利≥30%、退货≤8%、降价毛利≥25%）作为常量固化，与 RAGFlow 知识库一致。

from typing import Annotated

from langchain_core.tools import tool
from mysql.connector import connect, Error

from tools.mysql_tools import get_db_config

# ==================== SOP 业务红线（与 RAGFlow《跨境电商选品 SOP》保持一致） ====================
SOP_MIN_GROSS_MARGIN = 30.0      # 选品毛利底线（%）
SOP_FLOOR_GROSS_MARGIN = 25.0    # 竞品降价跟随毛利底线（%）
SOP_MAX_RETURN_RATE = 8.0        # 退货率红线（%），超过需下架复盘
SLOW_MOVING_DAYS = 60            # 库存周转健康阈值（天），超过视为积压


def _query(sql: str, params: tuple = ()) -> list:
    """执行只读查询，返回结果行列表。"""
    with connect(**get_db_config()) as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()


def _find_products(name_or_sku: str) -> list:
    """按商品名或 SKU 模糊查找商品（参数化，防注入）。"""
    return _query(
        "SELECT product_id, sku, product_name, category, purchase_cost, sale_price, gross_margin "
        "FROM products WHERE product_name LIKE %s OR sku LIKE %s ORDER BY product_id LIMIT 5",
        (f"%{name_or_sku}%", f"%{name_or_sku}%"),
    )


def _data_reference_date():
    """取数据中最新订单日期作为时间基准（演示数据是静态的，不存在真实"今天"）。"""
    rows = _query("SELECT MAX(order_date) FROM orders")
    return rows[0][0] if rows and rows[0][0] else None


def _recent90_sales(product_id: int):
    """返回 (近90天销量, 近90天销售额)，90 天窗口基于数据最新日期往前推。"""
    ref = _data_reference_date()
    if not ref:
        return 0, 0.0
    rows = _query(
        "SELECT COALESCE(SUM(quantity_sold),0), COALESCE(SUM(total_amount),0) FROM orders "
        "WHERE product_id=%s AND order_date >= DATE_SUB(%s, INTERVAL 90 DAY)",
        (product_id, ref),
    )
    qty, amount = rows[0]
    return int(qty), float(amount)


# 1. 库存周转率
@tool
def calc_inventory_turnover(
        product_name: Annotated[str, "商品名称或SKU，例如 '便携榨汁杯' 或 'JB-USB-300'"],
) -> str:
    """计算指定商品的库存周转天数（总库存÷近90天日均销量），判断是否积压（>60天）。"""
    try:
        matches = _find_products(product_name)
        if not matches:
            return f"未找到商品：{product_name}"
        if len(matches) > 1:
            names = "、".join(f"{r[2]}({r[1]})" for r in matches)
            return f"找到多个匹配商品：{names}。请提供更精确的名称或SKU。"

        pid, sku, name, category, _cost, _price, _margin = matches[0]

        inv = _query(
            "SELECT COALESCE(SUM(quantity_on_hand),0), COALESCE(SUM(quantity_in_transit),0) "
            "FROM inventory WHERE product_id=%s", (pid,),
        )
        on_hand, in_transit = inv[0]
        total_inv = int(on_hand) + int(in_transit)

        sales90, _amt = _recent90_sales(pid)
        daily_avg = sales90 / 90.0
        if daily_avg <= 0:
            days_str = "无动销（近90天0销量）"
            flag = "严重积压"
        else:
            days = total_inv / daily_avg
            days_str = f"{days:.1f} 天"
            flag = "积压" if days > SLOW_MOVING_DAYS else "健康"

        return (
            f"商品：{name}（SKU:{sku}，类目:{category}）\n"
            f"总库存：{total_inv}（在库 {on_hand} + 在途 {in_transit}）\n"
            f"近90天销量：{sales90}（日均 {daily_avg:.1f}）\n"
            f"库存周转天数：{days_str}\n"
            f"判定：{flag}（健康阈值 {SLOW_MOVING_DAYS} 天）"
        )
    except Error as e:
        return f"数据库查询失败：{e}"


# 2. 滞销预警
@tool
def list_slow_moving_products(
        threshold_days: Annotated[int, "库存周转天数阈值，默认60天"] = 60,
) -> str:
    """全库扫描，返回库存周转天数超过阈值（或近90天无动销）的积压商品清单。"""
    try:
        products = _query("SELECT product_id, sku, product_name FROM products ORDER BY product_id")
        if not products:
            return "商品表为空"

        results = []
        for pid, sku, name in products:
            inv = _query(
                "SELECT COALESCE(SUM(quantity_on_hand),0), COALESCE(SUM(quantity_in_transit),0) "
                "FROM inventory WHERE product_id=%s", (pid,),
            )
            total_inv = int(inv[0][0]) + int(inv[0][1])
            sales90, _amt = _recent90_sales(pid)
            daily_avg = sales90 / 90.0
            if daily_avg <= 0:
                results.append((name, sku, total_inv, "无动销", "严重积压"))
            else:
                days = total_inv / daily_avg
                if days > threshold_days:
                    results.append((name, sku, total_inv, f"{days:.1f} 天", "积压"))

        if not results:
            return f"没有发现周转天数超过 {threshold_days} 天的积压商品"

        lines = [f"积压商品清单（阈值 {threshold_days} 天）："]
        for name, sku, total_inv, days, flag in results:
            lines.append(f"- {name}（{sku}）：总库存 {total_inv}，周转 {days}，判定 {flag}")
        return "\n".join(lines)
    except Error as e:
        return f"数据库查询失败：{e}"


# 3. 毛利分析
@tool
def calc_gross_margin(
        product_name: Annotated[str, "商品名称或SKU"],
) -> str:
    """计算指定商品的毛利率并判断是否满足选品 SOP 的 30% 红线，给出降价空间（守住30%/25%毛利的最低价）。"""
    try:
        matches = _find_products(product_name)
        if not matches:
            return f"未找到商品：{product_name}"
        if len(matches) > 1:
            names = "、".join(f"{r[2]}({r[1]})" for r in matches)
            return f"找到多个匹配商品：{names}。请提供更精确的名称或SKU。"

        _pid, sku, name, category, cost, price, margin = matches[0]
        margin = float(margin or 0)
        price = float(price or 0)

        ok = f"达标（≥{SOP_MIN_GROSS_MARGIN:.0f}%）" if margin >= SOP_MIN_GROSS_MARGIN \
            else f"不达标（低于 {SOP_MIN_GROSS_MARGIN:.0f}% 红线）"

        # 降价空间：毛利率从当前值降到目标红线时，售价最多还能降多少
        drop30 = price * (margin / 100 - SOP_MIN_GROSS_MARGIN / 100) / (1 - SOP_MIN_GROSS_MARGIN / 100) \
            if margin > SOP_MIN_GROSS_MARGIN else 0
        drop25 = price * (margin / 100 - SOP_FLOOR_GROSS_MARGIN / 100) / (1 - SOP_FLOOR_GROSS_MARGIN / 100) \
            if margin > SOP_FLOOR_GROSS_MARGIN else 0

        return (
            f"商品：{name}（SKU:{sku}，类目:{category}）\n"
            f"采购成本：{cost}，售价：{price}，毛利率：{margin:.2f}%\n"
            f"SOP 红线判定：{ok}\n"
            f"降价空间：守住30%毛利最多可降 {drop30:.2f}（约 {(drop30 / price * 100 if price else 0):.1f}%）；"
            f"守住25%底线最多可降 {drop25:.2f}"
        )
    except Error as e:
        return f"数据库查询失败：{e}"


# 4. 退货率统计
@tool
def calc_return_rate(
        product_name: Annotated[str, "商品名称或SKU"],
) -> str:
    """统计指定商品的退货率（退货量÷总销量），判断是否超过 SOP 的 8% 红线。"""
    try:
        matches = _find_products(product_name)
        if not matches:
            return f"未找到商品：{product_name}"
        if len(matches) > 1:
            names = "、".join(f"{r[2]}({r[1]})" for r in matches)
            return f"找到多个匹配商品：{names}。请提供更精确的名称或SKU。"

        pid, sku, name, category, _c, _p, _m = matches[0]

        rows = _query(
            "SELECT COALESCE(SUM(quantity_sold),0), "
            "COALESCE(SUM(CASE WHEN is_returned=1 THEN quantity_sold ELSE 0 END),0) "
            "FROM orders WHERE product_id=%s", (pid,),
        )
        total_sold, total_returned = rows[0]
        total_sold, total_returned = int(total_sold), int(total_returned)

        if total_sold == 0:
            return f"商品：{name}（SKU:{sku}）：暂无销售记录，无法计算退货率"

        rate = total_returned / total_sold * 100
        flag = f"超红线（>{SOP_MAX_RETURN_RATE:.0f}%，需下架复盘）" if rate > SOP_MAX_RETURN_RATE \
            else f"正常（≤{SOP_MAX_RETURN_RATE:.0f}%）"

        return (
            f"商品：{name}（SKU:{sku}，类目:{category}）\n"
            f"总销量：{total_sold}，退货量：{total_returned}\n"
            f"退货率：{rate:.2f}%\n"
            f"SOP 红线判定：{flag}"
        )
    except Error as e:
        return f"数据库查询失败：{e}"


if __name__ == "__main__":
    # 单工具自测（直接连云端 MySQL）
    print("========== 退货率统计 ==========")
    print(calc_return_rate.invoke({"product_name": "便携榨汁杯"}))
    print("\n========== 毛利分析 ==========")
    print(calc_gross_margin.invoke({"product_name": "无线蓝牙耳机"}))
    print("\n========== 库存周转率 ==========")
    print(calc_inventory_turnover.invoke({"product_name": "宠物吹水机"}))
    print("\n========== 滞销预警 ==========")
    print(list_slow_moving_products.invoke({"threshold_days": 60}))
