"""Runner for Personal Trading Assistant Minimal Loop & Reconciled Core ETF Baseline Bundle.

Implements Phase S2 (R04) of docs/research-repair-and-consolidation-plan-2026-10.md.
Executes causal baselines on 1-3 core real ETFs and outputs daily after-close review.
Generates an immutable, non-overwriting reconciled bundle containing summary, manifest,
replay curves, and trade audit logs.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from qount.research.personal_trading_assistant import (
    CORE_ETF_UNIVERSE,
    PersonalTradingAssistantKernel,
    format_daily_report_markdown,
    generate_deterministic_daily_report,
    load_dataset_from_clean_indices,
)


def get_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def get_git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(ROOT)).decode().strip()
    except Exception:
        return "UNKNOWN"


def run_baseline_and_daily_review(
    output_dir: Path | None = None,
    data_path: Path | None = None,
    cash_apr: float = 0.02,
    initial_capital: float = 1_000_000.0,
    ma_period: int = 120,
    band_pct: float = 0.015,
    confirm_days: int = 2,
    expected_as_of_date: str | None = None,
    require_completed_bar: bool = True,
):
    print("=" * 96)
    print("AI 个人量化交易助手: 核心 ETF 调和基线与收盘后每日复盘评估 (Phase S2 / R04 Reconciled)")
    print("=" * 96)

    data_path = data_path or (ROOT / "data" / "processed" / "clean_indices_daily_2013_2026.json")
    if not data_path.exists():
        raise FileNotFoundError(f"Missing data file: {data_path}")

    # Protected immutable baseline and reconciled paths
    protected_dirs = [
        (ROOT / "state" / "research_runs" / "personal_assistant_baseline_20261012").resolve(),
        (ROOT / "state" / "research_runs" / "personal_assistant_reconciled_20261012").resolve(),
    ]
    out_dir = output_dir or (ROOT / "state" / "research_runs" / "personal_assistant_reconciled_20261012")
    if out_dir.resolve() in protected_dirs:
        raise PermissionError(
            f"The package at {out_dir} is a protected immutable artifact and must never be overwritten."
        )

    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(
            f"Target directory {out_dir} already exists and is non-empty; immutable run protection rejects overwriting."
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    dataset = load_dataset_from_clean_indices(data_path)
    kernel = PersonalTradingAssistantKernel(cash_apr=cash_apr, initial_capital=initial_capital)

    # Core 1-3 retail assets
    eval_symbols = ["000300.SH", "513100.SH", "159915.SZ"]
    now_iso = datetime.now(timezone.utc).isoformat()
    git_commit = get_git_commit()

    results_summary = {
        "schema_version": "1.1.0",
        "generated_at": now_iso,
        "git_commit": git_commit,
        "boundary": {
            "research_only": True,
            "orders_authorized": False,
            "promotion_evidence": False,
        },
        "run_type": "personal_assistant_reconciled_s2_bundle",
        "description": "Reconciled causal baseline bundle (Buy&Hold vs Trend vs Cash) for core retail ETFs with corporate actions and unified state machine",
        "previous_baseline_reference": {
            "run_dir": "state/research_runs/personal_assistant_baseline_20261012",
            "summary_sha256": "d0bae231d6e388141c46ddfa31b2d5d5a6e5556c0dd530db114fa98890a49a4b",
            "immutable_preservation": True,
            "key_differences_resolved": [
                "513100.SH 1:5 split (2022-01-13) incorporated in both share ledger and backward-adjusted closes, eliminating artificial 85.5% max drawdown",
                "TrendTimingStateMachine shared identically across historical backtest and daily evaluation",
                "Calendar-year CAGR (cagr_calendar_pct) reported alongside 252-day convention (cagr_252_pct)",
                "Two-sided turnover (annual_turnover_two_sided) reported alongside sell-only turnover (annual_turnover)",
                "Cash calmar ratio and win rate reported as null rather than 99.0 / 100.0",
            ],
        },
        "assets": {},
        "daily_after_market_review": [],
        "unknowns_and_limitations": [
            "510300.SH (华泰柏瑞沪深300ETF) 在 clean_indices 数据集中未提供独立日K序列，当前采用 000300.SH 作为指数代理进行长期大周期结构性验证。待补录真实 510300.SH 场内复权序列后再做实体ETF对照；当前仅保留研究比较身份，不生成有效实盘仓位建议。",
            "513100.SH 在 2022-01-13 实施 1:5 拆分，本运行通过 corporate_actions 完整调整了持仓份额（保持权益连续）及历史均线前复权序列（消除机械破位虚假信号）；分红/到账资格仍需逐期确认。",
            "现金按年化 2.0% 隔夜逆回购/货币基金按 252 交易日折算日复利累积 (daily_cash_rate = (1.0 + apr) ** (1/252) - 1.0)。",
            "换手率已严格区分单边卖出换手 (annual_turnover / sell_turnover) 与双边总换手 (annual_turnover_two_sided = (buy+sell)/avg_nav/years)。买持基线换手率按传统调仓口径统计为 0.0x；若计入初始建仓买入额，双边换手口径为首次建仓资金/(平均NAV*年数)。",
            "年化收益率已严格分列 252 交易日折算口径 (cagr_252_pct) 与自然日历年口径 (cagr_calendar_pct)。",
            "每日有效输出的数据条件：盘前/盘中极值不作为成交价，正式日线信号仅在完整收盘后生成；陈旧数据 (stale) 或未完整收盘 (incomplete) 均拒绝生成有效仓位建议，次日开盘按开盘价+滑点成交。",
        ],
    }

    replay_bundle: dict = {}
    trades_bundle: dict = {}
    trend_metrics: dict = {}

    print("\n[1] 核心资产全历史调和基线对比 (Buy & Hold vs 大周期趋势择时 vs 2% 纯现金):")
    print(f"{'资产与策略':<22} | {'时间跨度':<19} | {'日历年':<6} | {'CAGR(252)':<9} | {'CAGR(Cal)':<9} | {'MaxDD':<7} | {'在市比':<6} | {'单边换手':<8} | {'双边换手':<8} | {'笔数':<4} | {'卡玛'}")
    print("-" * 125)

    for sym in eval_symbols:
        meta = CORE_ETF_UNIVERSE[sym]
        bars = dataset[sym]
        valid_bars = [b for b in bars if b.trade_date >= meta.listing_date]
        valid_dates = [b.trade_date for b in valid_bars]

        results_summary["assets"][sym] = {
            "metadata": asdict(meta),
            "manifest": {
                "source_dataset": str(data_path.relative_to(ROOT)),
                "is_index_proxy": meta.is_index_proxy,
                "listing_date": meta.listing_date,
                "first_bar_date": valid_bars[0].trade_date,
                "last_bar_date": valid_bars[-1].trade_date,
                "trading_days": len(valid_bars),
                "corporate_actions": [asdict(ca) for ca in meta.corporate_actions],
            },
            "baselines": [],
        }
        replay_bundle[sym] = {}
        trades_bundle[sym] = {}

        # 1. Buy & Hold
        nav_bh, m_bh, t_bh = kernel.simulate_buy_and_hold(bars, meta, return_trades=True)
        results_summary["assets"][sym]["baselines"].append(asdict(m_bh))
        replay_bundle[sym]["Buy_and_Hold"] = {
            "metrics": asdict(m_bh),
            "nav": list(zip(valid_dates, [round(x, 2) for x in nav_bh])),
        }
        trades_bundle[sym]["Buy_and_Hold"] = t_bh
        calmar_str = f"{m_bh.calmar_ratio:.2f}" if m_bh.calmar_ratio is not None else "N/A"
        print(f"{meta.name[:9]+' B&H':<22} | {m_bh.start_date}-{m_bh.end_date} | {m_bh.calendar_years:5.1f}y | {m_bh.cagr_252_pct:8.2f}% | {m_bh.cagr_calendar_pct:8.2f}% | {m_bh.max_drawdown_pct:6.2f}% | {m_bh.exposure_pct:5.1f}% | {m_bh.annual_turnover:7.2f}x | {m_bh.annual_turnover_two_sided:7.2f}x | {m_bh.trade_count:<4} | {calmar_str}")

        # 2. Trend Timing MA120 (1.5% buffer)
        nav_tr120, m_tr120, t_tr120 = kernel.simulate_trend_timing(bars, meta, ma_period=120, band_pct=0.015, confirm_days=confirm_days, return_trades=True)
        results_summary["assets"][sym]["baselines"].append(asdict(m_tr120))
        replay_bundle[sym]["MA120_Band1.5pct"] = {
            "metrics": asdict(m_tr120),
            "nav": list(zip(valid_dates, [round(x, 2) for x in nav_tr120])),
        }
        trades_bundle[sym]["MA120_Band1.5pct"] = t_tr120
        trend_metrics[sym] = m_tr120
        calmar_str = f"{m_tr120.calmar_ratio:.2f}" if m_tr120.calmar_ratio is not None else "N/A"
        print(f"{meta.name[:9]+' MA120':<22} | {m_tr120.start_date}-{m_tr120.end_date} | {m_tr120.calendar_years:5.1f}y | {m_tr120.cagr_252_pct:8.2f}% | {m_tr120.cagr_calendar_pct:8.2f}% | {m_tr120.max_drawdown_pct:6.2f}% | {m_tr120.exposure_pct:5.1f}% | {m_tr120.annual_turnover:7.2f}x | {m_tr120.annual_turnover_two_sided:7.2f}x | {m_tr120.trade_count:<4} | {calmar_str}")

        # 3. Trend Timing MA200 (1.5% buffer)
        nav_tr200, m_tr200, t_tr200 = kernel.simulate_trend_timing(bars, meta, ma_period=200, band_pct=0.015, confirm_days=confirm_days, return_trades=True)
        results_summary["assets"][sym]["baselines"].append(asdict(m_tr200))
        replay_bundle[sym]["MA200_Band1.5pct"] = {
            "metrics": asdict(m_tr200),
            "nav": list(zip(valid_dates, [round(x, 2) for x in nav_tr200])),
        }
        trades_bundle[sym]["MA200_Band1.5pct"] = t_tr200
        calmar_str = f"{m_tr200.calmar_ratio:.2f}" if m_tr200.calmar_ratio is not None else "N/A"
        print(f"{meta.name[:9]+' MA200':<22} | {m_tr200.start_date}-{m_tr200.end_date} | {m_tr200.calendar_years:5.1f}y | {m_tr200.cagr_252_pct:8.2f}% | {m_tr200.cagr_calendar_pct:8.2f}% | {m_tr200.max_drawdown_pct:6.2f}% | {m_tr200.exposure_pct:5.1f}% | {m_tr200.annual_turnover:7.2f}x | {m_tr200.annual_turnover_two_sided:7.2f}x | {m_tr200.trade_count:<4} | {calmar_str}")

        # 4. Pure Cash Control
        nav_cash, m_cash, t_cash = kernel.simulate_pure_cash(bars, meta, return_trades=True)
        results_summary["assets"][sym]["baselines"].append(asdict(m_cash))
        replay_bundle[sym]["Pure_Cash_2pct_Control"] = {
            "metrics": asdict(m_cash),
            "nav": list(zip(valid_dates, [round(x, 2) for x in nav_cash])),
        }
        trades_bundle[sym]["Pure_Cash_2pct_Control"] = t_cash
        calmar_str = f"{m_cash.calmar_ratio:.2f}" if m_cash.calmar_ratio is not None else "null"
        print(f"{meta.name[:9]+' 纯现金':<22} | {m_cash.start_date}-{m_cash.end_date} | {m_cash.calendar_years:5.1f}y | {m_cash.cagr_252_pct:8.2f}% | {m_cash.cagr_calendar_pct:8.2f}% | {m_cash.max_drawdown_pct:6.2f}% | {m_cash.exposure_pct:5.1f}% | {m_cash.annual_turnover:7.2f}x | {m_cash.annual_turnover_two_sided:7.2f}x | {m_cash.trade_count:<4} | {calmar_str}")
        print("-" * 125)

    # Daily Assistant Status Review as of latest close
    daily_status_list = []
    print("\n[2] 收盘后每日复盘与无订单决策看板 (截至最新完整交易日):")
    for sym in eval_symbols:
        meta = CORE_ETF_UNIVERSE[sym]
        bars = dataset[sym]
        status = kernel.evaluate_daily_status(
            bars,
            meta,
            ma_period=ma_period,
            band_pct=band_pct,
            confirm_days=confirm_days,
            expected_as_of_date=expected_as_of_date,
            require_completed_bar=require_completed_bar,
        )
        daily_status_list.append(status)
        results_summary["daily_after_market_review"].append(asdict(status))

        regime_badge = "🟢 [多头持仓]" if status.regime == "BULLISH_HOLD" else ("🔴 [空头现金]" if status.regime == "BEARISH_CASH" else "🟡 [过渡观察]")
        print(f"\n标的: {status.name} ({status.symbol}) | 评估日期: {status.as_of_date}")
        print(f"  最新收盘价: {status.close_price:.3f} | MA{status.ma_period}: {status.ma_trend_val:.3f} (偏离度: {status.distance_to_ma_pct:+.2f}%)")
        print(f"  趋势体制: {regime_badge} | 建议目标仓位: {status.target_weight*100:.0f}% (确认日进度: {status.confirm_count}/{confirm_days})")
        print(f"  决策逻辑: {status.reason}")
        print(f"  安全底线: research_only=True / orders_authorized=False (零生产订单、零实盘交互)")

    # 1. Save summary.json
    summary_file = out_dir / "summary.json"
    with open(summary_file, "x", encoding="utf-8") as f:
        json.dump(results_summary, f, indent=2, ensure_ascii=False)

    # 2. Save baseline-replay.json
    replay_file = out_dir / "baseline-replay.json"
    with open(replay_file, "x", encoding="utf-8") as f:
        json.dump(replay_bundle, f, indent=2, ensure_ascii=False)

    # 3. Save trades.json
    trades_file = out_dir / "trades.json"
    with open(trades_file, "x", encoding="utf-8") as f:
        json.dump(trades_bundle, f, indent=2, ensure_ascii=False)

    # 4. Generate & Save deterministic daily report (S3-C)
    data_hash = get_sha256(data_path)
    daily_report = generate_deterministic_daily_report(
        daily_statuses=daily_status_list,
        baseline_metrics=trend_metrics,
        expected_as_of_date=expected_as_of_date,
        source_data_hash=data_hash,
        source_data_path=str(data_path.relative_to(ROOT)),
        execution_run_id=out_dir.name,
    )
    daily_report_json_file = out_dir / "daily-report.json"
    with open(daily_report_json_file, "x", encoding="utf-8") as f:
        json.dump(daily_report, f, indent=2, ensure_ascii=False)

    daily_report_md = format_daily_report_markdown(daily_report)
    daily_report_md_file = out_dir / "daily-report.md"
    with open(daily_report_md_file, "x", encoding="utf-8") as f:
        f.write(daily_report_md)

    # 5. Generate & Save manifest.json
    manifest = {
        "schema_version": "1.1.0",
        "generated_at": now_iso,
        "git_commit": git_commit,
        "boundary": {
            "research_only": True,
            "orders_authorized": False,
            "promotion_evidence": False,
        },
        "input_files": {
            "data_path": str(data_path.relative_to(ROOT)),
            "data_sha256": get_sha256(data_path),
            "code_path": "src/qount/research/personal_trading_assistant.py",
            "code_sha256": get_sha256(ROOT / "src" / "qount" / "research" / "personal_trading_assistant.py"),
            "runner_path": "scripts/research/run_personal_assistant_daily.py",
            "runner_sha256": get_sha256(Path(__file__).resolve()),
        },
        "eval_symbols": eval_symbols,
        "parameters": {
            "cash_apr": cash_apr,
            "initial_capital": initial_capital,
            "ma_period_daily": ma_period,
            "band_pct_daily": band_pct,
            "confirm_days_daily": confirm_days,
            "expected_as_of_date": expected_as_of_date,
            "require_completed_bar": require_completed_bar,
        },
        "output_artifacts": {
            "summary_json": {
                "file": "summary.json",
                "sha256": get_sha256(summary_file),
            },
            "baseline_replay_json": {
                "file": "baseline-replay.json",
                "sha256": get_sha256(replay_file),
            },
            "trades_json": {
                "file": "trades.json",
                "sha256": get_sha256(trades_file),
            },
            "daily_report_json": {
                "file": "daily-report.json",
                "sha256": get_sha256(daily_report_json_file),
            },
            "daily_report_md": {
                "file": "daily-report.md",
                "sha256": get_sha256(daily_report_md_file),
            },
        },
    }
    manifest_file = out_dir / "manifest.json"
    with open(manifest_file, "x", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # 6. Write completion marker
    complete_marker = out_dir / "_COMPLETE"
    with open(complete_marker, "x", encoding="utf-8") as f:
        f.write(f"Completed at {now_iso}\nGit commit: {git_commit}\n")

    print("\n[3] 结果工件已成功固化保存至调和运行目录 (不可覆盖新结果包):")
    print(f"  - 汇总报告: {summary_file}")
    print(f"  - 确定性日报 JSON: {daily_report_json_file}")
    print(f"  - 确定性日报 Markdown: {daily_report_md_file}")
    print(f"  - 校验清单: {manifest_file}")
    print(f"  - 独立重放: {replay_file}")
    print(f"  - 交易明细: {trades_file}")
    return results_summary


def main():
    parser = argparse.ArgumentParser(description="Personal Trading Assistant Reconciled Run")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory path")
    parser.add_argument("--data-path", type=str, default=None, help="Input daily bars JSON path")
    parser.add_argument("--cash-apr", type=float, default=0.02, help="Annual cash rate")
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0, help="Initial capital")
    parser.add_argument("--as-of-date", type=str, default=None, help="Expected latest complete trading date (YYYYMMDD)")
    parser.add_argument("--require-completed-bar", action="store_true", default=True, help="Require complete bar for signal evaluation (default: True)")
    parser.add_argument("--allow-incomplete-bar", dest="require_completed_bar", action="store_false", help="Allow incomplete bar for preview")
    args = parser.parse_args()

    out_p = Path(args.output_dir).resolve() if args.output_dir else None
    data_p = Path(args.data_path).resolve() if args.data_path else None
    run_baseline_and_daily_review(
        output_dir=out_p,
        data_path=data_p,
        cash_apr=args.cash_apr,
        initial_capital=args.initial_capital,
        expected_as_of_date=args.as_of_date,
        require_completed_bar=args.require_completed_bar,
    )


if __name__ == "__main__":
    main()

