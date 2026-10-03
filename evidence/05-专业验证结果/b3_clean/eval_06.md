# 可复现性诊断报告 — eval_06（linreg-pipeline / 高维线性回归）

## 结论
**根因标签：数据泄漏（目标泄漏特征）**。原仓库在 `make_data` 中把由目标 y 派生的泄漏列（`X[:, N_FEATURES-1] = y + 噪声`）注入特征矩阵，并用**全量数据**（而非训练集）做特征选择，导致泄漏特征 19 被选中、test_r2 被虚假抬升到 0.9995，与论文基线 0.8697 不符，触发「suspiciously high R2」断言失败。移除泄漏列并改回「只在训练集选特征」后，selected 与 test_r2 精确回归期望。**可复现性 = false。**

## 支撑证据（均来自工具返回）
- **inspect_repo**：入口 `main.py`；依赖 `numpy>=1.24`；`target_outputs` 已直接暴露泄漏注入行 `X[:, N_FEATURES - 1] = y + rng.normal(...)`。
- **build_env**：`all_resolvable=true`（numpy 2.3.5）——排除「依赖版本问题」「环境不匹配」。
- **run_repo ×2**：两次退出码均 1、输出一致（`consistent=true`，非随机性）
  - stdout：`selected = 19,0,1,3,2,9`、`test_r2 = 0.9995`
  - stderr：`AssertionError: suspiciously high R2 (possible data leakage)`（main.py:90）
- **compare_numbers**（期望 selected=0,1,3,2,17,8；test_r2=0.8697，rel_tol=1e-3）
  - selected：`19,0,1,3,2,9` vs `0,1,3,2,17,8` → 字符串不等（实际多选出泄漏特征 19，且 9/17/8 被替换）
  - test_r2：0.9995 vs 0.8697 → `rel_error≈0.149`，超容差（指标异常接近 1）
- **diagnose**：规则表再次机械返回「可复现（无缺陷）」，但其预设「运行成功+数值在容差内」与本案 `exit_code=1`、R2 逼近 1 矛盾；按「指标异常高（R² 反常接近 1）、特征由目标派生」签名，手工裁定为**数据泄漏（目标泄漏特征）**。
- **get_source** 定位两处缺陷：
  - `main.py:35` `X[:, N_FEATURES - 1] = y + rng.normal(...)` —— 目标泄漏特征（由 y 派生）
  - `main.py:81` `cols = select_features(X, y)` —— 用全量数据选特征（注释自标「错误」），应只用训练集
- **verify_fix**：在 `/tmp/repro-verify-duxw5hfb` 沙箱做最小修复（删除泄漏注入列 + 改回 `select_features(X_train, y_train)`）后，两次运行均 exit 0，输出
  `selected = 0,1,3,2,17,8`、`test_r2 = 0.8697`、`OK`，`fix_verified=true`，与论文期望逐项一致；**原仓库未被修改**（保持只读）。

## 第 6 步说明
已按规则执行：`get_source` 定位缺陷行（第 35 行泄漏注入 + 第 81 行全量选特征）→ 最小修复（移除目标派生泄漏列，特征选择改回只用训练集）→ `verify_fix` 在 /tmp 沙箱验证修复后 selected 与 test_r2 全部精确回归期望、两次一致。原仓库保持只读。

## 置信度与不确定性
- 置信度 **0.9**：证据链完整 —— 依赖可解析、两次一致（排除随机性）、R2 异常接近 1、源码确认「由 y 派生的泄漏特征 + 全量选特征」、去掉泄漏后立即精确回归基线，签名完全匹配「数据泄漏（目标泄漏特征）」。
- 不确定性：论文基线 0.8697 对应「无泄漏 + 训练集选特征」的干净流程；本例修复同时改了两处（删泄漏列 + 训练集选特征），未单独验证仅删泄漏列、保留全量选特征时 test_r2 是否也回归 0.8697。

## 本次结论不适用的范围
- 针对当前 `main.py` 的泄漏注入与全量选特征写法；改动这两处后判定改变。
- 数值结论仅覆盖本 SEED=7、N_SAMPLES=400、N_FEATURES=20 配置；未覆盖其它随机种子或数据规模。

---
判定: root_cause=数据泄漏（目标泄漏特征） reproducible=false confidence=0.9

[stderr]
- tool mcp_repro_tools_58f53a47_inspect_repo
- tool mcp_repro_tools_58f53a47_inspect_repo · ok · 4ms
- tool mcp_repro_tools_58f53a47_build_env
- tool mcp_repro_tools_58f53a47_build_env · ok · 4ms
- tool mcp_repro_tools_58f53a47_run_repo
- tool mcp_repro_tools_58f53a47_run_repo · ok · 275ms
- tool mcp_repro_tools_58f53a47_get_source
- tool mcp_repro_tools_58f53a47_get_source · ok · 2ms
- tool mcp_repro_tools_58f53a47_compare_numbers
- tool mcp_repro_tools_58f53a47_compare_numbers
- tool mcp_repro_tools_58f53a47_diagnose
- tool mcp_repro_tools_58f53a47_compare_numbers · ok · 2ms
- tool mcp_repro_tools_58f53a47_compare_numbers · ok · 3ms
- tool mcp_repro_tools_58f53a47_diagnose · ok · 3ms
- tool mcp_repro_tools_58f53a47_verify_fix
- tool mcp_repro_tools_58f53a47_verify_fix · ok · 142ms
