# P2 历史记录索引

> **状态**：historical / non-restorable evidence｜**权威**：历史分类导航，不维护当前事实｜**更新时间**：2026-10-02
> **TL;DR**：保留 64 份既有历史记录，归档 18 份旧文档及 1 段实施快照；错误结论通过撤回说明追溯，当前架构与结果集中在研究主文档。

`research_only=true / orders_authorized=false`。旧文档标题中的“最终”“完成”“成功”与正文中的“当前”均按原日期理解；不得据其启动训练、调整服务、恢复订单或声明正式验收通过。
历史代码块中的安装、同步、启动与提交命令仅作证据；部分结论已被实际测试推翻，认证字面值已清除。

## 当前替代入口

- [唯一当前事实与权限](../../current.md)
- [当前架构、双端训练与真实历史结果](../../p2-project-summary-20261002.md)
- [设计与正式验收协议](../../etf-imitation-policy-design-2026-09.md)
- [P2 当前文档导航](../../README-P2.md)
- [本轮移动与 hash 审计](archive-audit-20261002.md)、[批准记录](../manifest.md)

## 本轮归档的时点记录

| 记录 | 阅读限制 |
| --- | --- |
| [2026-10-01 实施与生成器诊断](snapshots/implementation-20261001.md) | 从设计 §11.1 拆出；基础设施完成不是最终训练完成；原小节存在前后更新不一致 |
| [2026-10-02 14:12 训练进度](snapshots/p2-training-progress-20261002-1412.md) | 仅是原时点记录，不能覆盖 16:39 核查或 17:18 停训证据 |
| [旧 RECENT_UPDATES](snapshots/RECENT_UPDATES.md) | 旧监控、预计时间与接手命令，不是当前运行手册 |
| [旧云服务器配置建议](snapshots/cloud-server-setup.md) | 旧通用安装建议，不是实际保存环境；实际版本见回收 environment.json |

## 已撤回结论的说明

这些文件保留已修正的撤回说明，方便识别过去的接口、基准、收益推测与状态误判。统一结论与复现方式见当前研究主文档。

- [P2-DOCS-CLEANUP-SUMMARY](corrections-20261002/P2-DOCS-CLEANUP-SUMMARY.md)
- [P2-DOCS-CLEANUP](corrections-20261002/P2-DOCS-CLEANUP.md)
- [P2-FINAL-STATUS](corrections-20261002/P2-FINAL-STATUS.md)
- [P2-HANDOVER](corrections-20261002/P2-HANDOVER.md)
- [P2-PROJECT-FINAL-REPORT](corrections-20261002/P2-PROJECT-FINAL-REPORT.md)
- [P2-TODAY-SUMMARY](corrections-20261002/P2-TODAY-SUMMARY.md)
- [ann_log_return-explanation](corrections-20261002/ann_log_return-explanation.md)
- [p2-backtest-environment-issue](corrections-20261002/p2-backtest-environment-issue.md)
- [p2-backtest-implementation-complete](corrections-20261002/p2-backtest-implementation-complete.md)
- [p2-backtest-reality-check](corrections-20261002/p2-backtest-reality-check.md)
- [p2-environment-setup](corrections-20261002/p2-environment-setup.md)
- [p2-next-steps-20261002](corrections-20261002/p2-next-steps-20261002.md)
- [p2-performance-results-20261002](corrections-20261002/p2-performance-results-20261002.md)
- [p2-return-analysis](corrections-20261002/p2-return-analysis.md)
- [wsl_final_report](corrections-20261002/wsl_final_report.md)

## 计划、设计与实现记录

- [p2-backtest-plan](p2-backtest-plan.md)
- [p2-dual-gpu-training-plan](p2-dual-gpu-training-plan.md)
- [p2-execution-guide](p2-execution-guide.md)
- [p2-execution-plan](p2-execution-plan.md)
- [p2-implementation-complete](p2-implementation-complete.md)
- [p2-monitoring-improvements](p2-monitoring-improvements.md)
- [p2-phase1-2-implementation](p2-phase1-2-implementation.md)
- [p2-rl-implementation-review](p2-rl-implementation-review.md)
- [p2-training-params-analysis](p2-training-params-analysis.md)
- [p2-wsl-auto-training-setup](p2-wsl-auto-training-setup.md)

## 优化、性能与问题诊断

- [p2-3090-batch-gap-explanation](p2-3090-batch-gap-explanation.md)
- [p2-3090-episode0-analysis](p2-3090-episode0-analysis.md)
- [p2-3090-episode1-analysis](p2-3090-episode1-analysis.md)
- [p2-3090-gap-cache-analysis](p2-3090-gap-cache-analysis.md)
- [p2-3090-optimization-restart](p2-3090-optimization-restart.md)
- [p2-3090-optimization-success](p2-3090-optimization-success.md)
- [p2-bottleneck-analysis](p2-bottleneck-analysis.md)
- [p2-cpp-engine-verification](p2-cpp-engine-verification.md)
- [p2-debug-status](p2-debug-status.md)
- [p2-episode1-breakthrough](p2-episode1-breakthrough.md)
- [p2-final-optimization](p2-final-optimization.md)
- [p2-gpu-idle-analysis](p2-gpu-idle-analysis.md)
- [p2-hardware-analysis](p2-hardware-analysis.md)
- [p2-optimization-final-summary](p2-optimization-final-summary.md)
- [p2-optimization-in-progress](p2-optimization-in-progress.md)
- [p2-optimization-plan](p2-optimization-plan.md)
- [p2-optimization-solutions](p2-optimization-solutions.md)
- [p2-parallel-implementation](p2-parallel-implementation.md)
- [p2-parallel-optimization](p2-parallel-optimization.md)
- [p2-pipeline-implementation](p2-pipeline-implementation.md)
- [p2-pipeline-optimization](p2-pipeline-optimization.md)
- [p2-wsl-fix-verification](p2-wsl-fix-verification.md)

## 训练状态与时点检查

- [p2-deployment-status-final](p2-deployment-status-final.md)
- [p2-dual-auto-training-final](p2-dual-auto-training-final.md)
- [p2-dual-check-final](p2-dual-check-final.md)
- [p2-dual-final-analysis](p2-dual-final-analysis.md)
- [p2-dual-gpu-status-analysis](p2-dual-gpu-status-analysis.md)
- [p2-dual-progress-comparison-0357](p2-dual-progress-comparison-0357.md)
- [p2-dual-progress-comparison](p2-dual-progress-comparison.md)
- [p2-dual-status-1238](p2-dual-status-1238.md)
- [p2-dual-test-final-report](p2-dual-test-final-report.md)
- [p2-dual-test-running](p2-dual-test-running.md)
- [p2-dual-training-check-complete](p2-dual-training-check-complete.md)
- [p2-dual-training-final-summary](p2-dual-training-final-summary.md)
- [p2-dual-training-running-summary](p2-dual-training-running-summary.md)
- [p2-dual-training-status-20261002-1408](p2-dual-training-status-20261002-1408.md)
- [p2-dual-training-status](p2-dual-training-status.md)
- [p2-dual-validation-ready](p2-dual-validation-ready.md)
- [p2-final-comprehensive-check](p2-final-comprehensive-check.md)
- [p2-final-status-0405](p2-final-status-0405.md)
- [p2-final-status-report](p2-final-status-report.md)
- [p2-full-training-launch](p2-full-training-launch.md)
- [p2-phase1-2-complete](p2-phase1-2-complete.md)
- [p2-progress-update-0221](p2-progress-update-0221.md)
- [p2-ready-status](p2-ready-status.md)
- [p2-realtime-status](p2-realtime-status.md)
- [p2-server-realtime-status](p2-server-realtime-status.md)
- [p2-training-final-summary](p2-training-final-summary.md)
- [p2-training-launch-confirmation](p2-training-launch-confirmation.md)
- [p2-training-log-20261002](p2-training-log-20261002.md)
- [p2-training-progress-analysis](p2-training-progress-analysis.md)
- [p2-training-success-20261002](p2-training-success-20261002.md)
- [p2-training-summary](p2-training-summary.md)
- [p2-wsl-completion-analysis](p2-wsl-completion-analysis.md)

## 保留与恢复边界

本目录保留历史叙述，不是部署包。代码、数据、checkpoint、日志和完整回收 manifest 的外置盘位置仅由研究主文档统一说明；本轮没有移动或删除这些运行产物，也没有变更模型、约束或主机服务。
