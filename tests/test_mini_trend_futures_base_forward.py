from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_base_forward import BASE_FORWARD_PREREG_VERSION
from qount.mini_trend.futures_base_forward import FUTURES_BASE_FORWARD_PROTOCOL
from qount.mini_trend.futures_base_forward import build_futures_base_forward_preregistration


def _rules() -> dict:
    return {
        "market": "um",
        "source_type": "runtime_exchange_info",
        "raw_exchange_info_hash": "raw",
        "rules": [
            {"symbol": symbol, "status": "TRADING", "min_qty": "0.001", "min_notional": "5"}
            for symbol in TOP3
        ],
    }


class MiniTrendFuturesBaseForwardTest(unittest.TestCase):
    def test_registration_is_future_only_and_no_carry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lessons = Path(tmp) / "lessons.json"
            lessons.write_text(
                json.dumps(
                    {
                        "schema_version": "mini_trend_live_lessons_v0.1",
                        "verdict": "audit_complete_research_only",
                        "candidate_constraints": {"carry_allowed": False, "market": "um_futures"},
                        "equity": {"inception_to_pre_withdrawal_return_pct": -2.0, "july_rebound_giveback_usdt": -25},
                        "orders": {"post_inception_placed_order_count": 37, "exact_duplicate_order_count": 5, "same_bar_direction_flip_group_count": 8},
                        "operations": {"fail_closed_unknown_capital_count": 66},
                    }
                ),
                encoding="utf-8",
            )
            prereg = build_futures_base_forward_preregistration(_rules(), lessons)
        self.assertEqual(prereg["schema_version"], BASE_FORWARD_PREREG_VERSION)
        self.assertTrue(prereg["meta"]["future_only"])
        self.assertFalse(prereg["meta"]["strategy_results_evaluated"])
        self.assertFalse(prereg["decision_contract"]["capital"]["carry_allowed"])
        self.assertFalse(prereg["decision_contract"]["execution"]["shorting_allowed"])
        self.assertEqual(prereg["decision_contract"]["data"]["market"], "um")
        self.assertEqual(prereg["decision_contract"]["stops"]["daily_chandelier_atr_multiple"], 3.0)
        self.assertEqual(prereg["protocol"]["contract_hash"], FUTURES_BASE_FORWARD_PROTOCOL.contract_hash)


if __name__ == "__main__":
    unittest.main()
