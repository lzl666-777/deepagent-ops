"""审计核心：把"复核"从再问一遍模型改成重新算一遍。

为什么要有这个模块
------------------
原来的“审计专员”和数据分析师用同一套工具、同一个模型，再问一遍然后让模型
自己比较两份结论。这不是复核，是第二次意见：模型算错的地方，第二次还会算错。

实测（`evaluation/result.json`）：15 条用例里审计只触发 1 次，决策类 3 条中 2 条
在 480 秒超时，根本没走到审计。

这个模块把“比较”交给代码：模型只做它擅长的事——从报告里把数字读出来；数字对不对
由这里重算，和数据库基准值比对，任何偏差直接判不通过。

分层
----
本模块是**纯函数**：输入 Truth 快照 + claims，输出 AuditReport，不做任何 I/O。
取数在 `tools/audit_tools.py`，那里才连 MySQL、才包成 LangChain 工具。

一个刻意的选择：审计**不 import** 分析师的业务工具（`business_tools`）。
那些工具正是被审计的对象；如果共用同一段查询，一个 bug 会让两边同时算错、
并且互相印证为“一致”。独立实现是这里的价值所在，哪怕多写几行 SQL。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from agent_audit import SKIP, AuditIssue, AuditReport, Auditor, Check, DictSource

# ==================== SOP 业务红线（与《跨境电商选品 SOP》一致） ====================
SOP_MIN_GROSS_MARGIN = 30.0   # 选品毛利底线（%）
SOP_MAX_RETURN_RATE = 8.0     # 退货率红线（%）
#: 业务数据基准日距今超过这么多天就提示“数据可能过期”。
DATA_MAX_AGE_DAYS = 180.0

#: A decision gate is only meaningful when the report supplied these numbers.
#: Missing one is "无法复核", not a clean pass: the model must not be able to
#: avoid the audit by sending an empty or partial ``claims`` dict.
DECISION_REQUIRED_METRICS: Tuple[str, ...] = (
    "gross_margin",
    "return_rate",
    "turnover_days",
)


# --------------------------------------------------------------------------- #
# 基准值
# --------------------------------------------------------------------------- #
@dataclass
class Truth:
    """从数据库重新算出来的一组基准值（单位：金额为元，比率为百分数）。"""

    product_name: str
    sku: str
    category: str
    cost: float
    price: float
    gross_margin: float            # 从成本/售价重算的毛利率（%）
    sales_qty: int
    sales_amount: float
    returned_qty: int
    return_rate: float             # 退货量 / 销量 * 100
    on_hand: int
    in_transit: int
    sales90_qty: int
    turnover_days: Optional[float]  # 总库存 / 近90天日均销量；无动销为 None
    data_as_of: Optional[Any]       # 最新订单日期（date/datetime 均可）


@dataclass(frozen=True)
class Metric:
    """一个可被审计的指标：中文名、相对容差、量纲范围。"""

    key: str
    label: str
    tolerance: float
    scale: Tuple[float, float]


#: 分析和审计之间约定的指标名。比率一律用百分数（21.82 表示 21.82%），
#: 与数据库 `gross_margin` 列和 `business_tools` 的输出保持一致。
METRICS: Dict[str, Metric] = {
    "gross_margin": Metric("gross_margin", "毛利率(%)", 0.01, (0.0, 100.0)),
    "return_rate": Metric("return_rate", "退货率(%)", 0.01, (0.0, 100.0)),
    "turnover_days": Metric("turnover_days", "库存周转天数", 0.02, (0.0, 100000.0)),
    "sales_qty": Metric("sales_qty", "销量", 0.0, (0.0, 1e12)),
    "returned_qty": Metric("returned_qty", "退货量", 0.0, (0.0, 1e12)),
    "sales_amount": Metric("sales_amount", "销售额", 0.01, (0.0, 1e15)),
}

#: 模型可能用中文或别名传指标名，统一映射到 METRICS 的 key。
ALIASES: Dict[str, str] = {
    "gross_margin": "gross_margin", "毛利率": "gross_margin", "毛利": "gross_margin",
    "return_rate": "return_rate", "退货率": "return_rate",
    "turnover_days": "turnover_days", "库存周转天数": "turnover_days", "周转天数": "turnover_days",
    "sales_qty": "sales_qty", "销量": "sales_qty", "总销量": "sales_qty",
    "returned_qty": "returned_qty", "退货量": "returned_qty",
    "sales_amount": "sales_amount", "销售额": "sales_amount", "营收": "sales_amount",
}


def truth_metrics(truth: Truth) -> Dict[str, Optional[float]]:
    """把 Truth 摊平成 {指标名: 基准值}，供比对和 SOP 判定使用。"""
    return {
        "gross_margin": truth.gross_margin,
        "return_rate": truth.return_rate,
        "turnover_days": truth.turnover_days,
        "sales_qty": float(truth.sales_qty),
        "returned_qty": float(truth.returned_qty),
        "sales_amount": truth.sales_amount,
    }


def canonicalise(claims: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """把 claims 的键统一成 METRICS 的 key，返回 (规范化后的 claims, 无法识别的键)。"""
    normalised: Dict[str, Any] = {}
    unknown: List[str] = []
    for raw_key, value in (claims or {}).items():
        key = ALIASES.get(str(raw_key).strip())
        if key is None:
            unknown.append(str(raw_key))
            continue
        normalised[key] = value
    return normalised, unknown


# --------------------------------------------------------------------------- #
# 审计结果
# --------------------------------------------------------------------------- #
@dataclass
class AuditOutcome:
    """一次审计的完整结果：报告 + 规范化后的 claims + 未识别字段 + 基准值。"""

    report: AuditReport
    claims: Dict[str, Any]
    unknown: List[str]
    truth: Truth
    missing_required: List[str] = field(default_factory=list)
    unverifiable_required: List[str] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        """True only when required claims were present and actually checked.

        ``report.passed`` alone is not enough: an empty claims dict has no
        errors, only skips. That is exactly the fail-open path a decision gate
        must not have.
        """
        return (
            self.report.passed
            and self.report.checked > 0
            and not self.missing_required
            and not self.unverifiable_required
        )

    @property
    def passed(self) -> bool:
        """The gate result. Unverified is not a pass."""
        return self.verified

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "verified": self.verified,
            "checked": self.report.checked,
            "skipped": self.report.skipped,
            "missing_required": list(self.missing_required),
            "unverifiable_required": list(self.unverifiable_required),
            "unknown_claims": list(self.unknown),
            "issues": [
                {
                    "check": issue.check,
                    "field": issue.field,
                    "severity": issue.severity,
                    "message": issue.message,
                    "expected": issue.expected,
                    "actual": issue.actual,
                }
                for issue in self.report.issues
            ],
        }


# --------------------------------------------------------------------------- #
# 审计
# --------------------------------------------------------------------------- #
def _to_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").replace("%", "").replace("，", "").strip())
        except ValueError:
            return None
    return None


def _close(claimed: float, actual: float, relative: float) -> bool:
    if actual == 0:
        return abs(claimed) <= 1e-9
    return abs(claimed - actual) / abs(actual) <= relative


def _looks_like_unit_confusion(claimed: float, actual: float) -> bool:
    """一个小数、一个百分数，且恰好差 100 倍 —— 典型的单位混用。"""
    if not (actual and 0 < claimed < 1 < actual):
        return False
    return abs(actual / claimed - 100.0) < 1.0


def _truth_check(metric: Metric, benchmark: Dict[str, Optional[float]]) -> Check:
    """把“报告里的值”和“数据库重算出来的值”比对。"""

    def _run(claims: Dict[str, Any], source: Any):
        claimed = _to_number(claims.get(metric.key))
        if claimed is None:
            return SKIP
        actual = benchmark.get(metric.key)
        if actual is None:
            return SKIP
        if _close(claimed, float(actual), metric.tolerance):
            return None
        hint = "（疑似百分数/小数混用）" if _looks_like_unit_confusion(claimed, float(actual)) else ""
        return AuditIssue(
            f"truth({metric.key})", metric.key,
            f"报告 {claimed:g} ≠ 数据库 {actual:g}{hint}",
            "error", expected=actual, actual=claimed,
        )

    return Check.custom(f"truth({metric.key})", _run)


def audit_claims(
    claims: Dict[str, Any],
    truth: Truth,
    now: Optional[Any] = None,
    required: Tuple[str, ...] = DECISION_REQUIRED_METRICS,
) -> AuditOutcome:
    """审计一份报告里的数字。

    四类检查，严重程度不同：

    ==================  ==========  ==========================================
    检查                 严重程度    说明
    ==================  ==========  ==========================================
    truth(*)            error       报告里的数 ≠ 数据库重算的数
    consistency(毛利)   error       报告自相矛盾（毛利率与成本/售价对不上）
    threshold(SOP)      warning     真值越了红线 —— 这是业务发现，不是算错
    freshness(基准日)   warning     数据过旧
    ==================  ==========  ==========================================

    两个刻意的选择：

    1. SOP 红线只给 warning。越线说明生意有问题，不说明数字是假的。审计的
       ``passed`` 只表示“这些数是真的”，不表示“这个结论是对的”。
    2. 红线按**数据库真值**判定，不按报告里的数。否则分析师把退货率少报成
       8.2% 时，告警会写成“8.2 超过上限 8”——既没用又误导；而真值是 21.82%，
       越线严重得多。

    ``required`` is deliberately fail-closed: a claim set that omits a required
    metric is reported as "无法复核", not as a clean pass. The previous behavior
    allowed ``audit_claims({}, truth)`` to pass with every check skipped, so a
    caller could avoid the audit by sending nothing.
    """
    normalised, unknown = canonicalise(claims)
    benchmark = truth_metrics(truth)
    source = DictSource({
        "cost": truth.cost,
        "price": truth.price,
        "gross_margin": truth.gross_margin,
        "sales_qty": float(truth.sales_qty),
        "returned_qty": float(truth.returned_qty),
        "return_rate": truth.return_rate,
        "turnover_days": truth.turnover_days,
        "sales_amount": truth.sales_amount,
    })

    missing_required = [key for key in required if key not in normalised]
    unverifiable_required = [
        key for key in required
        if key in normalised
        and (benchmark.get(key) is None or _to_number(normalised.get(key)) is None)
    ]

    checks: List[Check] = [
        # 报告内部的算术自洽：毛利率 = (1 - 成本/售价) * 100
        Check.consistency("gross_margin", "(1 - cost / price) * 100", tolerance=0.01),
    ]
    checks += [_truth_check(metric, benchmark) for metric in METRICS.values()]

    audit_input = dict(normalised)
    if truth.data_as_of is not None:
        audit_input["data_as_of"] = truth.data_as_of
        checks.append(Check.freshness("data_as_of", max_age_days=DATA_MAX_AGE_DAYS,
                                      severity="warning", now=now))

    report = Auditor(checks).check(audit_input, source=source)

    # A missing/unverifiable required metric is an audit failure, not a skip.
    # Add it after the truth checks so the specific numeric error remains the
    # first issue when both are present.
    if missing_required:
        report.issues.append(AuditIssue(
            "required_claims", "*",
            "missing required claims: %s" % ", ".join(missing_required),
            "error",
            expected=", ".join(required), actual=", ".join(sorted(normalised)),
        ))
        report.checked += 1
    if unverifiable_required:
        report.issues.append(AuditIssue(
            "unverifiable_claims", "*",
            "required claims could not be verified: %s" % ", ".join(unverifiable_required),
            "error",
        ))
        report.checked += 1

    # SOP 红线按真值判定：要回答的是“这门生意到底越没越线”，
    # 而不是“报告里那个（可能已经算错的）数越没越线”。
    sop_report = Auditor([
        Check.threshold("gross_margin", min=SOP_MIN_GROSS_MARGIN, severity="warning",
                        expect_range=METRICS["gross_margin"].scale),
        Check.threshold("return_rate", max=SOP_MAX_RETURN_RATE, severity="warning",
                        expect_range=METRICS["return_rate"].scale),
    ]).check({key: value for key, value in benchmark.items() if value is not None})

    report.issues.extend(sop_report.issues)
    report.checked += sop_report.checked
    report.skipped += sop_report.skipped

    return AuditOutcome(
        report=report,
        claims=normalised,
        unknown=unknown,
        truth=truth,
        missing_required=missing_required,
        unverifiable_required=unverifiable_required,
    )


# --------------------------------------------------------------------------- #
# 渲染（纯文本，不依赖模型）
# --------------------------------------------------------------------------- #
def render(outcome: AuditOutcome) -> str:
    """把审计结果渲染成模型可以直接引用、用户可以直接读的文本。"""
    gate_checks = {"required_claims", "unverifiable_claims"}
    has_data_error = any(
        issue.severity == "error" and issue.check not in gate_checks
        for issue in outcome.report.issues
    )
    if has_data_error:
        verdict = "不通过"
    elif outcome.missing_required or outcome.unverifiable_required:
        verdict = "无法复核"
    elif outcome.passed:
        verdict = "通过"
    else:
        verdict = "无法复核"
    lines = ["【审计结论】%s" % verdict, "", outcome.report.to_markdown(), ""]

    truth = outcome.truth
    lines.append("【数据库基准值（审计独立重算）】")
    lines.append("| 指标 | 基准值 |")
    lines.append("|---|---|")
    for key, value in truth_metrics(truth).items():
        if value is None:
            lines.append("| %s | 无（近90天无动销） |" % key)
        else:
            lines.append("| %s | %s |" % (key, round(float(value), 4)))
    lines.append("")
    lines.append(
        "口径：商品 %s（%s），成本 %.2f，售价 %.2f，总库存 %d（在库 %d + 在途 %d），"
        "近90天销量 %d，数据基准日 %s。"
        % (truth.product_name, truth.sku, truth.cost, truth.price,
           truth.on_hand + truth.in_transit, truth.on_hand, truth.in_transit,
           truth.sales90_qty, truth.data_as_of)
    )

    if outcome.unknown:
        lines.append("")
        lines.append("注意：以下字段无法识别，未参与审计：%s。可用字段见工具说明。"
                     % "、".join(outcome.unknown))
    if outcome.missing_required or outcome.unverifiable_required:
        lines.append("")
        lines.append(
            "按审计要求：无法复核时不得给出决策；请补齐并重新核对以下字段：%s。"
            % "、".join(outcome.missing_required + outcome.unverifiable_required)
        )
    if not outcome.passed:
        lines.append("")
        lines.append("按审计要求：结论必须为不通过，并把上面的问题清单原文引用给用户。")
    return "\n".join(lines)
