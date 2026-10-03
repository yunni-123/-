# 科研计算可复现性验证智能体（B4 · agi队 · 南京理工大学 · U084）

> 给定一个科研计算仓库 + 论文宣称的期望数值，本智能体自动完成「构建隔离环境 → 跑两次 → 逐项比对期望值 → 定位根因 → 最小修复并沙箱验证」，输出带置信度的可复现性诊断报告。

## 方案

Agnes Harness（AGH）agent + `repro-diagnosis` skill + `repro-tools` MCP 7 个确定性工具，6 步闭环：
`inspect_repo → build_env → run_repo×2 → compare_numbers → diagnose → get_source/verify_fix`。
模型只负责推理与规划，**所有判定数字来自工具链确定性输出**；评测（judge/B1/边界）全程无模型。

## 核心结果（19 变体基准集：15 缺陷 + 4 对照）

| 方案 | 判定准确 | 根因准确 | 对照误报 | 依赖缺陷检出 |
|---|---|---|---|---|
| B1 朴素脚本 | 4/19 | 0/19 | — | 0/4 |
| B2 大模型看报错 | 14/19 | 14/19 | 0 | 1/4 |
| **B3 本方案** | **19/19** | **19/19** | **0** | **4/4** |

**零泄露复现**：ground truth（defect.json/mapping/expected_values）整体移出诊断目录后重跑，`harden-clean-run.sh verify` 判定 **19/19 结论一致**。

## 目录结构

| 路径 | 内容 |
|---|---|
| `项目/repro-agent-bench/` | 基准集：`eval/`（19 变体 + 答案文件）、`base-repos/`、`variants/`、`tools/`（judge/batch/boundary/batch_b3）、`mcp_server.py`（7 工具，纯 stdlib）、`.agh/skills/repro-diagnosis/SKILL.md` |
| `项目/serve-agh.sh` | AGH 启动脚本（导出 `AGNES_MCP_STDIO_ALLOWLIST`） |
| `项目/repro-agent-bench/harden-clean-run.sh` | 零泄露加固复现（setup/run/verify/restore） |
| `15-技术报告.md` | 技术报告（含 6.4 工具链故障案例、6.5 边界行为修正） |
| `evidence/02..08` | 环境版本 / AGH 会话与诊断包 / 模型使用记录 / 专业验证结果（b1,b2,b3,b3_clean,judge,boundary）/ 模型使用声明 / demo 脚本 / 公开内容草稿 |

## 快速复现（WSL2 + AGH）

```bash
bash serve-agh.sh &                 # 起 AGH（daemon + MCP repro-tools）
cd repro-agent-bench
python3 tools/test_boundary.py      # 边界 + 双向断言
python3 tools/judge.py              # 三方案指标（需 results/b1 b2 b3）
bash harden-clean-run.sh setup && bash harden-clean-run.sh run && bash harden-clean-run.sh verify && bash harden-clean-run.sh restore
```

模型：竞赛 Key 仅开放 `agnes-3.0-flash`（`https://api.agnes-ai.cn/v1`）；评测数字不经任何模型。
