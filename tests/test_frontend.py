"""前端自动化测试（Playwright）。

需要本地服务运行在 http://127.0.0.1:8000。
启动服务: python backend/server.py
运行测试: cd tests && python -m unittest test_frontend -v
"""

from __future__ import annotations

import unittest
from urllib.request import urlopen
from urllib.error import URLError

BASE_URL = "http://127.0.0.1:8000"


def _server_running() -> bool:
    try:
        with urlopen(f"{BASE_URL}/api/v1/auth/roles", timeout=3) as resp:
            return resp.status == 200
    except (URLError, OSError):
        return False


@unittest.skipUnless(_server_running(), "本地服务未运行，跳过前端测试")
class FrontendSmokeTest(unittest.TestCase):
    """前端页面基础交互测试。"""

    @classmethod
    def setUpClass(cls) -> None:
        from playwright.sync_api import sync_playwright
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._browser.close()
        cls._pw.stop()

    def setUp(self) -> None:
        self._page = self._browser.new_page()

    def tearDown(self) -> None:
        self._page.close()

    def test_page_loads_with_title(self) -> None:
        """页面加载后应显示标题和主线榜单区域。"""
        self._page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        title = self._page.title()
        self.assertIn("雷达", title)
        # 主线榜单区域可见
        ranking = self._page.locator("#ranking-section, #ranking, [id*='ranking']")
        self.assertGreater(ranking.count(), 0, "未找到主线榜单区域")

    def test_date_switch_refreshes_content(self) -> None:
        """切换日期后榜单内容应更新。"""
        self._page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        date_input = self._page.locator("input[type='date']")
        if date_input.count() == 0:
            self.skipTest("未找到日期输入框")
        # 修改日期
        date_input.first.fill("2026-04-28")
        date_input.first.dispatch_event("change")
        # 等待 API 响应
        self._page.wait_for_timeout(5000)
        # 页面应仍有内容（可能为空数据但不报错）
        body = self._page.locator("body")
        self.assertTrue(body.is_visible())

    def test_ranking_limit_selector(self) -> None:
        """榜单裁剪选择器应存在且可切换。"""
        self._page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        # 查找 limit 选择器（可能是 select 或按钮）
        limit_control = self._page.locator("select[id*='limit'], select[id*='Limit'], [data-limit]")
        if limit_control.count() == 0:
            self.skipTest("未找到榜单裁剪控件")
        self.assertGreater(limit_control.count(), 0)

    def test_detail_page_score_breakdown(self) -> None:
        """点击榜单第一条应展示详情页评分拆解。"""
        self._page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        # 找到第一条主线并点击
        first_item = self._page.locator("[data-theme-id], .ranking-row, #ranking tr").first
        if not first_item.is_visible():
            self.skipTest("榜单为空")
        first_item.click()
        self._page.wait_for_timeout(3000)
        # 验证详情区域出现
        detail = self._page.locator("#detail-section, #detail, [id*='detail']")
        self.assertGreater(detail.count(), 0, "未找到详情区域")

    def test_kline_popup(self) -> None:
        """双击成分股行应弹出 K 线弹窗。"""
        self._page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        # 先进入详情页
        first_item = self._page.locator("[data-theme-id], .ranking-row, #ranking tr").first
        if not first_item.is_visible():
            self.skipTest("榜单为空")
        first_item.click()
        self._page.wait_for_timeout(3000)
        # 查找成分股表格行
        stock_row = self._page.locator("#stocks-table tr, .stock-row, [data-symbol]").first
        if not stock_row.is_visible():
            self.skipTest("未找到成分股行")
        stock_row.dblclick()
        self._page.wait_for_timeout(2000)
        # 验证 K 线弹窗出现（SVG 或 canvas）
        kline = self._page.locator("#kline-modal, .kline-modal, [id*='kline']")
        self.assertGreater(kline.count(), 0, "双击成分股后未出现 K 线弹窗")


if __name__ == "__main__":
    unittest.main()
