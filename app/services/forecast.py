"""智能补货预测引擎（纯函数实现，无数据库依赖，便于单元测试与回测）。

算法链路：
  1. 基线需求 d̄        = 近 N 天有效消耗 / 有效天数
  2. 星期因子 w(dow)    = 该星期几平均消耗 / 全期平均（餐饮强周期）
  3. 趋势修正           = 近 N 天线性回归斜率归一化，限制在 ±2%/天
  4. 日预测 f(t)        = d̄ × (1 + trend×k) × w(dow) × 促销因子
  5. 提前期需求 μ_L     = Σ f(t)，t 覆盖提前期
  6. 安全库存 SS        = Z × σ × √L
  7. 补货点 ROP         = μ_L + SS
  8. 建议订货量 Q       = 覆盖期需求 + SS − 可用库存 − 在途，按 MOQ / 包装倍数取整，受最大库存约束
  冷启动：有效天数 < 7 时降级为「近 7 天日均 × 覆盖天数」。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

MIN_EFFECTIVE_DAYS = 7
CLAMP_WEEKDAY = (0.5, 2.0)
CLAMP_TREND = (-0.02, 0.02)


@dataclass
class ForecastResult:
    baseline: float
    weekday_factors: list[float]
    trend: float
    daily_forecast: list[float]
    mu_lead_time: float
    sigma: float
    safety_stock: float
    rop: float
    coverage_demand: float
    cold_start: bool
    effective_days: int


@dataclass
class SuggestionInput:
    history: dict[date, int]          # 日期 -> 消耗（最小单位）
    on_hand: int                     # 现存
    locked: int                      # 锁定量
    in_transit: int                  # 在途（已下单未到货）
    lead_time_days: int
    order_cycle_days: int
    moq_base: int
    pack_multiple_base: int
    max_stock_base: int
    z: float = 1.65
    today: date = field(default_factory=date.today)
    history_days: int = 28


@dataclass
class Suggestion:
    suggest_qty_base: int
    available_base: int
    detail: dict
    reason: str
    forecast: ForecastResult
    needs_reorder: bool


# ------------------------------------------------------------------ 基础统计
def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mu = _mean(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (len(values) - 1))


def _slope(points: list[tuple[int, float]]) -> float:
    """最小二乘斜率。points: (x, y)"""
    n = len(points)
    if n < 2:
        return 0.0
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0
    return (n * sxy - sx * sy) / denom


def weekday_factors(history: dict[date, int], fallback: float = 1.0) -> list[float]:
    """按星期几（0=周一）计算需求因子。样本不足的星期回落到 1.0。"""
    buckets: dict[int, list[float]] = {i: [] for i in range(7)}
    for d, qty in history.items():
        buckets[d.weekday()].append(float(qty))
    overall = _mean([float(v) for v in history.values()])
    if overall <= 0:
        return [fallback] * 7
    factors = []
    for i in range(7):
        if len(buckets[i]) < 2:
            factors.append(fallback)
        else:
            ratio = _mean(buckets[i]) / overall
            factors.append(min(max(ratio, CLAMP_WEEKDAY[0]), CLAMP_WEEKDAY[1]))
    return factors


def build_forecast(inp: SuggestionInput) -> ForecastResult:
    end = inp.today - timedelta(days=1)
    start = end - timedelta(days=inp.history_days - 1)
    window: dict[date, int] = {}
    cursor = start
    while cursor <= end:
        window[cursor] = int(inp.history.get(cursor, 0))
        cursor += timedelta(days=1)

    positive = [v for v in window.values() if v > 0]
    effective_days = len(positive)
    cold_start = effective_days < MIN_EFFECTIVE_DAYS

    if cold_start:
        # 冷启动：用最近 7 天（含零）均值，缺数据则 0
        recent = [window.get(end - timedelta(days=i), 0) for i in range(7)]
        baseline = _mean([float(v) for v in recent])
        factors = [1.0] * 7
        trend = 0.0
        sigma = _stdev([float(v) for v in recent])
    else:
        baseline = sum(positive) / len(positive)
        factors = weekday_factors(window)
        points = [(i, float(window[start + timedelta(days=i)])) for i in range((end - start).days + 1)]
        raw_slope = _slope(points)
        trend = 0.0 if baseline <= 0 else min(max(raw_slope / baseline, CLAMP_TREND[0]), CLAMP_TREND[1])
        sigma = _stdev([float(v) for v in window.values()])

    # 逐日预测（覆盖提前期 + 一个订货周期）
    horizon = max(inp.lead_time_days, 0) + max(inp.order_cycle_days, 1)
    daily: list[float] = []
    for k in range(1, horizon + 1):
        target = inp.today + timedelta(days=k)
        base_t = baseline * (1 + trend * k)
        daily.append(max(0.0, base_t * factors[target.weekday()]))

    lead = max(inp.lead_time_days, 0)
    mu_lead = sum(daily[:lead])
    sigma_lead = sigma * math.sqrt(lead) if lead > 0 else 0.0
    safety = inp.z * sigma_lead
    rop = mu_lead + safety
    coverage = sum(daily)

    return ForecastResult(
        baseline=round(baseline, 2),
        weekday_factors=[round(f, 3) for f in factors],
        trend=round(trend, 4),
        daily_forecast=[round(x, 1) for x in daily],
        mu_lead_time=round(mu_lead, 1),
        sigma=round(sigma, 1),
        safety_stock=round(safety, 1),
        rop=round(rop, 1),
        coverage_demand=round(coverage, 1),
        cold_start=cold_start,
        effective_days=effective_days,
    )


def _round_up_to(value: float, multiple: int) -> int:
    if multiple <= 1:
        return int(math.ceil(value))
    return int(math.ceil(value / multiple) * multiple)


def compute_suggestion(inp: SuggestionInput) -> Suggestion:
    fc = build_forecast(inp)
    available = inp.on_hand - inp.locked
    raw = fc.coverage_demand + fc.safety_stock - available - inp.in_transit

    needs_reorder = available < fc.rop or raw > 0
    qty = 0
    if needs_reorder and raw > 0:
        qty = _round_up_to(raw, max(inp.pack_multiple_base, 1))
        if inp.moq_base > 0:
            qty = max(qty, inp.moq_base)
        if inp.max_stock_base > 0:
            qty = min(qty, max(0, inp.max_stock_base - available - inp.in_transit))

    detail = {
        "onHand": inp.on_hand,
        "locked": inp.locked,
        "available": available,
        "inTransit": inp.in_transit,
        "forecastDemand": fc.coverage_demand,
        "leadTimeDemand": fc.mu_lead_time,
        "safetyStock": fc.safety_stock,
        "rop": fc.rop,
        "baseline": fc.baseline,
        "trend": fc.trend,
        "coldStart": fc.cold_start,
        "effectiveDays": fc.effective_days,
        "weekdayFactors": fc.weekday_factors,
        "coverageDays": max(inp.lead_time_days, 0) + max(inp.order_cycle_days, 1),
    }

    if qty > 0:
        reason = (
            f"可用库存 {available}，低于补货点 {fc.rop:.0f}；"
            f"覆盖 {detail['coverageDays']} 天预计需 {fc.coverage_demand:.0f}，"
            f"加安全库存 {fc.safety_stock:.0f}，扣除在途 {inp.in_transit}，建议补 {qty}"
        )
    elif needs_reorder:
        reason = f"可用库存 {available} 低于补货点 {fc.rop:.0f}，但在途已覆盖需求，暂不追加"
    else:
        reason = f"可用库存 {available} 高于补货点 {fc.rop:.0f}，无需订货"

    return Suggestion(
        suggest_qty_base=qty,
        available_base=available,
        detail=detail,
        reason=reason,
        forecast=fc,
        needs_reorder=needs_reorder,
    )


def stockout_days(inp: SuggestionInput) -> int | None:
    """按预测消耗推算几天后断货；不会断货返回 None。"""
    fc = build_forecast(inp)
    available = inp.on_hand - inp.locked
    if fc.baseline <= 0:
        return None
    remaining = float(available)
    for idx, daily in enumerate(fc.daily_forecast, start=1):
        remaining -= daily
        if remaining < 0:
            return idx
    if remaining <= 0:
        return len(fc.daily_forecast) + 1
    return None


def backtest(
    history: dict[date, int],
    *,
    policy: dict,
    start: date,
    end: date,
    initial_stock: int | None = None,
) -> dict:
    """滚动回测：逐日按建议补货，统计缺货天数与平均库存。"""
    horizon_days = (end - start).days + 1
    stock = initial_stock if initial_stock is not None else int(policy.get("moq_base", 0)) * 2
    pipeline: dict[date, int] = {}
    shortages = 0
    stock_sum = 0
    order_count = 0

    day = start
    while day <= end:
        stock += pipeline.pop(day, 0)
        demand = int(history.get(day, 0))
        in_transit = sum(pipeline.values())
        window = {d: history.get(d, 0) for d in history if d < day}
        sub = {k: window[k] for k in sorted(window)[-policy.get("history_days", 28):]}
        inp = SuggestionInput(
            history=sub,
            on_hand=stock,
            locked=0,
            in_transit=in_transit,
            lead_time_days=policy.get("lead_time_days", 2),
            order_cycle_days=policy.get("order_cycle_days", 3),
            moq_base=policy.get("moq_base", 1),
            pack_multiple_base=policy.get("pack_multiple_base", 1),
            max_stock_base=policy.get("max_stock_base", 0),
            today=day,
        )
        sug = compute_suggestion(inp)
        if sug.suggest_qty_base > 0:
            arrive = day + timedelta(days=policy.get("lead_time_days", 2))
            pipeline[arrive] = pipeline.get(arrive, 0) + sug.suggest_qty_base
            order_count += 1
        if stock < demand:
            shortages += 1
            stock = 0
        else:
            stock -= demand
        stock_sum += stock
        day += timedelta(days=1)

    return {
        "days": horizon_days,
        "shortageDays": shortages,
        "shortageRate": round(shortages / horizon_days, 4),
        "avgStock": round(stock_sum / horizon_days, 1),
        "orderCount": order_count,
    }
