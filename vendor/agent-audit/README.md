# agent-audit

> Verify what your AI agent claims — catch inconsistent numbers, red-line breaches and stale data before they reach a decision.

## The problem

LLM agents are great at sounding confident and bad at arithmetic. A typical failure:

> "Return rate is 8.2%, revenue is $542,060, margin is 92.4%."

…except the return rate is 34.8%, revenue should be $183,770, and the margin is 45%.

Guardrails check **inputs/outputs for safety**. `agent-audit` checks **facts for correctness**: it recomputes numbers from the components the agent already reported, checks them against your business rules, and flags stale data — deterministically, no second LLM required.

## Quickstart

```bash
pip install agent-audit
```

```python
from agent_audit import Auditor, Check

report = Auditor([
    Check.threshold("return_rate", max=0.08),             # business red line
    Check.consistency("revenue", formula="price * qty"),  # 7.99 * 23000 = 183770
    Check.freshness("market_price_as_of", max_age_days=180),
]).check({
    "return_rate": 0.348,
    "revenue": 542060,
    "price": 7.99,
    "qty": 23000,
    "market_price_as_of": "2025-01-01",
})

print(report.passed)          # False
print(report.to_markdown())
```

Output:

```
## Audit Report

**Result:** FAIL
**Checked:** 3 | **Skipped:** 0 | **Issues:** 3

| Check | Field | Severity | Message |
|---|---|---|---|
| threshold(return_rate) | return_rate | error | value 0.348 exceeds max 0.08 |
| consistency(revenue) | revenue | error | 542060 != price * qty (183770) |
| freshness(market_price_as_of) | market_price_as_of | warning | data is 659 days old (max 180) |
```

## Checks

| Check | What it does |
|---|---|
| `Check.threshold(field, min=, max=, expect_range=)` | Fails when a numeric claim is outside a bound (SOP red lines, budget caps…). `expect_range` declares the field's scale, so a value from another scale is an error instead of a silent pass |
| `Check.consistency(target, formula, tolerance=0.01)` | Recomputes `formula` from the other claims and compares it to `target` |
| `Check.freshness(field, max_age_days)` | Warns when a date / timestamp claim is stale |
| `Check.custom(name, fn)` | Your own `fn(claims, source) -> None \| AuditIssue \| SKIP` |

A check returns one of three things:

- `None` → the claim passed
- `AuditIssue` → the claim failed (`severity="error"`) or is suspicious (`severity="warning"`)
- `SKIP` → the claim could not be verified (missing data)

`report.passed` is `True` only when there are no `error`-severity issues.

## Ground-truth source

For `consistency`, formula components missing from the claims are fetched from an optional `source`:

```python
from agent_audit import Auditor, Check, DictSource

report = Auditor([
    Check.consistency("revenue", formula="price * qty"),
]).check({"revenue": 100}, source=DictSource({"price": 10, "qty": 10}))

assert report.passed
```

Any object with a `get(field)` method works — e.g. a thin wrapper around SQL:

```python
class SqlSource:
    def __init__(self, cursor):
        self.cur = cursor

    def get(self, field):
        self.cur.execute(f"SELECT {field} FROM metrics WHERE id = %s", (1,))
        return self.cur.fetchone()[0]
```

## Safety

- **No code execution in formulas.** `consistency` expressions are parsed with a restricted AST walker: numeric constants, names and `+ - * / ** %` only. Calls, attributes, indexing and non-numeric constants are rejected, and the exponent of `**` is capped at 64 — a model-generated formula cannot execute code, and cannot pin a worker either. (Tests: `tests/test_hardening.py`.)
- **A broken check never crashes the audit.** Exceptions raised inside a check become an `error` issue instead of propagating, and a check returning something other than `None | AuditIssue | SKIP` is coerced into an error rather than breaking `report.passed`.
- **A broken formula fails the audit, not the claim.** A formula that cannot be
  evaluated is reported as an `error` with field `*` (an audit configuration
  error), so a typo in a rule can never silently become a `SKIP` and a clean
  pass. It is deliberately not reported as "the data is wrong".

### Units

`agent-audit` does not infer units. `0.348` and `34.8` are both valid numbers; which
one a field means is a property of *your* schema. Declare it with `expect_range`
and, when you have ground truth, compare against it — that comparison is what
catches a report and its source expressed in different units.

## Why not X?

- **Guardrails / output filters** check whether text is *safe*. `agent-audit` checks whether numbers are *true*.
- **LLM-as-judge** is another model giving an opinion. `agent-audit` recomputes deterministically wherever it can.

They compose well: LLM-as-judge for open-ended prose, `agent-audit` for quantitative claims.

## Development

```bash
git clone https://github.com/<you>/agent-audit.git
cd agent-audit
pip install -e ".[dev]"
pytest -q
python examples/quickstart.py
```

No runtime dependencies — standard library only.

## License

MIT
