"""Readable immutable review of a completed/partial frozen training run."""
from __future__ import annotations

import csv
from pathlib import Path
from statistics import mean, median

from .artifacts import GUARDS, finish_manifest, new_directory, read_json, sha256, verify_files, write_json


def _number(value, *, percent=False):
    if value is None:
        return "不可用"
    return f"{value * 100:.2f}%" if percent else f"{value:.4f}"


def write_review(source: Path, out: Path) -> dict:
    """Read only declared hashed files; never fit or use test metrics to select."""
    manifest = read_json(source / "manifest.json")
    verify_files(source, manifest["files"])
    summary = read_json(source / "summary.json")
    environment = read_json(source / "environment.json")
    if summary.get("research_only") is not True or summary.get("orders_authorized") is not False:
        raise ValueError("a research-only source run is required")
    new_directory(out)
    rows = []
    for fold, selection in sorted(summary.get("selections", {}).items()):
        records = read_json(source / fold / "screening-diagnostics.json")
        for name, seeds in records.items():
            if not seeds:
                continue
            rank = [r["prediction"]["rank_ic"] for r in seeds if r["prediction"]["rank_ic"] is not None]
            rows.append({"fold": fold, "configuration": name, "seeds": len(seeds),
                "parameters": seeds[0]["parameters"], "mu20_huber": mean(r["prediction"]["mu20_huber"] for r in seeds),
                "median_rank_ic": median(rank) if rank else None,
                "mean_2x_cagr": mean(r["bridge"]["2x"]["cagr"] for r in seeds),
                "mean_2x_sharpe": mean(r["bridge"]["2x"]["sharpe_excess_cash"] for r in seeds),
                "mean_2x_mdd": mean(r["bridge"]["2x"]["max_drawdown"] for r in seeds),
                "selected": name == selection["selected"]})
    with (out / "validation-leaderboard.csv").open("x", newline="") as stream:
        columns = ["fold", "configuration", "seeds", "parameters", "mu20_huber", "median_rank_ic",
                   "mean_2x_cagr", "mean_2x_sharpe", "mean_2x_mdd", "selected"]
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    lines = ["# ETF P3 自动训练结果", "", "research_only=true / orders_authorized=false / holdout_role=discovery", "",
        f"运行状态：**{summary['status']}**；外层测试：**{summary['outer_test_status']}**。",
        f"完成 {summary['fits_completed']} 次拟合，启动 {summary['fits_started']} 次，记录失败 {len(summary.get('failures', []))} 次。",
        f"总耗时 {summary['seconds'] / 60:.2f} 分钟；开始 {summary['started_at']}，结束 {summary['finished_at']}（UTC）。", "",
        f"GPU：{environment['gpu']}；Torch {environment['torch']} / CUDA {environment['cuda']}。",
        f"原始 run：`{source}`；输入与本报告分别使用 SHA256 清单回读验证。", "",
        "这些结果是已接受历史来源限制下的探索性研究；预测/组合/稳健性/新鲜确认门仍须逐项审核，不能作为生产授权。", "",
        "## 过去验证区间的冻结选择", "",
        "| Fold | 选择 | E4 多任务保留 | 静态市场保留 | GRU 同时优于 parent/静态 |", "| --- | --- | --- | --- | --- |"]
    for fold, selection in sorted(summary.get("selections", {}).items()):
        retained = lambda x: "是" if x else "否"
        lines.append(f"| {fold} | {selection['selected']} | {retained(selection['E4']['retained'])} | "
                     f"{retained(selection['E5_static']['retained'])} | "
                     f"{retained(selection['E5_gru_parent']['retained'] and selection['E5_gru_static']['retained'])} |")
    outer = summary.get("outer_test", {})
    if outer.get("status") == "complete":
        lines += ["", "## 冻结后的连续外层测试", "", "| 成本 | CAGR | 现金超额 Sharpe | MDD | 剔除最好完整年 CAGR |",
                  "| --- | --- | --- | --- | --- |"]
        for cost, metrics in outer["continuous"].items():
            lines.append(f"| {cost} | {_number(metrics['cagr'], percent=True)} | {_number(metrics['sharpe_excess_cash'])} | "
                         f"{_number(metrics['max_drawdown'], percent=True)} | "
                         f"{_number(metrics['drop_best_complete_year']['cagr'], percent=True)} |")
        lines += ["", "持仓、DD 和换手状态跨年度连续；ensemble 固定平均最初五个 seed，追加五个 seed 单独保存。2026 为部分年度。", "",
                  "| Fold | 模型 | RankIC | 标准化 Huber | 2× CAGR | 2× MDD |", "| --- | --- | --- | --- | --- | --- |"]
        for fold, record in outer["folds"].items():
            p, b = record["prediction"], record["bridge"]["2x"]
            lines.append(f"| {fold} | {record['model']} | {_number(p['rank_ic'])} | {_number(p['mu20_huber'])} | "
                         f"{_number(b['cagr'], percent=True)} | {_number(b['max_drawdown'], percent=True)} |")
        lines += ["", "| 年份 | 2× 净收益 | 交易日 | 年份状态 |", "| --- | --- | --- | --- |"]
        for year, values in outer["continuous"]["2x"]["annual"].items():
            lines.append(f"| {year} | {_number(values['return'], percent=True)} | {values['days']} | "
                         f"{'部分年度' if values['partial'] else '完整年度'} |")
    else:
        lines += ["", "外层测试尚未完整完成；没有用不完整结果生成正式连续收益结论。"]
    if summary.get("failures") or summary.get("error"):
        lines += ["", "## 失败记录", "", f"运行错误：{summary.get('error', '无')}。"]
        lines += [f"- {r['fold']} / {r['model']} / seed {r['seed']}: {r['error']}" for r in summary.get("failures", [])]
    lines += ["", "## 查看详细证据", "", "- 本目录 `validation-leaderboard.csv`：每个 fold/配置的全部初筛 seed 汇总。",
              "- 原始 run `summary.json`：三档成本、年度、预测/校准和区间诊断。",
              "- 原始 run `<fold>/selection.json`：每项保留/拒绝规则与 test 未参与选择的记录。",
              "- 原始 run `<fold>/<model>/seed_<seed>/`：best/last、history、预测、IC、成本曲线、诊断和异常。",
              "- 原始 run `events.jsonl` / 同级 console log：逐轮进度、编译重试日志、GPU/CPU/温度/空间。",
              "- 原始 run `family-review.json`：E3/E4/E5 复盘；没有自动授权 Stage 2、新 trial 或生产。", ""]
    (out / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    review = GUARDS | {"source_run": str(source), "source_manifest_sha256": sha256(source / "manifest.json"),
                      "source_status": summary["status"], "fits_completed": summary["fits_completed"],
                      "outer_test_status": summary["outer_test_status"], "validation_configurations": len(rows)}
    write_json(out / "review.json", review)
    return finish_manifest(out, schema="etf-alpha-readable-review-v1", **review)
