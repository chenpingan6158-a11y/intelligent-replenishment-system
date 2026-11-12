"""预测引擎单元测试（纯函数，不依赖数据库）。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services.forecast import SuggestionInput, backtest, build_forecast, compute_suggestion, stockout_days

TODAY = date(2026, 11, 11)


def make_history(days: int = 28, base: int = 1000, weekend_boost: float = 1.4) -> dict:
    """构造带星期周期的历史数据。"""
    history = {}
    for i in range(1, days + 1):
        d = TODAY - timedelta(days=i)
        factor = weekend_boost if d.weekday() >= 4 else 1.0
        history[d] = int(base * factor)
    return history


def default_input(**overrides) -> SuggestionInput:
    kwargs = dict(
        history=make_history(),
        on_hand=10000,
        locked=0,
        in_transit=0,
        lead_time_days=2,
        order_cycle_days=3,
        moq_base=5000,
        pack_multiple_base=5000,
        max_stock_base=0,
        z=1.65,
        today=TODAY,
    )
    kwargs.update(overrides)
    return SuggestionInput(**kwargs)


class TestWeekdayFactors:
    def test_weekend_higher(self):
        fc = build_forecast(default_input())
        assert fc.weekday_factors[4] > 1.0  # 周五
        assert fc.weekday_factors[0] < fc.weekday_factors[5]  # 周一 < 周六

    def test_empty_history_all_one(self):
        fc = build_forecast(default_input(history={}))
        assert fc.cold_start is True
        assert fc.weekday_factors == [1.0] * 7

    def test_single_day_history_returns_seven_valid_factors(self):
        history = {TODAY - timedelta(days=1): 800}
        factors = build_forecast(default_input(history=history)).weekday_factors
        assert len(factors) == 7
        assert all(factor > 0 for factor in factors)

    def test_all_zero_consumption_returns_neutral_factors(self):
        history = {TODAY - timedelta(days=i): 0 for i in range(1, 15)}
        factors = build_forecast(default_input(history=history)).weekday_factors
        assert factors == [1.0] * 7

    def test_unaligned_history_endpoints_returns_seven_valid_factors(self):
        history = {
            TODAY - timedelta(days=i): 800 + i * 10
            for i in range(1, 11)
        }
        factors = build_forecast(default_input(history=history)).weekday_factors
        assert len(factors) == 7
        assert all(factor > 0 for factor in factors)


class TestSuggestion:
    def test_zero_stock_suggests_replenishment(self):
        sug = compute_suggestion(default_input(on_hand=0))
        assert sug.suggest_qty_base > 0
        assert sug.needs_reorder is True
        # 覆盖期约 5 天 × ~1100/天 ≈ 5500，向上取整到 5000 的倍数
        assert sug.suggest_qty_base % 5000 == 0

    def test_rich_stock_no_replenishment(self):
        sug = compute_suggestion(default_input(on_hand=1_000_000))
        assert sug.suggest_qty_base == 0
        assert "无需订货" in sug.reason

    def test_moq_respected(self):
        sug = compute_suggestion(default_input(on_hand=0, moq_base=20000, pack_multiple_base=5000))
        assert sug.suggest_qty_base >= 20000

    def test_pack_multiple_rounding_up(self):
        sug = compute_suggestion(
            default_input(on_hand=0, pack_multiple_base=7000, moq_base=0)
        )
        assert sug.suggest_qty_base % 7000 == 0

    def test_max_stock_cap(self):
        sug = compute_suggestion(default_input(on_hand=0, max_stock_base=30000))
        assert sug.suggest_qty_base <= 30000

    def test_locked_and_in_transit_reduce_need(self):
        base_sug = compute_suggestion(default_input(on_hand=20000))
        locked_sug = compute_suggestion(default_input(on_hand=20000, locked=20000))
        transit_sug = compute_suggestion(default_input(on_hand=20000, in_transit=20000))
        assert locked_sug.suggest_qty_base >= base_sug.suggest_qty_base
        assert transit_sug.suggest_qty_base <= base_sug.suggest_qty_base

    def test_detail_is_explainable(self):
        sug = compute_suggestion(default_input(on_hand=0))
        detail = sug.detail
        for key in ("onHand", "inTransit", "forecastDemand", "safetyStock", "rop", "coverageDays"):
            assert key in detail
        # 可用 = 现存 - 锁定
        assert detail["available"] == detail["onHand"] - detail["locked"]

    def test_safety_stock_positive_with_variance(self):
        fc = build_forecast(default_input())
        assert fc.safety_stock > 0
        assert fc.rop > fc.mu_lead_time


class TestColdStart:
    def test_few_days_degrades(self):
        history = {TODAY - timedelta(days=i): 800 for i in range(1, 5)}
        sug = compute_suggestion(default_input(history=history, on_hand=0))
        assert sug.detail["coldStart"] is True
        assert sug.suggest_qty_base > 0

    def test_no_history_zero_suggestion(self):
        sug = compute_suggestion(default_input(history={}, on_hand=0))
        assert sug.suggest_qty_base == 0


class TestStockoutDays:
    def test_immediate_stockout(self):
        assert stockout_days(default_input(on_hand=0)) is not None

    def test_no_stockout(self):
        assert stockout_days(default_input(on_hand=10_000_000)) is None


class TestBacktest:
    def test_backtest_runs_and_returns_metrics(self):
        history = make_history(days=60, base=1000)
        result = backtest(
            history,
            policy={"lead_time_days": 2, "order_cycle_days": 3, "moq_base": 5000,
                    "pack_multiple_base": 5000, "max_stock_base": 0, "history_days": 28},
            start=TODAY - timedelta(days=30),
            end=TODAY - timedelta(days=1),
            initial_stock=10000,
        )
        assert result["days"] == 30
        assert 0 <= result["shortageRate"] <= 1
        assert result["orderCount"] > 0
        assert result["avgStock"] >= 0
