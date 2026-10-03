# 可复现性诊断报告 — eval_19（units-pipeline）

## 结论
**根因标签：单位换算错误**（`to_meters` 未应用 `TO_METER[unit]` 系数，直接把输入值当米使用；输入声明单位为 km，偏差倍数恰为 1000，呈常数倍数，两次运行完全一致 → 静默但稳定的单位换算缺陷，且触发内置 `assert` 以 `AssertionError` 结束）。

原仓库不可复现；按诊断修复（一行改动）后在 /tmp 沙箱复现成功，所有关键值回到论文基线。

## 支撑证据（均来自工具返回）
- **inspect_repo**：入口 `main.py`；依赖 `numpy>=1.24`。
- **build_env**：全部可解析（numpy 2.3.5）。
- **run_repo ×2**：两次退出码均为 1，输出完全一致（`consistent=true`，非随机性）
  - stdout：`distance_m = 1.2`、`frequency_hz = 2.400e+09`、`path_loss_db = 41.64`、`received_power_dbm = -11.64`
  - stderr：`AssertionError: distance out of plausible range (unit error?)`（main.py:58）
- **compare_numbers**（期望值：distance_m=1200.0, frequency_hz=2.4e9, path_loss_db=101.64, received_power_dbm=-71.64）
  - distance_m: 1.2 vs 1200.0 → 偏差 1000 倍，rel_error≈0.999（超出容差）
  - frequency_hz: 2.4e9 vs 2.4e9 → 通过
  - path_loss_db: 41.64 vs 101.64 → 恒差 60 dB（对应距离 1000 倍：20·log10(1000)=60）
  - received_power_dbm: -11.64 vs -71.64 → 同样恒差 60 dB
- **get_source**：`main.py` 第 26–28 行 `to_meters` 直接 `return float(value)`，忽略了 `TO_METER[unit]`（对照第 31–33 行 `to_hz` 正确地使用了 `value * TO_HZ[unit]`）。声明单位若为 km，则 1.2 km 应为 1200 m，当前被当作 1.2 m。
- **verify_fix**：把 `to_meters` 改为 `return float(value) * TO_METER[unit]` 后，在 `/tmp/repro-verify-_vudfiqg` 沙箱两次运行均 exit 0、输出与论文期望逐项一致，`fix_verified=true`；**原仓库未做任何修改**（保持只读）。

## 关于 `diagnose` 规则表的一点说明
`diagnose` 工具按规则表返回了「可复现（无缺陷）confidence=0.9」，但该裁决基于「运行成功 + 数值在容差内」的匹配条件；本例实际 `exit_code=1` 且 3/4 项数值偏离超出 1e-3 容差，规则表匹配明显不适用。按 skill 硬性规则 1（不得把矛盾证据当结论）与优先级「单位换算错误：偏差呈常数倍数（100/1000 等）」，我手工裁定为**单位换算错误**，并以一次最小修复在 /tmp 反向验证（fix_verified=true）来支撑该标签。

## 置信度与不确定性
- 置信度 **0.95**：证据链完整且自洽 —— 恒定 1000 倍偏差 + 恒定 60 dB 路径损耗差 + 源码中 `to_meters` 明显漏乘单位系数 + 对照的 `to_hz` 正确使用系数 + /tmp 单行修复后四项数值全部精确回归基线。
- 不确定性声明：本报告只证明「该单行修复可使输出回归论文基线」，不证明该修复是唯一合理修复；也不证明 `data.json` 中 distance 的 `unit` 字段具体值（未读取，但修复结果与 1.2 km→1200 m 的换算相容）。

## 本次结论不适用的范围
- 只针对 `eval_19` 该 `main.py` 的这四处输出值；不覆盖其他可能的下游使用方。
- 不覆盖 numpy 版本变化对该公式数值稳定性的影响（本次 numpy 2.3.5 下计算稳定）。
- 不覆盖 `data.json` 其它字段或后续扩展场景。

---
判定: root_cause=单位换算错误 reproducible=false confidence=0.95