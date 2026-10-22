"""
P3 评测集：15 条跨境电商业务问答 + 自动判分

用法（项目根目录）：
    python -m evaluation.evaluate                 # 跑全部 15 条
    python -m evaluation.evaluate --ids B1,B5,C2  # 只跑指定用例（复跑失败项用）

输出：
    evaluation/result.json（每条结果 + 汇总；每跑完一条就增量保存，中途崩溃也不丢）

判分方式（规则匹配，可复现）：
    pass_if：每个 fact 是一组可接受表述，至少命中一个才算该 fact 成立；所有 fact 成立才算通过
    fail_if：出现任一禁止内容（幻觉/错误结论）即判失败
    数字比较前会做归一化（去掉逗号/空格），避免 "7,500" vs "7500" 这类误判
"""
import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ==================== 评测集（ground truth 来自 tools/business_tools.py 实测） ====================
CASES = [
    # ---------- A. 数据查询（4） ----------
    {"id": "A1", "cat": "数据查询", "q": "数据库里有哪些商品？列出名称和类目。",
     "pass_if": [["便携榨汁杯"], ["无线蓝牙耳机"], ["宠物吹水机"], ["筋膜枪"]], "fail_if": []},
    {"id": "A2", "cat": "数据查询", "q": "毛利率最高的商品是哪个？毛利率多少？",
     "pass_if": [["宠物吹水机"], ["55"]], "fail_if": []},
    {"id": "A3", "cat": "数据查询", "q": "毛利率最低的商品是哪个？",
     "pass_if": [["无线蓝牙耳机"], ["28"]], "fail_if": []},
    {"id": "A4", "cat": "数据查询", "q": "数据库里有几个商品处于'在售'状态？",
     "pass_if": [["7", "七"]], "fail_if": []},

    # ---------- B. 业务计算（5） ----------
    {"id": "B1", "cat": "业务计算", "q": "便携榨汁杯的退货率是多少？是否超过 SOP 红线？",
     "pass_if": [["21.82", "21.8"], ["超红线", "超过", "超标", "超出", "高于"]],
     "fail_if": ["退货率正常", "未超"]},
    {"id": "B2", "cat": "业务计算", "q": "磁吸手机支架的库存周转天数是多少？健康吗？",
     "pass_if": [["27"], ["健康"]], "fail_if": []},
    {"id": "B3", "cat": "业务计算", "q": "无线蓝牙耳机的毛利率是否达标？守住25%底线最多能降多少钱？",
     "pass_if": [["28"], ["不达标", "低于", "未达"]], "fail_if": []},
    {"id": "B4", "cat": "业务计算", "q": "哪些商品库存周转超过 60 天？",
     "pass_if": [["便携榨汁杯"], ["宠物吹水机"], ["筋膜枪"]], "fail_if": []},
    {"id": "B5", "cat": "业务计算", "q": "宠物吹水机的库存周转天数是多少？",
     "pass_if": [["7500"]], "fail_if": []},

    # ---------- C. 决策（3，会触发审计） ----------
    {"id": "C1", "cat": "决策", "q": "评估一下便携榨汁杯值不值得继续做，给出 GO/NO-GO 建议。",
     "pass_if": [["NO-GO", "不通过", "不建议"]], "fail_if": []},
    {"id": "C2", "cat": "决策", "q": "磁吸手机支架值得备货吗？",
     "pass_if": [["不建议", "不通过", "不值得", "否", "谨慎"]], "fail_if": []},
    {"id": "C3", "cat": "决策", "q": "无线蓝牙耳机要不要跟进竞品降价？",
     "pass_if": [["不建议", "不跟", "否", "不宜"]], "fail_if": []},

    # ---------- D. 边界（3，考察是否幻觉） ----------
    {"id": "D1", "cat": "边界", "q": "小米15手机的价格是多少？",
     "pass_if": [["没有", "未找到", "不存在", "无此", "查不到", "不包含"]],
     "fail_if": ["5999", "4999", "3999"]},
    {"id": "D2", "cat": "边界", "q": "我们商品的亚马逊广告花费是多少？",
     "pass_if": [["没有", "不存在", "无数据", "未包含", "未提供", "查不到"]], "fail_if": []},
    {"id": "D3", "cat": "边界", "q": "帮我预测下个月便携榨汁杯的销量。",
     "pass_if": [["无法", "不能", "不具备", "没有预测", "基于历史", "仅供参考"]], "fail_if": []},
]


def _norm(s: str) -> str:
    """归一化：去掉逗号、空格、全角空格，避免数字/关键词格式差异导致误判"""
    return re.sub(r"[,，\s\u00a0]", "", s or "")


def judge(answer: str, case: dict):
    """返回 (是否通过, 未命中/违规说明)"""
    ans = _norm(answer)
    for bad in case.get("fail_if", []):
        if _norm(bad) in ans:
            return False, f"出现禁止内容: {bad}"
    missed = []
    for fact in case.get("pass_if", []):
        if not any(_norm(v) in ans for v in fact):
            missed.append(" / ".join(fact))
    if missed:
        return False, "未命中: " + "; ".join(missed)
    return True, ""


async def run_case(agent, case: dict, timeout: float = 480):
    """运行单条用例，返回 (调用的子agent列表, 最终回答)；异常不抛出，转成 [ERROR] 文本"""
    called, final = [], ""

    async def _run():
        nonlocal final
        async for chunk in agent.astream({"messages": [{"role": "user", "content": case["q"]}]}):
            for key, value in chunk.items():
                if not value or "messages" not in value:
                    continue
                msg = value["messages"][-1]
                tcs = getattr(msg, "tool_calls", None)
                content = getattr(msg, "content", None)
                if tcs:
                    for tc in tcs:
                        if tc.get("name") == "task":
                            st = (tc.get("args") or {}).get("subagent_type")
                            if st and st not in called:
                                called.append(st)
                elif content and key == "model":
                    final = str(content)

    try:
        await asyncio.wait_for(_run(), timeout=timeout)
    except asyncio.TimeoutError:
        return called, "[TIMEOUT]"
    except Exception as e:
        return called, f"[ERROR] {type(e).__name__}: {e}"
    return called, final


def _save(out: Path, results, summary=None):
    out.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")


async def main():
    from agent.main_agent import main_agent

    # 可选：--ids B1,B5,C2 只跑指定用例
    ids = None
    if "--ids" in sys.argv:
        ids = set(sys.argv[sys.argv.index("--ids") + 1].split(","))
    cases = [c for c in CASES if ids is None or c["id"] in ids]

    out = Path(__file__).resolve().parent / "result.json"
    results = []
    t_all = time.time()
    for i, case in enumerate(cases, 1):
        t0 = time.time()
        called, final = await run_case(main_agent, case)
        ok, reason = judge(final, case)
        dt = time.time() - t0
        results.append({
            "id": case["id"], "cat": case["cat"], "question": case["q"],
            "passed": ok, "reason": reason, "called_agents": called,
            "audit_triggered": "审计专员" in called, "elapsed_s": round(dt, 1),
            "answer": final[:2000],
        })
        mark = "PASS" if ok else "FAIL"
        print(f"[{i:02d}/{len(cases)}] {case['id']} {case['cat']} -> {mark} ({dt:.1f}s) agents={called}")
        if not ok:
            print(f"        原因: {reason}")
        _save(out, results)  # 每条都增量保存

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    halluc = sum(1 for r in results if "禁止内容" in (r["reason"] or ""))
    decision = [r for r in results if r["cat"] == "决策"]
    audit_hit = sum(1 for r in decision if r["audit_triggered"])

    summary = {
        "total": total,
        "passed": passed,
        "accuracy": round(passed / total * 100, 1) if total else 0,
        "hallucination_cases": halluc,
        "hallucination_rate": round(halluc / total * 100, 1) if total else 0,
        "decision_cases": len(decision),
        "audit_triggered": audit_hit,
        "audit_trigger_rate": round(audit_hit / len(decision) * 100, 1) if decision else 0,
        "elapsed_s": round(time.time() - t_all, 1),
    }

    print("\n" + "=" * 60)
    print("评测汇总")
    print("=" * 60)
    print(f"总用例: {summary['total']}  通过: {summary['passed']}  准确率: {summary['accuracy']}%")
    print(f"幻觉用例: {summary['hallucination_cases']}  幻觉率: {summary['hallucination_rate']}%")
    print(f"决策用例审计触发率: {summary['audit_trigger_rate']}% ({audit_hit}/{len(decision)})")
    print(f"总耗时: {summary['elapsed_s']}s")

    _save(out, results, summary)
    print(f"\n结果已保存: {out}")


if __name__ == "__main__":
    asyncio.run(main())
