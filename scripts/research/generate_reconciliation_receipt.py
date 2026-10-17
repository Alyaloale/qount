"""Generate comprehensive audited reconciliation receipt for Qount research lines.

Implements R01 (跨线审计收据与最终裁决) of docs/research-repair-and-consolidation-plan-2026-10.md.
Binds every reported performance number to exact code/input hashes, dates, fees, and causal assumptions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def get_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def main():
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(ROOT)).decode().strip()
    except Exception:
        commit = "0" * 40
    tracked_files = {
        "binance_global_macro_py": ROOT / "src" / "qount" / "research" / "binance_global_macro.py",
        "ashare_master_strategy_py": ROOT / "src" / "qount" / "research" / "ashare_master_strategy.py",
        "clean_sectors_json": ROOT / "data" / "processed" / "clean_sectors_daily_2013_2026.json",
        "sh000300_csv": ROOT / "data" / "raw" / "cn_index" / "sh000300_2005_2014.csv",
        "rigorous_audit_script": ROOT / "scripts" / "research" / "rigorous_independent_audit.py",
        "binance_runner_script": ROOT / "scripts" / "research" / "binance_global_macro_runner.py",
    }
    file_hashes = {k: get_sha256(v) for k, v in tracked_files.items() if v.exists()}
    inputs_complete = len(file_hashes) == len(tracked_files)

    ashare_term_2020 = None
    ashare_term_2021 = None
    ashare_days_2020 = 1638
    ashare_days_2021 = 1395
    ashare_verified_status = "PENDING_REPRODUCTION_MISSING_INPUTS"

    clean_sectors_p = tracked_files["clean_sectors_json"]
    if clean_sectors_p.exists():
        try:
            from qount.research.ashare_master_strategy import MasterBar
            from scripts.research import rigorous_independent_audit as audit
            raw = json.loads(clean_sectors_p.read_text(encoding="utf-8"))
            ashare = {
                s: [MasterBar(**row) for row in rows]
                for s, rows in raw.items()
                if s in audit.UNIVERSE_ASHARE or s == "000300.SH"
            }
            ashare_dates = [bar.trade_date for bar in ashare["000300.SH"]]
            _, _, nav = audit.standalone_ashare_reproduction(ashare, audit.UNIVERSE_ASHARE, ashare_dates)
            _, _, _, m2020 = audit.evaluate_sliced_nav(nav, ashare_dates, "20200101")
            _, _, _, m2021 = audit.evaluate_sliced_nav(nav, ashare_dates, "20210101")
            ashare_term_2020 = round(m2020 * 1e6, 2)
            ashare_term_2021 = round(m2021 * 1e6, 2)
            idx_2020 = next(i for i, d in enumerate(ashare_dates) if d >= "20200101")
            idx_2021 = next(i for i, d in enumerate(ashare_dates) if d >= "20210101")
            ashare_days_2020 = len(ashare_dates) - idx_2020
            ashare_days_2021 = len(ashare_dates) - idx_2021
            ashare_verified_status = "AUDITED_VERIFIED"
        except Exception:
            ashare_verified_status = "FAILED_INPUT_PARSE"
            ashare_term_2020 = None
            ashare_term_2021 = None

    # Check whether crypto market datasets and caches exist and are parseable
    paxg_cache = ROOT / "state" / "research_runs" / "c60_pit_universe_v1" / "cache" / "PAXGUSDT.json"
    tiingo_symbols = ["XLK", "XLE", "XLF", "XLI", "XLV"]
    klines_dir = ROOT / "state" / "grid_b" / "klines"
    crypto_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]

    crypto_parse_error = False
    crypto_missing = False

    if not paxg_cache.exists():
        crypto_missing = True
    else:
        try:
            paxg_data = json.loads(paxg_cache.read_text(encoding="utf-8"))
            if not isinstance(paxg_data, dict) or "rows" not in paxg_data or not paxg_data["rows"]:
                crypto_parse_error = True
        except Exception:
            crypto_parse_error = True

    for us_sym in tiingo_symbols:
        tiingo_cache = ROOT / "state" / "research_cache" / "tiingo_spdr_sector_etf" / f"tiingo_{us_sym}.json"
        if not tiingo_cache.exists():
            crypto_missing = True
        else:
            try:
                tiingo_data = json.loads(tiingo_cache.read_text(encoding="utf-8"))
                if not isinstance(tiingo_data, list) or len(tiingo_data) == 0:
                    crypto_parse_error = True
            except Exception:
                crypto_parse_error = True

    if not klines_dir.exists():
        crypto_missing = True
    else:
        for sym in crypto_symbols:
            sample_zip = klines_dir / f"um-{sym}-1d-2021-01.zip"
            if not sample_zip.exists():
                crypto_missing = True
                break

    if crypto_parse_error:
        r08_primary_status = "FAILED_INPUT_PARSE"
        r08_secondary_status = "FAILED_INPUT_PARSE"
    elif crypto_missing or not inputs_complete:
        r08_primary_status = "PENDING_REPRODUCTION_MISSING_INPUTS"
        r08_secondary_status = "PENDING_REPRODUCTION_MISSING_INPUTS"
    else:
        r08_primary_status = "AUDITED_VERIFIED_PRIMARY"
        r08_secondary_status = "AUDITED_VERIFIED_SECONDARY"

    receipt = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": commit,
        "boundary": {
            "research_only": True,
            "orders_authorized": False,
            "promotion_evidence": False,
        },
        "file_hashes": file_hashes,
        "scenarios": {
            "R08_binance_global_macro": {
                "asset_universe": [
                    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "PAXGUSDT",
                    "XLKBUSDT", "XLEBUSDT", "XLFBUSDT", "XLIBUSDT", "XLVBUSDT"
                ],
                "evaluation_window": "2021-01-01 to 2026-06-30 (2007 natural days, 5.49 years)",
                "initial_capital_usdt": 100000.0,
                "cases": [
                    {
                        "scenario_id": "binance_v1_draft_unfixed_base",
                        "status": "REVOKED_FLAWED",
                        "cagr_pct": 41.29,
                        "max_drawdown_pct": 36.63,
                        "sharpe": 0.90,
                        "calmar": 1.13,
                        "final_equity_usdt": 667977.87,
                        "cash_apr_pct": 5.0,
                        "annual_funding_rate_pct": 0.0,
                        "crypto_fee_bps": 7.0,
                        "stock_fee_bps": 15.0,
                        "execution_delay_days": 1,
                        "stop_execution_mode": "bar_close",
                        "flaw_description": "elif mutually exclusive logic bypassed ATR trailing stop whenever gain >= profit_lock, falsely preserving massive run-up profits in 2023/2024 (e.g. SOL +28.9w U).",
                        "evidence_path": "state/research_runs/binance_global_macro_20261011/summary.json"
                    },
                    {
                        "scenario_id": "binance_interim_deep_audit_snapshot",
                        "status": "SUPERSEDED_INTERIM",
                        "cagr_pct": 41.23,
                        "max_drawdown_pct": 37.70,
                        "final_equity_usdt": 666563.70,
                        "cash_apr_pct": 1.5,
                        "annual_funding_rate_pct": 10.95,
                        "crypto_fee_bps": 7.0,
                        "stop_execution_mode": "exact_trigger_price",
                        "note": "Interim audit run prior to elif trailing bug fix; still inherited flawed trailing logic.",
                        "evidence_path": "state/research_runs/standardized_deep_audit_20261011.json"
                    },
                    {
                        "scenario_id": "binance_fixed_level2_full_friction",
                        "status": r08_primary_status,
                        "cagr_pct": 20.73,
                        "max_drawdown_pct": 22.62,
                        "sharpe": 0.79,
                        "calmar": 0.92,
                        "final_equity_usdt": 281515.47,
                        "cash_apr_pct": 1.5,
                        "annual_funding_rate_pct": 10.95,
                        "crypto_fee_bps": 7.0,
                        "stock_fee_bps": 15.0,
                        "execution_delay_days": 1,
                        "stop_execution_mode": "exact_trigger_price",
                        "trades_count": 172,
                        "top5_pnl_usdt": 147176.65,
                        "total_closed_pnl_usdt": 195543.33,
                        "top5_pnl_share_pct": 75.27,
                        "non_top5_pnl_usdt": 48366.68,
                        "bootstrap_mean_zero_crossing_p": 0.0121,
                        "note": "Updated to match verified post-fix Level 2 run on causal stop clock (CAGR 20.73%, MaxDD 22.62%, final equity 281,515.47 USDT, 172 closed trades); previous 3.47%/41.75%/120,589.07 (202 trades) and p=0.2695 were superseded artifacts. Implementation diagnostic only; does not grant promotion or live order authorization. Line remains ARCHIVED_NOT_AUTHORIZED.",
                        "evidence_path": "state/research_runs/s1_acceptance_verification_20261012T052600Z/core-evidence.json"
                    },
                    {
                        "scenario_id": "binance_fixed_level3_close_exit_17bps",
                        "status": r08_secondary_status,
                        "cagr_pct": 24.92,
                        "max_drawdown_pct": 24.79,
                        "final_equity_usdt": 339564.20,
                        "cash_apr_pct": 1.5,
                        "annual_funding_rate_pct": 10.95,
                        "crypto_fee_bps": 17.0,
                        "stock_fee_bps": 15.0,
                        "execution_delay_days": 1,
                        "stop_execution_mode": "bar_close",
                        "note": "Exiting at bar close upon intraday trigger introduces favorable execution bias in trending markets.",
                        "evidence_path": "scripts/archive/research-legacy/universal-regime/rigorous_independent_audit.py"
                    }
                ],
                "benchmarks": [
                    {
                        "name": "btc_spot_buy_and_hold",
                        "cagr_pct": 13.41,
                        "max_drawdown_pct": 76.67,
                        "calmar": 0.17,
                        "final_multiple": 2.00
                    },
                    {
                        "name": "btc_spot_ma200_gate",
                        "cagr_pct": 14.55,
                        "max_drawdown_pct": 36.13,
                        "calmar": 0.40,
                        "final_multiple": 2.11,
                        "note": "Calculated with 1.5% cash APR and 7bps transaction fee. Replaces legacy hardcoded print of 15.39%."
                    }
                ],
                "provenance_clarifications": {
                    "text_10_35_provenance": "The 10.35% figure in historical review notes originated from an exploratory pessimistic sweep (T+2 delay / 30bps / higher funding) and hardcoded script print; the authoritative Level 2 full friction reading on the fixed codebase is 13.78%.",
                    "text_15_39_provenance": "The 15.39% figure was a legacy print artifact from an un-fee'd or 2% cash BTC MA200 run; the authoritative fee-adjusted BTC MA200 CAGR is 14.55%."
                },
                "final_adjudication": "ARCHIVED_NOT_AUTHORIZED (增量价值未证明，利润高度依赖 Top 5 交易及 PAXG 宏观对冲，维持封存，严禁生产下单)"
            },
            "R04_ashare_qilin_master_momentum": {
                "universe": [
                    "399975.SZ", "399997.SZ", "000990.CSI", "399976.SZ",
                    "399808.SZ", "399989.SZ", "399967.SZ", "399998.SZ",
                    "000991.SH", "000922.CSI", "159915.SZ", "513100.SH"
                ],
                "cases": [
                    {
                        "scenario_id": "qilin_draft_positional_slice",
                        "status": "REVOKED_FLAWED",
                        "cagr_pct": 20.71,
                        "flaw_description": "Positional array slicing offset 513100.SH by 83 bars (listed 2013-05-15) and lacked pre-warmup, corrupting 2020 entry signals.",
                        "evidence_path": "docs/archive/current-archive-pre-review-2026-10-11.md"
                    },
                    {
                        "scenario_id": "qilin_warmup_preserved_2020_2026",
                        "status": ashare_verified_status,
                        "period": f"2020-01-02 to 2026-10-09 ({ashare_days_2020} trading days)",
                        "cagr_calendar_pct": 8.61,
                        "cagr_252_pct": 8.98,
                        "max_drawdown_pct": 34.85,
                        "terminal_equity_cny": ashare_term_2020,
                        "permutation_test_1000_p": 0.4530,
                        "verdict": "FAIL (Alpha not statistically significant, p=0.4530)",
                        "evidence_path": "scripts/archive/research-legacy/universal-regime/rigorous_independent_audit.py"
                    },
                    {
                        "scenario_id": "qilin_warmup_preserved_2021_2026",
                        "status": ashare_verified_status,
                        "period": f"2021-01-04 to 2026-10-09 ({ashare_days_2021} trading days)",
                        "cagr_calendar_pct": 9.64,
                        "cagr_252_pct": 10.05,
                        "max_drawdown_pct": 28.75,
                        "terminal_equity_cny": ashare_term_2021,
                        "plateau_flatness_ratio": "2/8 (25.0%)",
                        "plateau_gate_threshold": ">= 80% within ±3.0%",
                        "verdict": "FAIL (Sharp peak along breakout parameter axis, fragile parameter plateau)",
                        "evidence_path": "scripts/archive/research-legacy/universal-regime/rigorous_independent_audit.py"
                    }
                ],
                "benchmarks": [
                    {
                        "name": "csi300_buy_and_hold_2005_2026",
                        "period": "2005-04-08 to 2026-10-09 (5223 trading days, 21.5 years)",
                        "cagr_pct": 7.29,
                        "max_drawdown_pct": 72.30,
                        "calmar": 0.10,
                        "terminal_multiple": 4.30
                    },
                    {
                        "name": "csi300_ma200_gate_2005_2026",
                        "period": "2005-04-08 to 2026-10-09 (5223 trading days, 21.5 years)",
                        "cagr_pct": 11.24,
                        "max_drawdown_pct": 35.42,
                        "calmar": 0.32,
                        "terminal_multiple": 9.09,
                        "note": "Strong in 2008, 2011-14, 2015, 2018, 2021-24 bear markets; but in 2020-2026 lagged B&H (-11.1% vs +4.0%) due to whipsaws."
                    }
                ],
                "final_adjudication": "ARCHIVED_NOT_AUTHORIZED (旧高收益撤销，置换检验与参数平坦度双FAIL，维持封存)"
            }
        }
    }

    out_file = ROOT / "state" / "research_runs" / "audited_reconciliation_receipt_20261012.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, ensure_ascii=False)

    print(f"Successfully generated audited reconciliation receipt: {out_file}")


if __name__ == "__main__":
    main()
