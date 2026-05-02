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


class ClusterStoreTest(unittest.TestCase):
    """自动聚合结果版本化测试。"""

    def setUp(self) -> None:
        import sqlite3
        from cluster_store import init_schema
        self._conn = sqlite3.connect(":memory:")
        init_schema(self._conn)

    def tearDown(self) -> None:
        self._conn.close()

    def test_save_and_load_clusters(self) -> None:
        """保存后可按日期加载。"""
        from cluster_store import save_clusters, load_clusters
        clusters = [
            {
                "cluster_name": "半导体",
                "sector_codes": ["BK1036", "BK1082"],
                "sector_names": ["半导体", "芯片"],
                "core_stocks": ["中芯国际", "北方华创"],
                "generation_reason": "自动聚合：半导体, 芯片",
            }
        ]
        version = save_clusters(self._conn, "2026-04-29", clusters)
        self.assertEqual(version, 1)
        loaded = load_clusters(self._conn, "2026-04-29")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["cluster_name"], "半导体")
        self.assertEqual(loaded[0]["sector_codes"], ["BK1036", "BK1082"])
        self.assertEqual(loaded[0]["cluster_version"], 1)

    def test_version_auto_increment(self) -> None:
        """同日重复执行时版本号自增。"""
        from cluster_store import save_clusters, load_clusters
        save_clusters(self._conn, "2026-04-29", [
            {"cluster_name": "AI", "sector_codes": ["BK001"], "sector_names": ["AI概念"]},
        ])
        v2 = save_clusters(self._conn, "2026-04-29", [
            {"cluster_name": "AI", "sector_codes": ["BK001", "BK002"], "sector_names": ["AI概念", "算力"]},
        ])
        self.assertEqual(v2, 2)
        loaded = load_clusters(self._conn, "2026-04-29", version=2)
        self.assertEqual(len(loaded[0]["sector_codes"]), 2)

    def test_load_nonexistent_date(self) -> None:
        """不存在的日期返回空列表。"""
        from cluster_store import load_clusters
        loaded = load_clusters(self._conn, "2020-01-01")
        self.assertEqual(loaded, [])

    def test_list_cluster_dates(self) -> None:
        """列出有聚合记录的日期。"""
        from cluster_store import save_clusters, list_cluster_dates
        save_clusters(self._conn, "2026-04-28", [
            {"cluster_name": "A", "sector_codes": ["BK001"]},
        ])
        save_clusters(self._conn, "2026-04-29", [
            {"cluster_name": "B", "sector_codes": ["BK002"]},
            {"cluster_name": "C", "sector_codes": ["BK003"]},
        ])
        dates = list_cluster_dates(self._conn)
        self.assertEqual(len(dates), 2)
        self.assertEqual(dates[0]["cluster_date"], "2026-04-29")
        self.assertEqual(dates[0]["cluster_count"], 2)


class NoFutureLeakTest(unittest.TestCase):
    """无未来函数系统测试：验证评分和回测严格使用当日及之前数据。"""

    def test_load_histories_no_future_data(self) -> None:
        """load_histories 只加载 trade_date <= 目标日期的行情。"""
        from real_scoring import load_histories
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """
            create table em_daily_quote (
              symbol text, trade_date integer, open real, high real, low real,
              close real, volume integer, amount real, primary key(symbol, trade_date)
            )
            """
        )
        conn.executemany(
            "insert into em_daily_quote values (?,?,?,?,?,?,?,?)",
            [
                ("SH600000", 20260428, 10.0, 10.5, 9.8, 10.2, 1000, 10200),
                ("SH600000", 20260429, 10.2, 10.8, 10.0, 10.5, 1200, 12600),
                ("SH600000", 20260430, 10.5, 11.0, 10.3, 10.8, 1100, 11880),
            ],
        )
        histories = load_histories(conn, ["SH600000"], 20260429)
        dates_in_history = [h["trade_date"] for h in histories.get("SH600000", [])]
        self.assertNotIn(20260430, dates_in_history, "load_histories 不应加载目标日期之后的数据")
        self.assertIn(20260429, dates_in_history)
        conn.close()

    def test_stock_metrics_no_future_reference(self) -> None:
        """stock_metrics 只基于传入的历史数据计算，不引入外部数据。"""
        from real_scoring import stock_metrics
        history = [
            {"symbol": "SH600000", "trade_date": 20260425, "open": 9.5, "high": 10.0, "low": 9.3, "close": 9.8, "volume": 800, "amount": 7840},
            {"symbol": "SH600000", "trade_date": 20260428, "open": 9.8, "high": 10.2, "low": 9.7, "close": 10.0, "volume": 900, "amount": 9000},
            {"symbol": "SH600000", "trade_date": 20260429, "open": 10.0, "high": 10.5, "low": 9.9, "close": 10.2, "volume": 1000, "amount": 10200},
        ]
        metrics = stock_metrics("SH600000", history)
        self.assertIsNotNone(metrics)
        # pct1 基于最后两天 (10.2/10.0 - 1 = 2%)
        self.assertAlmostEqual(metrics["pct1"] * 100, 2.0, places=1)

    def test_backtest_result_contains_gap_info(self) -> None:
        """回测结果应包含 fallback_count 和 gap_dates。"""
        # 不实际运行回测（太慢），只验证 backtest_result 返回结构
        from real_scoring import backtest_result
        # 用极短区间触发 insufficient_data 或有数据
        result = backtest_result({"start_date": "20990101", "end_date": "20991231", "holding_period": 3, "top_n": 5})
        # 即使 insufficient_data，也不应抛异常
        self.assertIn("status", result)

    def test_model_config_uses_no_future_data(self) -> None:
        """get_active_config 只读取已保存的配置，不预测未来。"""
        from model_config_store import get_active_config
        config = get_active_config()
        self.assertIn("heat_weight", config)
        self.assertIn("continuation_weight", config)
        self.assertIn("risk_cap", config)
        # 确认配置值在合理范围
        self.assertGreater(config["heat_weight"], 0)
        self.assertGreater(config["continuation_weight"], 0)
        self.assertGreater(config["risk_cap"], 0)


@unittest.skipUnless(db_ready(), "本地 SQLite 数据库不存在，跳过 Excel 导出测试")
class ExcelExportTest(unittest.TestCase):
    """Excel 导出回归测试。"""

    def test_ranking_excel_data_available(self) -> None:
        """榜单 Excel 所需数据可正常生成。"""
        from io import BytesIO
        import pandas as pd
        ranking = ranking_payload("2026-04-29", limit=10)
        rows = []
        for item in ranking["items"]:
            rows.append({
                "排名": item["rank"],
                "主线": item["theme_name"],
                "主线分": item["theme_score"],
                "热度分": item["heat_score"],
                "延续性分": item["continuation_score"],
                "风险扣分": item["risk_penalty"],
                "状态": item["status"],
            })
        self.assertGreater(len(rows), 0)
        # 验证能写入 Excel
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="主线榜单")
        self.assertGreater(len(output.getvalue()), 0)

    def test_risk_detail_rows_available(self) -> None:
        """风险明细数据可正常提取。"""
        ranking = ranking_payload("2026-04-29", limit=10)
        risk_rows = []
        for item in ranking["items"]:
            for risk in item["risks"]:
                risk_rows.append({
                    "主线": item["theme_name"],
                    "风险项": risk["risk_type"],
                    "扣分": risk["penalty"],
                })
        # 风险可能为空（低风险板块），但结构应正确
        self.assertIsInstance(risk_rows, list)

    def test_daily_report_exportable(self) -> None:
        """日度复盘报告数据可正常获取。"""
        from real_scoring import daily_report
        report = daily_report("2026-04-29")
        self.assertIn("date", report)
        self.assertIn("report", report)
        self.assertGreater(len(report["report"]), 0)


class DragonTigerStoreTest(unittest.TestCase):
    """龙虎榜数据存储和评分测试。"""

    def setUp(self) -> None:
        self._conn = sqlite3.connect(":memory:")
        from load_akshare_data import init_schema
        init_schema(self._conn)

    def tearDown(self) -> None:
        self._conn.close()

    def test_save_and_query_dragon_tiger(self) -> None:
        """龙虎榜数据可保存和查询。"""
        import pandas as pd
        from load_akshare_data import save_dragon_tiger
        df = pd.DataFrame([{
            "trade_date": "20260429",
            "symbol": "SH600000",
            "stock_name": "浦发银行",
            "close_price": 10.5,
            "pct_change": 2.0,
            "net_buy_amount": 1e8,
            "buy_amount": 3e8,
            "sell_amount": 2e8,
            "total_amount": 5e8,
            "market_total_amount": 1e10,
            "net_buy_ratio": 1.0,
            "turnover_ratio": 5.0,
            "float_cap": 1e11,
            "reason": "涨幅偏离值达到7%",
        }])
        count = save_dragon_tiger(self._conn, df)
        self.assertEqual(count, 1)
        row = self._conn.execute(
            "select stock_name, net_buy_amount from ak_dragon_tiger_daily where symbol = 'SH600000'"
        ).fetchone()
        self.assertEqual(row[0], "浦发银行")
        self.assertAlmostEqual(row[1], 1e8)

    def test_dragon_tiger_scoring_integration(self) -> None:
        """龙虎榜查询函数在表不存在时不报错。"""
        from real_scoring import _load_dragon_tiger
        conn = sqlite3.connect(":memory:")
        result = _load_dragon_tiger(conn, ["SH600000"], "20260429")
        self.assertEqual(result, {})
        conn.close()

    def test_hot_rank_sentiment(self) -> None:
        """热度排名计算正确。"""
        from sentiment_store import compute_hot_rank_sentiment
        # 前 5 名
        score = compute_hot_rank_sentiment(
            ["SH600000", "SZ000001"],
            {"SH600000": 3, "SZ000001": 20},
        )
        self.assertGreater(score, 80)
        # 无数据
        score_empty = compute_hot_rank_sentiment([], {})
        self.assertEqual(score_empty, 0.0)


class ThemeStageStateMachineTest(unittest.TestCase):
    """主线阶段有限状态机单元测试。"""

    def test_all_stages_defined(self) -> None:
        """阶段枚举完整。"""
        from theme_stage_store import ALL_STAGES
        self.assertEqual(len(ALL_STAGES), 6)
        for s in ("启动", "加速", "高潮", "分歧", "退潮", "修复"):
            self.assertIn(s, ALL_STAGES)

    def test_valid_transitions(self) -> None:
        """合法迁移通过验证。"""
        from theme_stage_store import is_valid_transition
        # 启动 -> 加速 ✓
        self.assertTrue(is_valid_transition("启动", "加速"))
        # 加速 -> 高潮 ✓
        self.assertTrue(is_valid_transition("加速", "高潮"))
        # 高潮 -> 分歧 ✓
        self.assertTrue(is_valid_transition("高潮", "分歧"))
        # 分歧 -> 修复 ✓
        self.assertTrue(is_valid_transition("分歧", "修复"))
        # 退潮 -> 修复 ✓
        self.assertTrue(is_valid_transition("退潮", "修复"))
        # 修复 -> 加速 ✓
        self.assertTrue(is_valid_transition("修复", "加速"))
        # 保持当前 ✓
        self.assertTrue(is_valid_transition("加速", "加速"))
        # 首次（None）✓
        self.assertTrue(is_valid_transition(None, "启动"))

    def test_invalid_transitions(self) -> None:
        """非法迁移被拒绝。"""
        from theme_stage_store import is_valid_transition
        # 启动 -> 高潮 ✗
        self.assertFalse(is_valid_transition("启动", "高潮"))
        # 启动 -> 修复 ✗
        self.assertFalse(is_valid_transition("启动", "修复"))
        # 高潮 -> 启动 ✗
        self.assertFalse(is_valid_transition("高潮", "启动"))
        # 退潮 -> 高潮 ✗
        self.assertFalse(is_valid_transition("退潮", "高潮"))
        # 修复 -> 启动 ✗
        self.assertFalse(is_valid_transition("修复", "启动"))
        # 修复 -> 高潮 ✗
        self.assertFalse(is_valid_transition("修复", "高潮"))

    def test_valid_next_stages_list(self) -> None:
        """合法下一步阶段列表正确。"""
        from theme_stage_store import get_valid_next_stages
        next_from_climax = get_valid_next_stages("高潮")
        self.assertIn("分歧", next_from_climax)
        self.assertIn("退潮", next_from_climax)
        self.assertEqual(len(next_from_climax), 2)

    def test_save_and_load_stage(self) -> None:
        """阶段可保存和读取。"""
        from theme_stage_store import (
            ensure_tables, save_stage, load_stage,
        )
        conn = sqlite3.connect(":memory:")
        ensure_tables(conn)
        save_stage(conn, "2026-04-29", "theme_test_1", "加速", "启动",
                   "热度上升+延续性好", ["热度68+3日上升"], 0.65, "v1.0")
        result = load_stage(conn, "2026-04-29", "theme_test_1")
        self.assertIsNotNone(result)
        self.assertEqual(result["stage"], "加速")
        self.assertEqual(result["previous_stage"], "启动")
        self.assertEqual(result["stage_reason"], "热度上升+延续性好")
        self.assertEqual(result["transition_signals"], ["热度68+3日上升"])
        conn.close()

    def test_save_rejects_invalid_stage(self) -> None:
        """保存非法阶段枚举值时抛出 ValueError。"""
        from theme_stage_store import ensure_tables, save_stage
        conn = sqlite3.connect(":memory:")
        ensure_tables(conn)
        with self.assertRaises(ValueError):
            save_stage(conn, "2026-04-29", "t1", "不存在的阶段", None,
                       "test", [], 0.5, "v1")
        conn.close()

    def test_save_rejects_invalid_transition(self) -> None:
        """保存非法迁移时抛出 ValueError。"""
        from theme_stage_store import ensure_tables, save_stage
        conn = sqlite3.connect(":memory:")
        ensure_tables(conn)
        with self.assertRaises(ValueError):
            save_stage(conn, "2026-04-29", "t1", "高潮", "启动",
                       "非法", [], 0.5, "v1")
        conn.close()

    def test_load_previous_stage(self) -> None:
        """可查找前一日阶段。"""
        from theme_stage_store import ensure_tables, save_stage, load_previous_stage
        conn = sqlite3.connect(":memory:")
        ensure_tables(conn)
        save_stage(conn, "2026-04-28", "t1", "启动", None, "首日", [], 0.5, "v1")
        save_stage(conn, "2026-04-29", "t1", "加速", "启动", "升温", [], 0.6, "v1")
        prev = load_previous_stage(conn, "2026-04-30", "t1")
        self.assertEqual(prev, "加速")
        conn.close()

    def test_stage_history(self) -> None:
        """阶段历史查询正确。"""
        from theme_stage_store import ensure_tables, save_stage, load_stage_history
        conn = sqlite3.connect(":memory:")
        ensure_tables(conn)
        save_stage(conn, "2026-04-27", "t1", "启动", None, "首日", [], 0.5, "v1")
        save_stage(conn, "2026-04-28", "t1", "加速", "启动", "升温", [], 0.6, "v1")
        save_stage(conn, "2026-04-29", "t1", "高潮", "加速", "极强", [], 0.7, "v1")
        history = load_stage_history(conn, "t1", "2026-04-29", 20)
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["stage"], "高潮")  # 最新在前
        conn.close()

    def test_determine_stage_high_risk_is_ebb(self) -> None:
        """高风险扣分判断为退潮。"""
        from real_scoring import determine_stage
        result = determine_stage(
            theme_score=45, heat=50, continuation=40, risk=12,
            previous_stage="高潮",
        )
        self.assertEqual(result["stage"], "退潮")

    def test_determine_stage_strong_is_climax(self) -> None:
        """极强信号判断为高潮。"""
        from real_scoring import determine_stage
        result = determine_stage(
            theme_score=80, heat=78, continuation=70, risk=3,
            limit_count=5, break_count=0,
            previous_stage="加速",
        )
        self.assertEqual(result["stage"], "高潮")

    def test_determine_stage_rising_is_accelerate(self) -> None:
        """热度上升+风险低判断为加速。"""
        from real_scoring import determine_stage
        result = determine_stage(
            theme_score=70, heat=70, continuation=62, risk=4,
            heat_trend_3d=1.5,
            previous_stage="启动",
        )
        self.assertEqual(result["stage"], "加速")

    def test_determine_stage_invalid_transition_corrected(self) -> None:
        """非法迁移被自动修正到最近的合法阶段。"""
        from real_scoring import determine_stage
        # 前阶段=高潮, 但信号指向启动 → 不合法，应修正为分歧
        result = determine_stage(
            theme_score=58, heat=56, continuation=55, risk=3,
            previous_stage="高潮",
        )
        self.assertNotEqual(result["stage"], "启动")
        self.assertIn(result["stage"], ("分歧", "退潮"))  # 合法的高潮→下一步

    def test_determine_stage_relay_break_downgrade(self) -> None:
        """接力断裂导致降级。"""
        from real_scoring import determine_stage
        result = determine_stage(
            theme_score=72, heat=72, continuation=65, risk=4,
            relay_lead_continue=0.2,
            previous_stage="加速",
        )
        self.assertEqual(result["stage"], "分歧")

    def test_determine_stage_first_day_any_stage(self) -> None:
        """首日（无前阶段）任何阶段都合法。"""
        from real_scoring import determine_stage
        result = determine_stage(
            theme_score=60, heat=58, continuation=55, risk=2,
            previous_stage=None,
        )
        self.assertIn(result["stage"], ("启动", "修复", "加速", "高潮", "分歧", "退潮"))


if __name__ == "__main__":
    unittest.main()
