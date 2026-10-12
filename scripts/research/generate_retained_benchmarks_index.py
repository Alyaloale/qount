#!/usr/bin/env python3
"""Generates the lightweight retained benchmarks evidence index for S3-B (R07, R09, R10, R11).

Pure offline audit index linking verdicts, contracts, source codes, and result hashes
without reopening frozen research or retraining.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def build_retained_benchmarks_index() -> Dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()

    # Pre-verify all local files and collect hashes
    local_files_to_hash = [
        "docs/c60-pit-universe-survivorship-2026-09.md",
        "config/c60-gradient-20261011.json",
        "state/research_runs/c60_pit_universe_v1/07b62924514a4386.json",
        "state/research_runs/c60_pit_universe_v1/manifest-6a65831f9efa1dd8.json",
        "state/research_runs/c60_vol_matched_v1/0def726cec0edcf3.json",
        "state/research_runs/research_remediation_20261011/c60-summary.json",
        "state/research_runs/research_remediation_20261011/c60-manifest.json",
        "docs/qount_strategy_master_index.md",
        "config/dual-engine-research-registry.json",
        "docs/dual-engine-optimization-2026-10.md",
        "config/dual-engine-cashflow-20261005.json",
        "config/dual-engine-execution-ownership-20261005.json",
        "docs/cta-r-forward-ledger-2026-09.md",
        "docs/cta-r-us-replication-and-c60-vol-matched-2026-09.md",
        "state/research_runs/cta_r_us_replication_v1/9dc7b5a80cd6ec80/results.json",
        "state/research_runs/cta_r_us_replication_v1/9dc7b5a80cd6ec80/manifest.json",
        "state/research_runs/cta_r_us_replication_v1/9dc7b5a80cd6ec80/closes.json",
        "docs/README-P2.md",
        "docs/etf-p3-research-plan-2026-10.md",
        "config/etf-alpha-residual-reviewed-20261003.json",
        "state/research_runs/etf_alpha_residual_start_20261003T174223Z/final-status.json",
        "state/research_runs/etf_alpha_residual_start_20261003T174223Z/RESULT.md",
        "state/research_runs/etf_alpha_residual_start_20261003T174223Z/summary.json",
        "state/research_runs/etf_alpha_residual_start_20261003T174223Z/exit.json",
    ]

    hashes: Dict[str, str] = {}
    for rel_p in local_files_to_hash:
        full_p = REPO_ROOT / rel_p
        if not full_p.exists():
            raise FileNotFoundError(f"Missing required evidence file: {rel_p}")
        hashes[rel_p] = sha256_file(full_p)

    entries = {
        "R07": {
            "research_line": "R07",
            "name": "Crypto C60 v1/v2, PIT 宇宙幸存者偏差与梯度研究",
            "version": "c60_v2 / c60_pit_universe_v1 / c60_gradient_20261011",
            "current_verdict": "既有无订单模拟及前瞻对照保留；稳定选币优势撤回（PIT 剔除 2021 Sharpe 0.47 < BTC 门 0.69，撤回选币贡献）；梯度/不交易带候选失败（四格换手虽降，但 CAGR 全降，三格回撤恶化），不替换 paper。",
            "status": "RETAINED_BENCHMARK_CONTROL",
            "source_code_pointer": "src/qount/research/c60_*.py",
            "contracts_and_docs": [
                {
                    "path": "docs/c60-pit-universe-survivorship-2026-09.md",
                    "sha256": hashes["docs/c60-pit-universe-survivorship-2026-09.md"],
                    "description": "C60 v2 PIT 宇宙幸存者偏差量化预登记与判定规则",
                },
                {
                    "path": "config/c60-gradient-20261011.json",
                    "sha256": hashes["config/c60-gradient-20261011.json"],
                    "description": "C60 梯度与不交易带冻结合同 (12 曲线暴露)",
                },
                {
                    "path": "docs/research-remediation-plan-2026-10.md",
                    "sha256": sha256_file(REPO_ROOT / "docs/research-remediation-plan-2026-10.md"),
                    "description": "P2 梯度对比执行记录与四格换手/CAGR/回撤完整核算",
                },
            ],
            "results_and_artifacts": [
                {
                    "path": "state/research_runs/c60_pit_universe_v1/07b62924514a4386.json",
                    "sha256": hashes["state/research_runs/c60_pit_universe_v1/07b62924514a4386.json"],
                    "description": "PIT 宇宙重放结果 (CAGR 14.3%, Sharpe 0.56, MDD -45.5%)",
                },
                {
                    "path": "state/research_runs/c60_pit_universe_v1/manifest-6a65831f9efa1dd8.json",
                    "sha256": hashes["state/research_runs/c60_pit_universe_v1/manifest-6a65831f9efa1dd8.json"],
                    "description": "PIT 宇宙 25,270 个月度行情文件 SHA256 清单",
                },
                {
                    "path": "state/research_runs/c60_vol_matched_v1/0def726cec0edcf3.json",
                    "sha256": hashes["state/research_runs/c60_vol_matched_v1/0def726cec0edcf3.json"],
                    "description": "静态与仅 BTC 闸门同波动率对照结果 (仅 BTC 门 Sharpe 0.63/0.69)",
                },
                {
                    "path": "state/research_runs/research_remediation_20261011/c60-summary.json",
                    "sha256": hashes["state/research_runs/research_remediation_20261011/c60-summary.json"],
                    "description": "C60 梯度 12 曲线完整核算摘要 (4 格 CAGR 均降、3 格回撤恶化)",
                },
                {
                    "path": "state/research_runs/research_remediation_20261011/c60-manifest.json",
                    "sha256": hashes["state/research_runs/research_remediation_20261011/c60-manifest.json"],
                    "description": "C60 梯度工件 manifest 回执",
                },
                {
                    "path": "/mnt/e/qount_data/qount/artifacts/dual_engine/gradient_20261011T073000Z_v3",
                    "sha256": "external_storage_directory_verified_on_wsl",
                    "description": "Windows E 盘不可变梯度完整工件根",
                },
            ],
            "inputs_and_evaluation_window": {
                "evaluation_window": "2020-12-06 至 2026-08-31 (2,095 bars)",
                "gradient_window": "2021-01-01 至 2026-08-31",
                "universe_scope": "Binance spot USDT 对，按时点成交额 Top8 + BTC + PAXG，清洗退市共 674 资产",
            },
            "cost_and_cash_assumptions": {
                "base_fee_bps": 25.0,
                "stress_fee_bps": 50.0,
                "execution_style": "T+0, 权重逐日漂移，按换手率扣费",
                "cash_treatment": "未分配及被拒权重留现金，不计现金利息",
            },
            "replay_or_forward_origin": {
                "replay_first_decision_date": "2020-12-06",
                "forward_origin": "2026-09-30 (缺最新前向记录，如实标缺，不回填)",
            },
            "sample_consumption_status": "consumed_historical_discovery_pool",
            "open_unknowns": [
                "时点重放仍假设 t 日有收盘、t+1 无收盘时能在前一收盘卖出（公告时钟与真实成交未完整认证）",
                "自身与 BTC 联合门贡献 82.1% 进出归因，不等于 BTC 单门可消除相同比例摩擦",
                "本地无最新前向账本更新记录，缺口如实标缺",
            ],
            "next_legitimate_check": "未做远端巡检，统一标为 not_checked。仅当同口径时点 pool 与真实前向数据就绪后才行比较。",
            "freshness_status": "not_checked",
            "global_trial_count": None,
        },
        "R09": {
            "research_line": "R09",
            "name": "Dual-Engine G20/C60/GC5/D15 四账户模拟与十七轮离线排名",
            "version": "dual_engine_four_accounts / seventeen_rounds_offline / cashflow_v4",
            "current_verdict": "既有四账户公共数据模拟已部署；YTD 包含历史回放，不是实盘收益；十七轮离线领先仍待新鲜确认，月度重建资金现金流实现失败；离线领先不替换 paper 合同。",
            "status": "RETAINED_BENCHMARK_CONTROL",
            "source_code_pointer": "src/qount/dual_engine/",
            "contracts_and_docs": [
                {
                    "path": "docs/qount_strategy_master_index.md",
                    "sha256": hashes["docs/qount_strategy_master_index.md"],
                    "description": "Dual-Engine 核心策略总集与当前有效模拟盘合同",
                },
                {
                    "path": "config/dual-engine-research-registry.json",
                    "sha256": hashes["config/dual-engine-research-registry.json"],
                    "description": "双引擎机器总登记 (1,151 局部曲线暴露，152 候选)",
                },
                {
                    "path": "docs/dual-engine-optimization-2026-10.md",
                    "sha256": sha256_file(REPO_ROOT / "docs/dual-engine-optimization-2026-10.md"),
                    "description": "双引擎十七轮离线优化与机制诊断专题文档",
                },
                {
                    "path": "config/dual-engine-cashflow-20261005.json",
                    "sha256": hashes["config/dual-engine-cashflow-20261005.json"],
                    "description": "第十七轮月度资金流重组冻结合同",
                },
                {
                    "path": "config/dual-engine-execution-ownership-20261005.json",
                    "sha256": hashes["config/dual-engine-execution-ownership-20261005.json"],
                    "description": "第十六轮来源权属冻结合同",
                },
            ],
            "results_and_artifacts": [
                {
                    "path": "config/dual-engine-research-registry.json",
                    "sha256": hashes["config/dual-engine-research-registry.json"],
                    "description": "十七轮历史离线排名机器登记与领先者标记",
                },
                {
                    "path": "/mnt/e/qount_data/qount/artifacts/dual_engine/ownership_20261005T124238Z/registry",
                    "sha256": "f712bcd72bdb5be199ad74a7ede3318e6bd79363b7b941a888a4916a573d335b",
                    "description": "第十六轮来源权属注册根 manifest hash",
                },
                {
                    "path": "/mnt/e/qount_data/qount/artifacts/dual_engine/cashflow_20261006T075644Z_v4/registry",
                    "sha256": "b302fcb8f7a3e9f62c68307bc51d18c9ffbf5bd1466102bd6becf6cb2041a579",
                    "description": "第十七轮资金现金流尝试注册根 manifest hash",
                },
            ],
            "inputs_and_evaluation_window": {
                "evaluation_window": "2018 至 2026 离线研究；YTD 回放从 2026-01-01 起",
                "universe_scope": "G20 (7杠杆ETF+BIL), C60 (10加密标的), GC5 (95/5固定配比), D15 (动态加密预算 2.5-15%)",
            },
            "cost_and_cash_assumptions": {
                "g20_fee_bps": 20.0,
                "c60_fee_bps": 25.0,
                "c60_stress_bps": 50.0,
                "cash_treatment": "G20 以 BIL 短期国债为现金代理，C60 为无息现金，D15 允许月度跨袖套再平衡",
            },
            "replay_or_forward_origin": {
                "ytd_replay_origin": "2026-01-01T00:00:00Z",
                "first_accounting_point": "2026-01-02T15:00:30Z",
                "forward_health": "not_checked",
            },
            "sample_consumption_status": "consumed_historical_discovery_pool",
            "open_unknowns": [
                "月度资金现金流实现失败，重建毛额收入被摩擦吞噬，结算机制 unknown",
                "目标风险预算与实际持仓漂移未在会计中分列",
                "市场图中 SPY benchmark bars 为 0，缺乏同区间基准超额检验",
            ],
            "next_legitimate_check": "未做远端巡检，统一标为 not_checked。须待精确结算证据与新鲜前向记录后才行评估。",
            "freshness_status": "not_checked",
            "global_trial_count": None,
        },
        "R10": {
            "research_line": "R10",
            "name": "CTA-R 跨资产趋势追踪与美股 ETF 复现",
            "version": "cta_r_paper / Trial 151 US replication / D1 forward ledger",
            "current_verdict": "独立 research-paper 侧车／前瞻账本已登记部署；冻结规则美股复现通过最低研究门（5/5 门全过，Sharpe 0.75），但未超过 60/40 Sharpe (0.78)，未获晋级；成本／可交易性与前向一致性待确认。",
            "status": "RETAINED_BENCHMARK_CONTROL",
            "source_code_pointer": "src/qount/research/cta_r_*.py",
            "contracts_and_docs": [
                {
                    "path": "docs/cta-r-forward-ledger-2026-09.md",
                    "sha256": hashes["docs/cta-r-forward-ledger-2026-09.md"],
                    "description": "CTA-R D1 前瞻账本冻结合同与停止条件",
                },
                {
                    "path": "docs/cta-r-us-replication-and-c60-vol-matched-2026-09.md",
                    "sha256": hashes["docs/cta-r-us-replication-and-c60-vol-matched-2026-09.md"],
                    "description": "Trial 151 美股 ETF 复现预登记协议与运行结果",
                },
            ],
            "results_and_artifacts": [
                {
                    "path": "state/research_runs/cta_r_us_replication_v1/9dc7b5a80cd6ec80/results.json",
                    "sha256": hashes["state/research_runs/cta_r_us_replication_v1/9dc7b5a80cd6ec80/results.json"],
                    "description": "Trial 151 美股复现结果 (Sharpe 0.75, CAGR 7.4%, MDD -17.1%, 5/5 门 PASS)",
                },
                {
                    "path": "state/research_runs/cta_r_us_replication_v1/9dc7b5a80cd6ec80/manifest.json",
                    "sha256": hashes["state/research_runs/cta_r_us_replication_v1/9dc7b5a80cd6ec80/manifest.json"],
                    "description": "Trial 151 工件 manifest 清单",
                },
                {
                    "path": "state/research_runs/cta_r_us_replication_v1/9dc7b5a80cd6ec80/closes.json",
                    "sha256": hashes["state/research_runs/cta_r_us_replication_v1/9dc7b5a80cd6ec80/closes.json"],
                    "description": "Tiingo 美股 8 只 ETF 共同交易日价格序列",
                },
                {
                    "path": "/var/www/qount/data/cta_r_paper.json",
                    "sha256": "vps_remote_not_checked",
                    "description": "VPS 侧车重建工件 (未做实时远端巡检)",
                },
                {
                    "path": "/var/lib/qount/research/cta-r-forward/seed/",
                    "sha256": "vps_remote_not_checked",
                    "description": "VPS 前瞻账本 hash 链状态目录",
                },
            ],
            "inputs_and_evaluation_window": {
                "evaluation_window": "美股复现 2004-11-18 至 2026-09-28 (5,498 交易日，249 次调仓，评估自 2005-12-19)",
                "universe_scope": "美股 8 只 ETF (SPY, IWM, QQQ, DIA, GLD, IEF, EFA, EEM)；A 股 8 只 ETF (510300, 510500 等)",
            },
            "cost_and_cash_assumptions": {
                "us_replication_fee_bps": 10.0,
                "us_stress_fee_bps": 20.0,
                "a_share_sidecar_fee_bps": 2.0,
                "a_share_stress_fee_bps": 10.0,
                "cash_treatment": "超出 0.35 仓位上限留现金，现金不计息",
            },
            "replay_or_forward_origin": {
                "forward_genesis_date": "2026-09-29 收盘后状态 (bar 2848, 净值 10,000)",
                "forward_start_date": "2026-09-30",
                "forward_health": "not_checked",
            },
            "sample_consumption_status": "consumed_historical_discovery_pool",
            "open_unknowns": [
                "美股最低门通过未超过 60/40 Sharpe (0.78)，DSR 0.757 未达 0.95 门槛",
                "侧车 (2 bps)、重认证 (10 bps) 与美股复现 (10/20 bps) 成本不一致",
                "跨境 ETF 溢价及个人账户实际可交易性受限",
            ],
            "next_legitimate_check": "每 6 个 21 日调仓周期做一致性检查 (约 126 个交易日)。未做远端巡检，统一标为 not_checked。",
            "freshness_status": "not_checked",
            "global_trial_count": 151,
        },
        "R11": {
            "research_line": "R11",
            "name": "ETF Trader P2/P3 Alpha 与 R3 残差 Pilot 试验",
            "version": "P2_Stage_B / P3_v2_Alpha / R3_residual_pilot_20261003",
            "current_verdict": "P2 停训回收；P3 v2 完成（未胜过简单动量）；R3 pilot 真实候选（MLP / Ridge）未通过增量门（40/60/120 日块 95% 置信区间下界全跨零），选择回落 zero_residual_reconstruction，按协议停止；outer withheld；51-fit 单轮授权已消费，无自动重启、扩容或云端恢复。",
            "status": "FROZEN_REPLACED_CONTROL",
            "source_code_pointer": "src/qount/research/etf_trader/ 与 src/qount/research/etf_alpha/",
            "contracts_and_docs": [
                {
                    "path": "docs/README-P2.md",
                    "sha256": hashes["docs/README-P2.md"],
                    "description": "ETF Trader P2/P3 统一入口导航与状态说明",
                },
                {
                    "path": "docs/etf-p3-research-plan-2026-10.md",
                    "sha256": hashes["docs/etf-p3-research-plan-2026-10.md"],
                    "description": "P3 分层重构设计与 §24 R3 残差 pilot 执行结果",
                },
                {
                    "path": "config/etf-alpha-residual-reviewed-20261003.json",
                    "sha256": hashes["config/etf-alpha-residual-reviewed-20261003.json"],
                    "description": "R3 开训前复审 runtime-v2 冻结合同",
                },
            ],
            "results_and_artifacts": [
                {
                    "path": "state/research_runs/etf_alpha_residual_start_20261003T174223Z/final-status.json",
                    "sha256": hashes["state/research_runs/etf_alpha_residual_start_20261003T174223Z/final-status.json"],
                    "description": "R3 pilot 最终状态 (status=pilot_no_increment, fits=51/51, outer_test_status=withheld)",
                },
                {
                    "path": "state/research_runs/etf_alpha_residual_start_20261003T174223Z/RESULT.md",
                    "sha256": hashes["state/research_runs/etf_alpha_residual_start_20261003T174223Z/RESULT.md"],
                    "description": "R3 pilot 核心结果报告 (置信区间下界跨零，回落 zero_residual)",
                },
                {
                    "path": "state/research_runs/etf_alpha_residual_start_20261003T174223Z/summary.json",
                    "sha256": hashes["state/research_runs/etf_alpha_residual_start_20261003T174223Z/summary.json"],
                    "description": "R3 pilot 运行元数据与退出回执",
                },
                {
                    "path": "state/research_runs/etf_alpha_residual_start_20261003T174223Z/exit.json",
                    "sha256": hashes["state/research_runs/etf_alpha_residual_start_20261003T174223Z/exit.json"],
                    "description": "R3 pilot 进程退出码与耗时 (exit_code=0, 55.36s 拟合)",
                },
                {
                    "path": "/mnt/e/qount_data/qount/artifacts/etf_alpha_p3/residual_run_20261003T174223Z",
                    "sha256": "312d1a8c7746515766b367204d8c10e870300b1dbf62ed96704877c27c204297",
                    "description": "E 盘不可变 R3 pilot 完整结果 manifest SHA256",
                },
                {
                    "path": "/mnt/e/qount_data/qount/artifacts/etf_alpha_p3/residual_ready_20261003T141654Z",
                    "sha256": "d985ba9a6fc7f964b984a695ca58ff8d78e8881acac92b0b85b0342f4f9eeed4",
                    "description": "E 盘不可变 R3 准备工件 manifest SHA256",
                },
            ],
            "inputs_and_evaluation_window": {
                "inner_evaluation_window": "2017–2019 三年连续 inner 验证 (51 fits = 45 神经 + 6 Ridge)",
                "outer_test_status": "2020–2026 outer withheld (严禁接触，未消费)",
                "universe_scope": "8 只美股 ETF 面板特征与收益重构标签",
            },
            "cost_and_cash_assumptions": {
                "model_cost": "2× 交易成本连续组合评估",
                "cash_treatment": "现金利息计入超额 Sharpe 口径",
            },
            "replay_or_forward_origin": {
                "forward_origin": None,
                "forward_health": "not_applicable",
            },
            "sample_consumption_status": "inner_consumed_outer_withheld",
            "open_unknowns": [
                "40/60/120 日块 95% 置信区间下界跨零，残差预测增量未在统计上显著区分于空对照",
                "固定 120 日动量 (CAGR 8.11%) 与训练资产均值 (CAGR 9.33%) 在 inner 年化收益更高",
                "无 outer 结果，不假设泛化性能",
            ],
            "next_legitimate_check": "无自动重启或云端恢复授权；仅当提出全新可解释信息源或小容量增量机制并获批准时才考虑新实验。当前标为 not_checked。",
            "freshness_status": "not_checked",
            "global_trial_count": None,
        },
    }

    return {
        "schema_version": "1.0.0",
        "stage": "S3-B",
        "title": "Retained Benchmarks Lightweight Evidence Index",
        "generated_at": now_iso,
        "authoritative_source": "docs/current.md",
        "plan_source": "docs/research-repair-and-consolidation-plan-2026-10.md",
        "safety_boundaries": {
            "research_only": True,
            "orders_authorized": False,
            "promotion_evidence": False,
        },
        "description": "Lightweight evidence index for retained benchmark controls (R07, R09, R10, R11). Verifiable pointers, hashes, cost/cash assumptions, evaluation windows, and known gaps without reopening frozen research or retraining.",
        "entries": entries,
    }


def main() -> None:
    index_data = build_retained_benchmarks_index()
    out_path = REPO_ROOT / "state" / "research_runs" / "retained_benchmarks_index_20261012.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2, ensure_ascii=False)
    print(f"Generated retained benchmarks index at {out_path} ({len(index_data['entries'])} entries).")


if __name__ == "__main__":
    main()
