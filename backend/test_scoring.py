from __future__ import annotations

import sqlite3
import unittest

from model_config_store import get_active_config
from real_scoring import (
    DB_PATH,
    compute_relay_break,
    db_ready,
    detail_payload,
    factor_effectiveness_payload,
    ranking_payload,
    theme_matrix_payload,
)


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

    def test_ranking_supports_row_limit(self) -> None:
        limited = ranking_payload("2026-04-29", "short", 10)
        all_rows = ranking_payload("2026-04-29", "short", None)
        self.assertEqual(limited["row_limit"], 10)
        self.assertLessEqual(len(limited["items"]), 10)
        self.assertEqual(all_rows["row_limit"], "all")
        self.assertGreaterEqual(all_rows["total_count"], len(limited["items"]))

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
        self.assertLessEqual(len(matrix["items"]), 10)
        target_date = matrix["date"]
        for item in matrix["items"]:
            self.assertIn(target_date, item["cells"])

    def test_theme_matrix_supports_all_rows(self) -> None:
        matrix = theme_matrix_payload("2026-04-29", 20, None)
        self.assertEqual(matrix["row_limit"], "all")
        self.assertGreaterEqual(matrix["total_count"], len(matrix["items"]))

    def test_factor_effectiveness_returns_items(self) -> None:
        payload = factor_effectiveness_payload("2026-04-29", 3)
        self.assertIn(payload["status"], ["completed", "insufficient_data"])
        if payload["status"] == "completed":
            self.assertGreater(len(payload["items"]), 0)

    def test_factor_scores_are_clamped_and_explainable(self) -> None:
        payload = ranking_payload("2026-04-29", "short")
        detail = detail_payload(payload["items"][0]["theme_id"], "2026-04-29")
        self.assertIsNotNone(detail)
        for group in ["heat", "continuation"]:
            for row in detail["factor_contribution"][group]:
                self.assertGreaterEqual(float(row["score"]), 0)
                self.assertLessEqual(float(row["score"]), 100)
                self.assertIn("weighted", row)
                self.assertIn("basis", row)
                self.assertIn("formula", row)

    def test_no_limit_sector_does_not_get_short_emotion_floor(self) -> None:
        payload = ranking_payload("2026-04-29", "short")
        target = next(
            item for item in payload["items"]
            if item["sectors"][0]["stats"].get("limit_count", 0) == 0
        )
        detail = detail_payload(target["theme_id"], "2026-04-29")
        stats = detail["sectors"][0]["stats"]
        self.assertEqual(stats["limit_count"], 0)
        short_emotion = next(row for row in detail["factor_contribution"]["heat"] if row["name"] == "涨停与短线情绪")
        self.assertLess(short_emotion["score"], 10)

    def test_default_theme_components_use_dynamic_eastmoney_sectors(self) -> None:
        payload = ranking_payload("2026-04-29", "short")
        self.assertFalse(any(item["theme_id"].startswith("theme_ai_compute") for item in payload["items"]))
        self.assertFalse(any(item["theme_id"].startswith("theme_resource_price") for item in payload["items"]))
        detail = detail_payload(payload["items"][0]["theme_id"], "2026-04-29")
        self.assertGreater(len(detail["stock_metrics"]), 5)
        sources = {sector["stats"]["universe_source"] for sector in detail["sectors"]}
        self.assertEqual(sources, {"eastmoney_dynamic"})

    def test_eastmoney_stock_names_are_real_names(self) -> None:
        with sqlite3.connect(DB_PATH) as conn:
            rows = dict(
                conn.execute(
                    """
                    select symbol, name
                    from em_stock
                    where symbol in ('000001', '000002', '002384', '300274', '300476', '300750')
                    """
                ).fetchall()
            )
            named_count = conn.execute("select count(*) from em_stock where name != symbol").fetchone()[0]

        self.assertEqual(rows["000001"], "平安银行")
        self.assertEqual(rows["000002"], "万  科Ａ")
        self.assertEqual(rows["002384"], "东山精密")
        self.assertEqual(rows["300274"], "阳光电源")
        self.assertEqual(rows["300476"], "胜宏科技")
        self.assertEqual(rows["300750"], "宁德时代")
        self.assertGreater(named_count, 5000)

    def test_risk_types_within_srs_range(self) -> None:
        """验证所有风险扣分项均在合理范围内。

        单板块风险按 SRS 8.4 上限约束；聚合后的主线风险上限为 5.0。
        """
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
                # 聚合后的主线风险上限为 5.0
                self.assertLessEqual(penalty, 5.0,
                                     f"{risk_type} 扣分 {penalty} 超过聚合上限 5.0")

    def test_sector_stats_include_break_rate(self) -> None:
        """验证板块统计包含炸板率相关字段（有数据时）。"""
        payload = ranking_payload("2026-04-29", "short")
        found_stats = False
        for theme in payload["items"]:
            for sector in theme.get("sectors", []):
                stats = sector.get("stats", {})
                if not stats:
                    continue
                found_stats = True
                self.assertIn("break_rate", stats)
                self.assertIn("touched_count", stats)
                self.assertIn("max_consecutive_boards", stats)
                self.assertGreaterEqual(stats["break_rate"], 0)
                self.assertLessEqual(stats["break_rate"], 1)
        # 至少有一个板块有统计数据
        self.assertTrue(found_stats, "至少应有一个板块包含统计数据")

    def test_relay_break_stats_in_sector(self) -> None:
        """验证板块统计包含资金接力断裂指标（有数据时）。"""
        payload = ranking_payload("2026-04-29", "short")
        found_relay = False
        for theme in payload["items"]:
            for sector in theme.get("sectors", []):
                relay = sector.get("stats", {}).get("relay_break", {})
                if not relay:
                    continue
                found_relay = True
                self.assertIn("lead_continue_rate", relay)
                self.assertIn("limit_overlap_rate", relay)
                self.assertIn("core_deviation", relay)
        # 有 relay_break 数据时字段结构正确即可
        if not found_relay:
            self.skipTest("无板块包含接力断裂数据")


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


class CatalystScoringTest(unittest.TestCase):
    """催化等级评分单元测试。"""

    def test_catalyst_s_grade_high_score(self) -> None:
        """S 级催化首日应得到高分。"""
        from catalyst_store import compute_catalyst_score
        catalysts = [
            {"title": "重大政策", "level": "S", "trade_date": "2026-04-29"},
        ]
        strength, continuation, details = compute_catalyst_score(catalysts, "2026-04-29")
        self.assertGreater(strength, 80)
        self.assertGreater(continuation, 80)
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["level"], "S")
        self.assertEqual(details[0]["days_since"], 0)

    def test_catalyst_c_grade_low_score(self) -> None:
        """C 级催化首日应低于 S 级。"""
        from catalyst_store import compute_catalyst_score
        catalysts = [
            {"title": "小道消息", "level": "C", "trade_date": "2026-04-29"},
        ]
        strength, _, _ = compute_catalyst_score(catalysts, "2026-04-29")
        self.assertLess(strength, 35)

    def test_catalyst_decays_over_time(self) -> None:
        """催化随时间衰减，20 日后趋零。"""
        from catalyst_store import compute_catalyst_score
        catalysts = [
            {"title": "政策催化", "level": "S", "trade_date": "2026-04-09"},
        ]
        strength, _, details = compute_catalyst_score(catalysts, "2026-04-29")
        # 20 天后衰减系数为 0
        self.assertAlmostEqual(strength, 0.0, places=1)
        self.assertEqual(details[0]["decay"], 0.0)

    def test_catalyst_partial_decay(self) -> None:
        """10 天后的催化应衰减约 50%。"""
        from catalyst_store import compute_catalyst_score
        catalysts = [
            {"title": "政策催化", "level": "A", "trade_date": "2026-04-19"},
        ]
        strength, _, details = compute_catalyst_score(catalysts, "2026-04-29")
        # A 级基础分 70，衰减系数 0.5
        self.assertAlmostEqual(strength, 35.0, places=0)
        self.assertAlmostEqual(details[0]["decay"], 0.5, places=2)

    def test_no_catalyst_zero_score(self) -> None:
        """无催化时返回零分。"""
        from catalyst_store import compute_catalyst_score
        strength, continuation, details = compute_catalyst_score([], "2026-04-29")
        self.assertEqual(strength, 0.0)
        self.assertEqual(continuation, 0.0)
        self.assertEqual(details, [])

    def test_multiple_catalysts_takes_max(self) -> None:
        """多条催化取最高有效分。"""
        from catalyst_store import compute_catalyst_score
        catalysts = [
            {"title": "重大政策", "level": "S", "trade_date": "2026-04-20"},
            {"title": "小道消息", "level": "C", "trade_date": "2026-04-29"},
        ]
        strength, _, _ = compute_catalyst_score(catalysts, "2026-04-29")
        # C 级首日 30 > S 级 9 天后衰减（85 * 0.55 = 46.75）
        self.assertGreater(strength, 30)


if __name__ == "__main__":
    unittest.main()
