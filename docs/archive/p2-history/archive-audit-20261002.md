# P2 文档归档审计（2026-10-02）

> **状态**：historical / non-restorable evidence｜**权威**：本轮文档归档执行记录｜**日期**：2026-10-02
> **TL;DR**：owner 明确授权后先登记 approved、再移动 18 份文档，另拆出 1 段实施历史；研究代码、模型和数据路径未移动。

当前入口为 [研究主文档](../../p2-project-summary-20261002.md)、[设计参考](../../etf-imitation-policy-design-2026-09.md) 与 [current.md](../../current.md)。
批准记录见 [archive manifest](../manifest.md)，分类入口见 [README](README.md)。

## 引用与保留范围

- 移动前扫描 docs、scripts、src、tests，并使用 rg 扩展至根导航及隐藏上下文；没有代码、部署或测试依赖待移动文档。唯一外部旧入口为 .claude-context 中的 RECENT_UPDATES，已改指当前 README-P2。
- 既有 64 份历史记录保留原路径，增加历史/非恢复提示；29 份含认证字面值的历史文档已清除该内容，私有认证配置没有修改。未创建含凭据的原文备份。
- 以下 hash 指本轮开始移动时的现存正文与归档完成后的正文；15 份撤回说明保留的是已修正的现存版本，不冒称本轮恢复了更早完整报告。
- 差异限于归档提示、相对链接和认证字面值清除；拆出的设计 §11.1 保留原研究叙述，并说明前后更新不一致和未经本轮重新验收。
- 所有记录均为 research_only=true / orders_authorized=false，历史代码块不是可恢复运行指令。

## 路径与内容审计

| 原路径 | 归档正文 | 移动前 SHA256 | 归档后 SHA256 |
| --- | --- | --- | --- |
| `docs/P2-FINAL-STATUS.md` | [P2-FINAL-STATUS.md](corrections-20261002/P2-FINAL-STATUS.md) | `a331b8f3e1aacdd662cd14e6711804b6406e44af7a9598c894190e66e100913d` | `2a7156ce2cb8943bdfd8cbaa6b14319980b48684ef007ac4367cffd55a42cbb6` |
| `docs/P2-PROJECT-FINAL-REPORT.md` | [P2-PROJECT-FINAL-REPORT.md](corrections-20261002/P2-PROJECT-FINAL-REPORT.md) | `739dab48b715c81371400d90e4b304624ee04c98a68c31921ec1b432f6196118` | `6313f6aaf20e67d927eae01ab58719a4dc16271e855367653ae562d884ad4455` |
| `docs/P2-TODAY-SUMMARY.md` | [P2-TODAY-SUMMARY.md](corrections-20261002/P2-TODAY-SUMMARY.md) | `f273f01bba137f5727a1434e2adf7879dc95670a2f88a67d20cd0120919b6e08` | `22b247bd48ce003f2c20a43edb40d76e998e76c77559c5fc98088979c4c7b8f4` |
| `docs/P2-HANDOVER.md` | [P2-HANDOVER.md](corrections-20261002/P2-HANDOVER.md) | `a9b1575fc545f7d43a3403c6715d47d26e3a29e031e92b2ab36caa65592291c1` | `da4d3401157e4f2068d7f528ac0909be3da9d69335f0a6848621db597ac4b534` |
| `docs/P2-DOCS-CLEANUP.md` | [P2-DOCS-CLEANUP.md](corrections-20261002/P2-DOCS-CLEANUP.md) | `bb71cc8b1a83e1e6a5049867fc01b0e7f0e7e07053b516c6b56ed977ee0b99f8` | `250d5c63d4e2832166abcef312add92d448ddd65bd436a206d27f56b57874162` |
| `docs/P2-DOCS-CLEANUP-SUMMARY.md` | [P2-DOCS-CLEANUP-SUMMARY.md](corrections-20261002/P2-DOCS-CLEANUP-SUMMARY.md) | `da73df6cdbf3607a7a0936e1222d9adaba4c1f0993ba7323bfaf2d39d0629c62` | `fe7559143df379767d16055c06a1a2d50520df67e9c64cce6c06e2a7dbd9b5e3` |
| `docs/p2-performance-results-20261002.md` | [p2-performance-results-20261002.md](corrections-20261002/p2-performance-results-20261002.md) | `45e833bc0dc7d3d8157dd5d7a180bab1e58f5343449618db8f84983fbcb92115` | `405545577050b4858737d5af6d6d5b990df2bcd508b856d0d4e03841c4746515` |
| `docs/p2-return-analysis.md` | [p2-return-analysis.md](corrections-20261002/p2-return-analysis.md) | `bc77a747746fd70ce1891bb7b45a1f9cf5412206a69bb29aefab4439d9dc6fda` | `6ed1a27ee2c5b07e2c85bba8dfe85c4217324420e6d30ae02147a484d4782deb` |
| `docs/p2-backtest-reality-check.md` | [p2-backtest-reality-check.md](corrections-20261002/p2-backtest-reality-check.md) | `732bbbf5ebbd4c802c7ec7f1ce104977874b6553c314f4a30cabaeece758eb37` | `15a73682dcc95b424c944252df9a1741e6e0a7c69757c108ec4435091848719f` |
| `docs/p2-backtest-implementation-complete.md` | [p2-backtest-implementation-complete.md](corrections-20261002/p2-backtest-implementation-complete.md) | `fbcb6851026bcfc84857db79d50ad0eca73aaedbc2e21141dc797302ee49c748` | `b036f9eb261f07a18618db6e3758472587ebdc872af63786115abb3d0be0af32` |
| `docs/p2-backtest-environment-issue.md` | [p2-backtest-environment-issue.md](corrections-20261002/p2-backtest-environment-issue.md) | `bf1e2477def9742fc1707b66494148cc67cda30302d1c8b8577a9d7b52f19878` | `49abb73264b478b4b1ee18827a0d6e35e8532c66a360097894ad16ae9a406a4d` |
| `docs/p2-next-steps-20261002.md` | [p2-next-steps-20261002.md](corrections-20261002/p2-next-steps-20261002.md) | `1f29c583e10f209e1eecf90080d7553a270dca0ae104fd793edfcb2b0f4ee53a` | `cfdb11ccd6c14defe55444f73d8203ba8520c8674e701cff25ede5ccca2fa19b` |
| `docs/p2-environment-setup.md` | [p2-environment-setup.md](corrections-20261002/p2-environment-setup.md) | `d94d142b0f9c7f696f82849c4b1684499a4136503a2ff081e455d583a22064da` | `44c6c4dba4bbac96b6913036bacd08b3071757f94875b8d29a766b90b1a57d6e` |
| `docs/wsl_final_report.md` | [wsl_final_report.md](corrections-20261002/wsl_final_report.md) | `3fdc21cf40b96f8097b27d232a5262ba0429a09cb9bb2ad9f97d02379bfed3b9` | `611d3247c5eb7a16a915b938c6b3b26d163b9df1e6fca503a57e12e488fc1702` |
| `docs/ann_log_return-explanation.md` | [ann_log_return-explanation.md](corrections-20261002/ann_log_return-explanation.md) | `bb576b0a2162e7480973b395bc7853e1114656195c9348c9590ec3c6f18838ca` | `eb7b2fe4fb5b8f01fc59dfb95779d6c6f87f213fdd9304ab387e1bfaf2d3e0d5` |
| `docs/p2-training-progress-20261002-1412.md` | [p2-training-progress-20261002-1412.md](snapshots/p2-training-progress-20261002-1412.md) | `8bd606ec3455755da31861fe8d22ddcfccb5cca2c1f277a05c98c56b19c1bc29` | `3dd5b9d346a67452b9ef9d4bd928ecedde472a3367acb1ed0fec895b8149975a` |
| `docs/RECENT_UPDATES.md` | [RECENT_UPDATES.md](snapshots/RECENT_UPDATES.md) | `e6110e24d6e9dd776c4c57e3ea9d06191ef4723ebecc0eefefa7740c5247434b` | `8932a295ec638c27a2c2ef594e2b774bdf9d3c9cda5c1823a5c0a565591623d1` |
| `docs/cloud-server-setup.md` | [cloud-server-setup.md](snapshots/cloud-server-setup.md) | `0144607f7d35c8b53b1e52958732e37154e48780ac4d4555026bed8699da6ac1` | `0a0676f478411064ae076baadb067d8f0e5917de6676b82d551120f3a42c8ab2` |

设计 §11.1 的正文另见 [implementation-20261001.md](snapshots/implementation-20261001.md)；原设计文件保留稳定路径及替代链接。

## 验证记录

本轮实际执行：

- 移动前、移动后 `PYTHONPATH=src ./.venv/bin/python scripts/maintenance/repository_hygiene.py check` 均通过；active Markdown、部署引用、生产导入边界和环境合同无错误。
- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_repository_hygiene`：4 项通过。
- `git diff --check`：通过。
- 补充核对 24 份当前入口/新归档正文的 259 个相对链接与标题锚点：无缺路径或缺锚点；不把既有历史正文内的旧命令当成导航。
- 18 份移动正文的归档后 SHA256 与上表逐项匹配，原路径均已移除；已知 3090 认证字面值在 P2 归档中匹配为 0。
- 按实际 MLP/GRU/输出头维度复核参数量：默认 phi32/h64/L1 为 29,256，实测 WSL phi32/h32/L2 为 18,632，云端 phi32/h16/L2 为 7,752。

动作、持仓和年度表直接摘自既有 `results.json`；训练配置核对既有 `checkpoint-validation.json`。本轮仅整理文档，没有重新训练、重新回测或重新暴露历史测试窗口，没有运行全仓回归。
