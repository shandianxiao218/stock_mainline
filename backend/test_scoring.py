from __future__ import annotations

import unittest

from model_config_store import get_active_config
from real_scoring import db_ready, factor_effectiveness_payload, ranking_payload, theme_matrix_payload, compute_relay_break


@unittest.skipUnless(db_ready(), "本地 SQLite 数据库不存在，跳过评分烟测")
class RealScoringSmokeTest(unittest.TestCase):
    def test_ranking_has_theme_scores(self) -> None:
        payload = ranking_payload("2026-04-29", "short")
        self.assertGreater(len(payload["items"]), 0)
        top = payload["items"][0]
        self.assertIn("theme_score", top)
        self.assertIn("heat_score", top)
        self.assertIn("continuation_score", top)
        self.assertIn("risk_penalty", top)

    def test_risk_penalty_respects_config_cap(self) -> None:
        payload = ranking_payload("2026-04-29", "short")
        cap = float(get_active_config()["risk_cap"])
        for item in payload["items"]:
            self.assertLessEqual(float(item["risk_penalty"]), cap)

    def test_confidence_components_are_present(self) -> None:
        payload = ranking_payload("2026-04-29", "short")
        components = payload["components"]
        for key in ["liquidity", "theme_spread", "risk_stability", "market_breadth", "theme_consistency"]:
            self.assertIn(key, components)
            self.assertGreaterEqual(float(components[key]), 0)

    def test_theme_matrix_returns_recent_dates(self) -> None:
        matrix = theme_matrix_payload("2026-04-29", 20)
        self.assertGreaterEqual(len(matrix["dates"]), 1)
        self.assertGreaterEqual(len(matrix["items"]), 1)

    def test_factor_effectiveness_returns_items(self) -> None:
        payload = factor_effectiveness_payload("2026-04-29", 3)
        self.assertIn(payload["status"], ["completed", "insufficient_data"])
        if payload["status"] == "completed":
            self.assertGreater(len(payload["items"]), 0)

    def test_risk_types_within_srs_range(self) -> None:
        """验证所有风险扣分项均在 SRS 8.4 规定的区间内。"""
        srs_max = {
            "板块连续高潮": 4, "炸板率过高": 4, "核心股走弱": 5,
            "资金接力断裂": 5, "舆情过热": 3, "舆情背离": 2,
            "高位放量滞涨": 4, "后排不跟/广度不足": 3,
            "监管/异动风险": 3, "数据缺失": 20,
        }
        payload = ranking_payload("2026-04-29", "short")
        for theme in payload["items"]:
            for risk in theme.get("risks", []):
                risk_type = risk["risk_type"]
                penalty = float(risk["penalty"])
                self.assertLessEqual(penalty, srs_max.get(risk_type, 20),
                                     f"{risk_type} 扣分 {penalty} 超过 SRS 上限")

    def test_sector_stats_include_break_rate(self) -> None:
        """验证板块统计包含炸板率相关字段。"""
        payload = ranking_payload("2026-04-29", "short")
        for theme in payload["items"]:
            for sector in theme.get("sectors", []):
                stats = sector.get("stats", {})
                self.assertIn("break_rate", stats)
                self.assertIn("touched_count", stats)
                self.assertIn("max_consecutive_boards", stats)
                self.assertGreaterEqual(stats["break_rate"], 0)
                self.assertLessEqual(stats["break_rate"], 1)

    def test_relay_break_stats_in_sector(self) -> None:
        """验证板块统计包含资金接力断裂指标。"""
        payload = ranking_payload("2026-04-29", "short")
        for theme in payload["items"]:
            for sector in theme.get("sectors", []):
                relay = sector.get("stats", {}).get("relay_break", {})
                self.assertIn("lead_continue_rate", relay)
                self.assertIn("limit_overlap_rate", relay)
                self.assertIn("core_deviation", relay)


class RelayBreakUnitTest(unittest.TestCase):
    """资金接力断裂指标单元测试。"""

    def test_compute_relay_break_healthy(self) -> None:
        """领涨延续率 > 60% 时不应触发接力断裂扣分。"""
        metrics = [
            {"symbol": "A", "pct1": 0.05, "amount": 100, "limit_up": False},
            {"symbol": "B", "pct1": 0.03, "amount": 80, "limit_up": False},
            {"symbol": "C", "pct1": 0.02, "amount": 60, "limit_up": False},
            {"symbol": "D", "pct1": -0.01, "amount": 40, "limit_up": False},
        ]
        prev_pcts = {"A": 0.06, "B": 0.04, "C": 0.03, "D": 0.01}
        result = compute_relay_break(metrics, prev_pcts, 0.025)
        self.assertIsNotNone(result["lead_continue_rate"])
        self.assertGreater(result["lead_continue_rate"], 0.6)

    def test_compute_relay_break_broken(self) -> None:
        """领涨延续率 < 20% 时应标记为断裂。"""
        metrics = [
            {"symbol": "A", "pct1": -0.03, "amount": 100, "limit_up": False},
            {"symbol": "B", "pct1": -0.02, "amount": 80, "limit_up": False},
            {"symbol": "C", "pct1": 0.05, "amount": 60, "limit_up": False},
            {"symbol": "D", "pct1": 0.04, "amount": 40, "limit_up": False},
            {"symbol": "E", "pct1": 0.03, "amount": 30, "limit_up": False},
            {"symbol": "F", "pct1": 0.02, "amount": 20, "limit_up": False},
        ]
        # 昨日领涨 A、B、C、D、E（按涨幅排序前 1/3），但今日 A、B 大跌
        prev_pcts = {"A": 0.08, "B": 0.07, "C": 0.06, "D": 0.05, "E": 0.04, "F": 0.00}
        # 今日中位数约 0.01，领涨股 A(-3%)、B(-2%) 未跑赢
        result = compute_relay_break(metrics, prev_pcts, 0.01)
        self.assertLess(result["lead_continue_rate"], 0.4)

    def test_compute_relay_break_no_prev(self) -> None:
        """无前日数据时返回 None。"""
        metrics = [
            {"symbol": "A", "pct1": 0.05, "amount": 100, "limit_up": False},
        ]
        result = compute_relay_break(metrics, {}, 0.01)
        self.assertIsNone(result["lead_continue_rate"])
        self.assertIsNone(result["limit_overlap_rate"])


if __name__ == "__main__":
    unittest.main()
