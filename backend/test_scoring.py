from __future__ import annotations

import unittest

from model_config_store import get_active_config
from real_scoring import db_ready, factor_effectiveness_payload, ranking_payload, theme_matrix_payload


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


if __name__ == "__main__":
    unittest.main()
