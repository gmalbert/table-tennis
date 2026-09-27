from __future__ import annotations

from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).parent.parent


class StreamlitSmokeTests(unittest.TestCase):
    def run_page(self, relative_path: str, timeout: int = 120) -> AppTest:
        app = AppTest.from_file(str(ROOT / relative_path), default_timeout=timeout)
        app.run(timeout=timeout)
        rendered_exceptions = [str(item.value) for item in app.exception]
        self.assertEqual(rendered_exceptions, [], f"{relative_path}: {rendered_exceptions}")
        return app

    def test_entry_point(self) -> None:
        app = self.run_page("predictions.py")
        self.assertTrue(app.title or app.subheader)

    def test_frontier_pages_render(self) -> None:
        for relative_path in (
            "pages/6_Upcoming_Matches.py",
            "pages/7_Backtesting.py",
            "pages/8_World_Rankings.py",
            "pages/9_Betting_Tools.py",
            "pages/10_Tournament_Brackets.py",
            "pages/11_Model_Lab.py",
            "pages/12_Data_Quality.py",
        ):
            with self.subTest(page=relative_path):
                self.run_page(relative_path)


if __name__ == "__main__":
    unittest.main()
