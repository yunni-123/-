## 诊断报告：/root/repro-agent-bench/eval/eval_06（linreg-pipeline）

### ① 规划（inspect_repo）
- 仓库：`main.py` + `requirements.txt`（numpy>=1.24）+ `defect.json`，入口 `main.py`。
- 目标关键值：`selected`（选出的 6 个特征索引）、`test_r2`。
- 论文宣称期望：`selected=0,1,3,2,17,8`、`test_r2=0.8697`。

### ② 环境构建（build_env）
- `numpy>=1.24` → 已装 `2.3.5`，**全部可解析**，无依赖版本问题。✓

### ③ 执行（run_repo，跑两次）
- 两次均 `exit_code=1`，`consistent=true`（**非随机性**，确定性同点失败）。
- 两次输出均：`selected = 19,0,1,3,2,9`、`test_r2 = 0.9995`。
- 失败栈：`main.py:90` `assert score < 0.90, "suspiciously high R2 (possible data leakage)"`。

### ④ 源码定位（get_source）
`make_data`（`main.py:34-35`）注入了一条**目标泄漏特征**：
```python
# 注入目标泄漏特征：由目标 y 派生（本不该作为特征出现）
X[:, N_FEATURES - 1] = y + rng.normal(0.0, 0.05, size=N_SAMPLES)   # ← 缺陷行（line 35）
```
第 19 列由目标 `y` 直接派生（仅加 0.05 噪声），相关性近乎 1.0，故特征选择将其排在最前（`selected` 首位=19），test R² 被抬高到 0.9995，触发 0.90 上界断言。

### ⑤ 数值比对（compare_numbers，修复前实际 vs 期望）
| 项 | 实际 | 期望 | rel_error | within_tol |
|---|---|---|---|---|
| selected[0] | 19 | 0 | — | ✗ |
| selected[1] | 0 | 1 | — | ✗ |
| selected[2] | 1 | 3 | — | ✗ |
| selected[3] | 3 | 2 | — | ✗ |
| selected[4] | 2 | 17 | 0.882 | ✗ |
| selected[5] | 9 | 8 | 0.125 | ✗ |
| test_r2 | 0.9995 | 0.8697 | 0.149 | ✗ |

7/7 项全部偏离期望 → 与论文宣称数值不一致。

### ⑥ 修复验证（verify_fix，/tmp 沙箱，原仓库未改动）
**仅移除泄漏行（第 35 行）不足以完全回到期望**：
- 只删泄漏行 → `selected = 0,1,3,2,9,8`、`test_r2 = 0.8707`（第 5 个索引 9≠17，R² 略有偏差）。

**根因确认（关键）**：除泄漏行外，`main.py:81` 还有一个缺陷——特征选择**误用全量数据**：
```python
cols = select_features(X, y)   # 错误：用了全量数据选特征
```
按 docstring「正确顺序」，应只用**训练集**选特征。移除泄漏行并改为 `select_features(X_train, y_train)` 后：
- `selected = 0,1,3,2,17,8`、`test_r2 = 0.8697`（**逐项精确命中期望**），两次 `exit_code=0`、`consistent=true`，`fix_verified=true`。

即：泄漏特征把 feature 19 顶到选择集内并抬高了 test R²；而「全量选特征」的排序错位使第 5 个索引为 9 而非 17。二者须一并修正数值才能完全复现。

### 根因裁决
- 主导缺陷为**数据泄漏（目标泄漏特征）**：`main.py:35` 用目标 `y` 派生第 19 列特征，导致 test R² 反常接近 1（0.9995）并被 `selected` 首位捕获，触发 `assert score < 0.90`。与标签表「指标异常高（R² 反常接近 1）、特征由目标派生」签名逐字吻合。
- 次要同源缺陷：`main.py:81` 用全量数据选特征（应为训练集），使 `selected` 第 5 项偏离；修复验证表明两项需同时纠正才能精确复现。

### 不确定性 / 不适用范围
- `diagnose` 工具自动规则表返回 `可复现（无缺陷） confidence=0.9`，与①–⑥直接证据（确定性失败 + R² 反常接近 1 + 泄漏特征）**相矛盾**，故不采信其裁决，标签由证据推理得出。
- 本结论仅适用于该仓库「高维线性回归 + 相关性特征选择 + 训练/测试划分」场景；改动 N_FEATURES、SEED、TOP_K 或选特征准则不在本次验证范围内。

判定: root_cause=数据泄漏（目标泄漏特征） reproducible=false confidence=0.95

[stderr]
- tool mcp_repro_tools_58f53a47_inspect_repo
- tool mcp_repro_tools_58f53a47_build_env
- tool mcp_repro_tools_58f53a47_inspect_repo · ok · 6ms
- tool mcp_repro_tools_58f53a47_build_env · ok · 7ms
- tool mcp_repro_tools_58f53a47_run_repo
- tool mcp_repro_tools_58f53a47_run_repo · ok · 456ms
- tool mcp_repro_tools_58f53a47_get_source
- tool mcp_repro_tools_58f53a47_get_source · ok · 3ms
- tool mcp_repro_tools_58f53a47_compare_numbers
- tool mcp_repro_tools_58f53a47_compare_numbers
- tool mcp_repro_tools_58f53a47_compare_numbers
- tool mcp_repro_tools_58f53a47_compare_numbers
- tool mcp_repro_tools_58f53a47_compare_numbers · ok · 2ms
- tool mcp_repro_tools_58f53a47_compare_numbers · ok · 3ms
- tool mcp_repro_tools_58f53a47_compare_numbers · ok · 2ms
- tool mcp_repro_tools_58f53a47_compare_numbers · ok · 3ms
- tool mcp_repro_tools_58f53a47_compare_numbers
- tool mcp_repro_tools_58f53a47_compare_numbers
- tool mcp_repro_tools_58f53a47_compare_numbers
- tool mcp_repro_tools_58f53a47_compare_numbers · ok · 4ms
- tool mcp_repro_tools_58f53a47_compare_numbers · ok · 5ms
- tool mcp_repro_tools_58f53a47_compare_numbers · ok · 3ms
- tool mcp_repro_tools_58f53a47_verify_fix
- tool mcp_repro_tools_58f53a47_verify_fix · ok · 128ms
- tool mcp_repro_tools_58f53a47_diagnose
- tool mcp_repro_tools_58f53a47_diagnose · ok · 4ms
- tool write
- tool mcp_repro_tools_58f53a47_verify_fix
- tool mcp_repro_tools_58f53a47_verify_fix · ok · 157ms
