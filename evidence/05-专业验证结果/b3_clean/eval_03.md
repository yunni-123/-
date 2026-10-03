# 可复现性诊断报告 — eval_03（illcond-solve / Hilbert，法方程显式求逆）

## 结论
**根因标签：数值不稳定**。原仓库 `solve()` 使用法方程 `np.linalg.solve(A.T @ A, A.T @ b)`，对已病态的 Hilbert 矩阵再平方条件数（cond(A)=1.526e+10 → cond(AᵀA)≈10²⁰），残差与解误差放大到 10⁶ 量级，稳定不可复现；改用直接对 `A` 的稳定求解后，数值精确回归论文基线。**可复现性 = false。**

## 支撑证据（均来自工具返回）
- **inspect_repo**：入口 `main.py`；依赖 `numpy>=1.24`。
- **build_env**：`all_resolvable=true`（numpy 2.3.5）——排除「依赖版本问题」「环境不匹配」。
- **run_repo ×2**：两次退出码均 1，输出一致（`consistent=true`，非随机性）
  - stdout：`cond(A) = 1.526e+10`、`relative_residual = 8.228e-10`、`solution_error = 1.194e+00`
  - stderr：`AssertionError: relative residual too large: numerical instability`（main.py:45）
- **compare_numbers**（期望 1.526e+10 / 1.071e-16 / 2.256e-07）
  - cond(A)：1.526e+10 vs 1.526e+10 → 通过（条件数本身算对了，只是被法方程放大的对象）
  - relative_residual：8.228e-10 vs 1.071e-16 → 偏差 ~7.7e6 倍，超容差
  - solution_error：1.194 vs 2.256e-07 → 偏差 ~5.3e6 倍，超容差
- **diagnose**：规则表再次机械返回「可复现（无缺陷）」，但该裁决预设运行成功+数值在容差内，与本案 `exit_code=1`、两项核心数值偏离 10⁶ 倍、assert 明确报「numerical instability」矛盾；按证据手工裁定为**数值不稳定**。
- **get_source** 定位：`main.py` 第 24–26 行 `solve()` 返回 `np.linalg.solve(A.T @ A, A.T @ b)`——法方程/正规方程形式，对病态矩阵会把条件数平方，正是残差与误差放大的根因（对照同族 eval_01/eval_02 该函数为 `np.linalg.solve(A, b)`）。
- **verify_fix**：在 `/tmp/repro-verify-lvs574u6` 沙箱将 `solve()` 改回直接 `np.linalg.solve(A, b)` 后，两次运行均 exit 0，输出
  `cond(A)=1.526e+10, relative_residual=1.071e-16, solution_error=2.256e-07, OK`，`fix_verified=true`，与论文期望逐项一致；**原仓库未被修改**（保持只读）。

## 第 6 步说明
已按规则执行：`get_source` 定位缺陷行（第 26 行法方程求逆）→ 最小修复（仅将 `solve` 内的 `np.linalg.solve(A.T @ A, A.T @ b)` 改为稳定的 `np.linalg.solve(A, b)`，不动 Hilbert 构造与断言）→ `verify_fix` 在 /tmp 沙箱验证修复后 3 项数值全部精确回归期望、两次一致。原仓库保持只读。

## 置信度与不确定性
- 置信度 **0.9**：证据链完整 —— 依赖可解析、两次运行一致（排除随机性）、残差/解误差恒定放大 ~10⁶ 倍、源码确为法方程形式、改回直接求解即精确回归基线，签名完全匹配「数值不稳定（条件数高、显式求逆/法方程）」。
- 不确定性：未逐一验证其它等价的稳定求解器（如 `np.linalg.lstsq`、加正则化）能否同样回归；本结论仅针对该 `N=8` 配置。

## 本次结论不适用的范围
- 针对当前 `main.py` 的 `solve()` 法方程写法；若换成稳定求解器则判定的可复现性会改变。
- 数值结论仅覆盖 N=8、本 numpy 2.3.5 环境；未覆盖其它矩阵规模或 numpy 大版本。

---
判定: root_cause=数值不稳定 reproducible=false confidence=0.9

[stderr]
- tool mcp_repro_tools_58f53a47_inspect_repo
- tool mcp_repro_tools_58f53a47_inspect_repo · ok · 4ms
- tool mcp_repro_tools_58f53a47_build_env
- tool mcp_repro_tools_58f53a47_build_env · ok · 6ms
- tool mcp_repro_tools_58f53a47_run_repo
- tool mcp_repro_tools_58f53a47_run_repo · ok · 256ms
- tool mcp_repro_tools_58f53a47_compare_numbers
- tool mcp_repro_tools_58f53a47_compare_numbers · ok · 3ms
- tool mcp_repro_tools_58f53a47_compare_numbers
- tool mcp_repro_tools_58f53a47_compare_numbers · ok · 3ms
- tool mcp_repro_tools_58f53a47_compare_numbers
- tool mcp_repro_tools_58f53a47_compare_numbers · ok · 3ms
- tool mcp_repro_tools_58f53a47_diagnose
- tool mcp_repro_tools_58f53a47_diagnose · ok · 3ms
- tool mcp_repro_tools_58f53a47_get_source
- tool mcp_repro_tools_58f53a47_get_source · ok · 4ms
- tool mcp_repro_tools_58f53a47_verify_fix
- tool mcp_repro_tools_58f53a47_verify_fix · ok · 128ms
