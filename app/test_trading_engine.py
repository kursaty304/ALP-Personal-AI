import math
import unittest
from decimal import Decimal

from trading_engine import (
    PaperTrader, analyze_candles, build_position_plan, ema,
    parse_bitvavo_candles, rsi,
)


class TradingEngineTests(unittest.TestCase):
    def test_parse_and_sort_bitvavo_candles(self):
        rows = [
            ["3600000", "101", "103", "99", "102", "5"],
            ["0", "100", "102", "98", "101", "4"],
        ]
        candles = parse_bitvavo_candles(rows)
        self.assertEqual([c.timestamp_ms for c in candles], [0, 3600000])
        self.assertEqual(candles[-1].close, 102.0)

    def test_ema(self):
        self.assertEqual(ema([1, 2, 3, 4], 3), [None, None, 2.0, 3.0])

    def test_rsi_flat_market(self):
        self.assertEqual(rsi([10.0] * 16, 14)[14], 50.0)

    def test_position_plan_respects_risk_and_fees(self):
        plan = build_position_plan("100", "98", "100", "1", "0.0025")
        self.assertLessEqual(plan.estimated_loss_eur, Decimal("1.00000001"))
        self.assertGreater(plan.quantity, 0)
        self.assertGreater(plan.target_price, plan.entry_price)

    def test_paper_trade_round_trip(self):
        trader = PaperTrader("100", "0.0025")
        trader.open_long("BTC-EUR", "100", "98", timestamp_ms=1)
        closed = trader.close_position("105", timestamp_ms=2)
        self.assertGreater(closed.net_pnl_eur, 0)
        self.assertIsNone(trader.position)
        self.assertEqual(len(trader.closed_trades), 1)
        self.assertGreater(trader.performance_summary()["win_rate_pct"], 0)

    def test_stop_exit_is_paper_only(self):
        trader = PaperTrader("100")
        trader.open_long("BTC-EUR", "100", "98", timestamp_ms=1)
        closed = trader.evaluate_exit("97", timestamp_ms=2)
        self.assertIsNotNone(closed)
        self.assertLess(closed.net_pnl_eur, 0)

    def test_only_one_open_position(self):
        trader = PaperTrader("100")
        trader.open_long("BTC-EUR", "100", "98")
        with self.assertRaises(ValueError):
            trader.open_long("ETH-EUR", "50", "49")

    def test_analysis_requires_200_closed_bars(self):
        base = 1_700_000_000_000
        rows = []
        for i in range(80):
            close = 100 + i * 0.1 + math.sin(i / 3)
            rows.append([base + i * 3_600_000, close, close + 1, close - 1, close, 10])
        result = analyze_candles(rows, now_ms=base + 1000 * 3_600_000)
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["signal"], "WAIT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
