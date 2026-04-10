import tempfile
import unittest
from pathlib import Path

from run_ml_walkforward import list_missing_cache_files


class RunMLWalkforwardTests(unittest.TestCase):
    def test_list_missing_cache_files_reports_required_market_cache_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            missing = list_missing_cache_files(str(base), ["BTCUSDT"], ["5m", "15m"])

        self.assertEqual(
            missing,
            [
                str(base / "BTCUSDT_premium.json"),
                str(base / "BTCUSDT_open_interest.json"),
                str(base / "BTCUSDT_5m_klines.json"),
                str(base / "BTCUSDT_15m_klines.json"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
