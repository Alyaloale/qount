"""Accounting and failure-boundary checks for the read-only asset view."""
import copy
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from qount.operations.account_assets import append_asset_history, collect_asset_overview, read_asset_history
from qount.api.routes.account import _execution_symbol, get_asset_overview
from qount.operations.authority_writer import read_blocked_runtime_observation


class Exchange:
    def __init__(self):
        self.calls = []
        self.wallets = [
            {"walletName": "Spot", "balance": "100", "activate": True},
            {"walletName": "USDⓈ-M Futures", "balance": "20", "activate": True},
            {"walletName": "COIN-M Futures", "balance": "0", "activate": False},
        ]
        self.usdm = {"assets": [{"asset": "USDT", "walletBalance": "20", "unrealizedProfit": "5", "marginBalance": "25", "availableBalance": "22"}],
                     "positions": [{"symbol": "BTCUSDT", "positionAmt": "0.001", "positionSide": "BOTH", "unrealizedProfit": "5", "notional": "100"}]}
        self.coinm = {"assets": [{"asset": "BTC", "walletBalance": "0.01", "unrealizedProfit": "-0.001", "marginBalance": "0.009"}],
                      "positions": [{"symbol": "BTCUSD_PERP", "positionAmt": "-10", "positionSide": "SHORT", "unrealizedProfit": "-0.001"}]}
        self.prices = [{"symbol": "BTCUSDT", "price": "100000"}]

    def sapiGetAssetWalletBalance(self, params):
        self.calls.append(("wallets", params))
        return copy.deepcopy(self.wallets)

    def fapiPrivateV3GetAccount(self, params):
        self.calls.append(("usdm", params))
        return copy.deepcopy(self.usdm)

    def dapiPrivateGetAccount(self, params):
        self.calls.append(("coinm", params))
        return copy.deepcopy(self.coinm)

    def publicGetTickerPrice(self, params):
        self.calls.append(("prices", params))
        return copy.deepcopy(self.prices)


class TestAccountAssets(unittest.TestCase):
    def test_ccxt_usdm_symbol_is_normalized_to_execution_symbol(self):
        self.assertEqual(_execution_symbol("CL/USDT:USDT"), "CLUSDT")
        self.assertEqual(_execution_symbol("BTCUSDT"), "BTCUSDT")

    def test_totals_do_not_double_count_futures_and_allow_available_above_wallet(self):
        exchange = Exchange()
        result = collect_asset_overview(exchange)
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["reported_total_usdt"], 120)
        self.assertEqual(result["futures_equity_usdt"], 25)
        self.assertEqual(result["futures_unrealized_pnl_usdt"], 5)
        self.assertEqual(result["usdm_available_balance_usdt"], 22)
        self.assertEqual(result["futures_positions"][0]["notional_usdt"], 100)
        self.assertEqual(exchange.calls[0], ("wallets", {"quoteAsset": "USDT"}))
        self.assertEqual([name for name, _ in exchange.calls], ["wallets", "usdm"])

    def test_wallet_totals_include_coin_margin_while_pnl_scope_stays_usdm(self):
        exchange = Exchange()
        exchange.wallets[2].update(activate=True, balance="1000")
        result = collect_asset_overview(exchange)
        self.assertEqual(result["reported_total_usdt"], 1120)
        self.assertEqual(result["futures_equity_usdt"], 25)
        self.assertTrue(all(p["market"] == "usdm" for p in result["futures_positions"]))

    def test_coin_margin_price_gaps_cannot_affect_usdm_completeness(self):
        exchange = Exchange()
        exchange.wallets[2].update(activate=True, balance="1000")
        exchange.prices = []
        result = collect_asset_overview(exchange)
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["reported_total_usdt"], 1120)
        self.assertEqual(result["futures_unrealized_pnl_usdt"], 5)
        self.assertTrue(result["futures_positions_complete"])

    def test_broken_equity_identity_is_rejected(self):
        exchange = Exchange()
        exchange.usdm["assets"][0]["marginBalance"] = "999"
        result = collect_asset_overview(exchange)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertIsNone(result["futures_equity_usdt"])

    def test_other_collateral_does_not_suppress_real_usdt_equity_or_get_valued_at_par(self):
        exchange = Exchange()
        exchange.usdm["assets"].append({"asset":"USDC","walletBalance":".0000073",
            "unrealizedProfit":"0","marginBalance":".0000073","availableBalance":".0000073"})
        result = collect_asset_overview(exchange)
        self.assertEqual(result["status"],"PARTIAL")
        self.assertEqual(result["usdm_margin_balance_usdt"],25)
        self.assertEqual(result["futures_equity_usdt"],25)
        self.assertEqual(result["unvalued_collateral_assets"],["USDC"])
        self.assertTrue(result["futures_positions_complete"])
        from qount.operations.account_performance import _observation
        self.assertEqual(_observation(result["observed_at"],result)["equity_usdt"],25)

    def test_duplicate_wallet_and_nonfinite_amount_are_rejected(self):
        for extra in [{"walletName": "Spot", "balance": "1", "activate": True},
                      {"walletName": "Funding", "balance": "nan", "activate": True}]:
            exchange = Exchange()
            exchange.wallets.append(extra)
            result = collect_asset_overview(exchange)
            self.assertEqual(result["status"], "MISSING")
            self.assertIsNone(result["reported_total_usdt"])

    def test_errors_never_store_signed_url_or_secret(self):
        exchange = Exchange()
        def fail(_):
            raise RuntimeError("https://private?signature=SECRET&apiKey=SECRET")
        exchange.sapiGetAssetWalletBalance = fail
        result = collect_asset_overview(exchange)
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertEqual(result["errors"], {"wallet_overview": "RuntimeError"})

    def test_history_is_real_append_only_and_read_does_not_create_files(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "history.db"
            self.assertEqual(read_asset_history(path)["status"], "MISSING")
            self.assertFalse(path.exists())
            result = collect_asset_overview(Exchange())
            append_asset_history(path, result)
            append_asset_history(path, result)
            self.assertEqual(read_asset_history(path)["observation_count"], 1)
            conflicting = result | {"reported_total_usdt": 999}
            with self.assertRaisesRegex(ValueError, "conflict"):
                append_asset_history(path, conflicting)
            self.assertEqual(read_asset_history(path)["points"][0]["reported_total_usdt"], 120)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_api_never_substitutes_legacy_or_paper_balance(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "observation.json"
            path.write_text(json.dumps({"account_observation": {"wallet_balance": 999999}}))
            with patch.dict(os.environ, {"QOUNT_ACCOUNT_ASSETS_PATH": str(path)}):
                self.assertIsNone(get_asset_overview()["reported_total_usdt"])
                result = collect_asset_overview(Exchange())
                path.write_text(json.dumps(result))
                self.assertEqual(get_asset_overview()["reported_total_usdt"], 120)

    def test_observer_keeps_strict_legacy_contract_and_separate_asset_files(self):
        script = Path(__file__).resolve().parents[1] / "scripts/operations/refresh_dashboard_account_observation.py"
        spec = importlib.util.spec_from_file_location("asset_observer_test", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stamp = datetime.now(timezone.utc).isoformat()
        for legacy in ({"observed_at": stamp}, None):
            with self.subTest(legacy_available=legacy is not None), tempfile.TemporaryDirectory() as root:
                target = Path(root) / "blocked_runtime_observation.json"
                with patch.object(module.Settings, "from_env", return_value=object()), \
                     patch.object(module, "build_pilot_account_preflight", return_value={"created_at": stamp}), \
                     patch.object(module, "_readonly_account_observation", return_value=legacy), \
                     patch.object(module, "build_exchange", return_value=Exchange()), \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(module.main(["--output-path", str(target)]), 0)
                assets = json.loads(target.with_name("account-assets.json").read_text())
                self.assertEqual(assets["reported_total_usdt"], 120)
                self.assertEqual(read_asset_history(target.with_name("account-assets-history.sqlite3"))["observation_count"], 1)
                if legacy is not None:
                    parsed = read_blocked_runtime_observation(target)
                    self.assertEqual(parsed["account_observation"], legacy)
                    self.assertNotIn("asset_overview", parsed)
                else:
                    self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
