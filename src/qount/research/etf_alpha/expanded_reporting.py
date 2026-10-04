"""Human-readable v2 result receipt; no fitting or selection."""
from __future__ import annotations


def render_report(summary, config):
    lines = ["# P3 v2 大规模训练结果", "",
        "research_only=true / orders_authorized=false / holdout_role=discovery", "",
        f"状态：{summary['status']}；outer：{summary['outer_test_status']}。",
        f"开始：{summary['started_at']}；结束：{summary.get('finished_at', 'running')}。",
        f"拟合：{summary.get('fits_completed', 0)}/{config['max_fits']}；墙钟：{summary.get('seconds', 0)/3600:.3f} 小时。", "",
        "整轮墙钟上限：" + ("无，固定任务全部完成后退出。" if config.get("max_hours") is None else f"{config['max_hours']} 小时。"), "",
        f"增强数据：{summary['bootstrap_root']}；有效增强日期 {summary.get('usable_augmented_dates', '未完成')}。",
        "Bootstrap 没有增加独立市场观测；真实历史的来源、事件会计与费用限制继续适用。", "",
        "## 已冻结的过去验证选择", "", "| Fold | 选择 | 合格候选 | RankIC 对照门槛（另加 0.01） |",
        "| --- | --- | --- | --- |"]
    for name, selection in summary.get("selections", {}).items():
        lines.append(f"| {name} | {selection['selected']} | {', '.join(selection['eligible'])} | {selection['rank_reference']:.4f} |")
    outer = summary.get("outer_test", {})
    if outer.get("status") == "complete":
        lines += ["", "## 连续外层历史：同窗口、同风险约束、固定五 seed 均值", "",
                  "| Family | 成本 | 年化 CAGR | 现金超额 Sharpe | 最大回撤 | 剔除最好完整年 CAGR |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for name, costs in outer["continuous"].items():
            for cost, value in costs.items():
                sharpe = value["sharpe_excess_cash"]
                sharpe_text = "—" if sharpe is None else f"{sharpe:.3f}"
                lines.append(f"| {name} | {cost} | {value['cagr']:.2%} | {sharpe_text} | {value['max_drawdown']:.2%} | {value['drop_best_complete_year']['cagr']:.2%} |")
        lines += ["", "## 逐 fold 排序能力（固定各 family）", "",
                  "| Family | Fold | RankIC | μ20 Huber |", "| --- | --- | --- | --- |"]
        for name, folds in outer["folds"].items():
            for fold, report in folds.items():
                p = report["prediction"]
                rank = "—" if p["rank_ic"] is None else f"{p['rank_ic']:.4f}"
                lines.append(f"| {name} | {fold} | {rank} | {p['mu20_huber']:.4f} |")
        lines += ["", "2026 为截至 2026-10-01 的部分年度。预测 IC 的标签尾部与组合执行日期分别保留各自正确口径。",
                  "逐年收益、40/60/120 日同步块区间、残差 IC 和全部三档成本报告在 summary.json 与 outer_test/。"]
    else:
        lines += ["", "完整外层结果尚未取得；partial/checkpoint 不能当作已完成模型或正式收益结论。"]
    if summary.get("error"):
        lines += ["", "错误：" + summary["error"]]
    lines += ["", "已消费历史仍为 discovery；A/P/R/F、新鲜确认、DSR/PBO 资格没有因本次训练自动通过。",
              "下一阶段、paper/live 和生产权限没有自动授权；固定任务完成后停止，不自动增加试验。", ""]
    return "\n".join(lines)
