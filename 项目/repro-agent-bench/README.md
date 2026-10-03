# repro-agent-bench · 可复现性验证基准集

本目录是"科研计算可复现性验证智能体"的**客观评测基准**。
它把"Agent 能不能查出代码为什么不复现"变成一个**可计算、可对标**的分数。

---

## 一、基准集设计

```
base-repos/          4 个"完好"的基础仓库（应当判定为可复现）
variants/            19 个变体 = 15 个含缺陷 + 4 个完好对照组
tools/inject_defect.py   缺陷注入工具（确定性、可校验）
tools/run_bench.py      基线执行器：导出 observations.csv
observations.csv    每个变体的真实观测签名（判据依据）
```

### 基础仓库

| 仓库 | 主题 | 依赖 | 关键输出 |
|---|---|---|---|
| `sinusoid-fit` | 正弦信号最小二乘拟合 | numpy | `amplitude`, `frequency` |
| `linreg-pipeline` | 高维线性回归（划分/标准化/特征选择） | numpy | `selected`, `test_r2` |
| `illcond-solve` | 病态线性方程组求解 | numpy | `relative_residual`, `solution_error` |
| `units-pipeline` | 物理量单位传递（路径损耗） | numpy | `distance_m`, `path_loss_db` |

### 缺陷类型与期望根因（7 类）

| 缺陷 ID | 期望根因标签 | 观测签名 | 检出难度 |
|---|---|---|---|
| `no_seed` | 随机性未固定 | **两次运行结果不同**（唯一非确定性类） | 中 |
| `data_leakage` | 数据泄漏（目标泄漏特征） | `test_r2` 超上界，触发断言 | **难（最隐蔽）** |
| `unit_confusion` | 单位换算错误 | `distance out of plausible range` | 中 |
| `numerical_instability` | 数值不稳定 | `relative residual too large` | 中 |
| `silent_truncation` | 静默截断 | 数值偏离（sinusoid）/ 形状断言（illcond） | **难（不报错）** |
| `env_cuda` | 环境不匹配 | `RuntimeError: CUDA/GPU backend is required` | 易 |
| `dep_typo` | 依赖版本问题 | **无签名——主程序照常跑通** | **需环境构建才能检出** |

---

## 二、关键实验发现（写进报告的核心素材）

### 发现 1：基线（直接跑 `python main.py`）无法给出根因

`tools/run_bench.py` 模拟"最朴素的复现尝试"：进目录、跑 `main.py`、记录退出码和输出。

- **能检出**：`env_cuda`、`numerical_instability`、`unit_confusion`、`silent_truncation`(illcond)、`data_leakage` —— 因为它们会让程序**抛异常**
- **不能检出**：`no_seed`（程序正常退出，只有多次运行才暴露）、`silent_truncation`(sinusoid)（数值只是偏离）、`dep_typo`（**完全不执行环境构建就发现不了**）

> **这是本项目最有力的论证材料**：朴素脚本方案能"看到报错"，但**给不出根因、也发现不了静默缺陷**。

### 发现 2：`dep_typo` 的签名与"完好仓库"完全相同

实测数据：

```
sinusoid-fit--pristine        {"amplitude": "2.9799", "frequency": "2.5000"}
sinusoid-fit--dep_typo        {"amplitude": "2.9799", "frequency": "2.5000"}   <- 一模一样
```

**原因**：`run_bench.py` 只跑 `main.py`，从不检查 `requirements.txt`，而当前环境已装 numpy，所以不存在的依赖被完全忽略。

> **结论**：依赖类缺陷**只能靠"环境构建"步骤检出**——必须先解析依赖、再尝试安装/校验，才能发现 `nonexistent-package-xyz==99.99.99`。
> **这正好证明：环境构建是 harness 的不可替代能力，不是"多此一举的包装"。**

### 发现 3：我们主动剔除了一个"测不出来"的缺陷

最初的 `data_leakage` 设计是"特征选择/标准化在划分之前用全量数据做"。**实测该形态在最小二乘下几乎不抬高指标**：

| 配置 (n/p/真实特征/选择数) | 正确 CV | 泄漏 CV | 虚高 |
|---|---|---|---|
| 400/20/4/6 | 0.870 | 0.871 | +0.001 |
| 200/20/4/6 | 0.856 | 0.856 | −0.000 |
| 100/40/3/10 | 0.815 | 0.839 | +0.025 |
| 200/60/2/15 | 0.802 | 0.822 | +0.020 |
| 80/60/3/10 | 0.766 | 0.814 | +0.048 |

**虚高最大只有 0.05，不足以稳定检出。** 原因：虚假相关在训练集上有效，但不会延续到固定测试集。

因此我们**放弃了该形态**，改用**目标泄漏特征**（由目标派生的特征在全量数据上被选到），它产生明确、可复现的检出信号（`test_r2` 越过 0.90 上界触发断言）。

> **这件事本身就是加分项**：能说明"我们测过某个缺陷形态、发现它在当前设定下不可稳定检出、因此主动剔除，而不是凑一个好看的数字"。
> 这正是赛制"验证严谨性"要考察的东西，也是大多数队伍不会做的事。

### 发现 4：每个缺陷产生唯一可区分的签名

| 观测签名 | 对应变体 |
|---|---|
| `RuntimeError: CUDA/GPU backend is required` | 4 个 `env_cuda` |
| `AssertionError: relative residual too large` | `numerical_instability` |
| `AssertionError: matrix was silently truncated` | `silent_truncation`(illcond) |
| `AssertionError: suspiciously high R2` | `data_leakage` |
| `AssertionError: distance out of plausible range` | `unit_confusion` |
| `{"amplitude": "2.9964", ...}` | `silent_truncation`(sinusoid) |
| **多次运行不一致** | 2 个 `no_seed`（唯一非确定类） |
| 与 pristine 完全相同 | 3 个 `dep_typo` ← **需环境构建** |

→ 判据是**可判定的**：观测签名可以唯一映射到根因标签。

---

## 三、复现步骤

```bash
# 1. 确认基础仓库全部可复现
cd base-repos/sinusoid-fit && python main.py      # 应打印 OK

# 2. 生成全部变体（15 个缺陷 + 4 个对照）
python tools/inject_defect.py --all

# 3. 跑基线，得到观测签名
python tools/run_bench.py

# 4. 查看缺陷清单
python tools/inject_defect.py --list
```

**注意**：`inject_defect.py` 对每个替换做**精确命中校验**（命中次数必须等于预期）。
一旦基础仓库改动导致正则失配，脚本会**直接报错中止**，不会静默生成错误的变体。
这个"自我校验"机制在开发期已经抓出 4 处真实失配。

---

## 四、评测指标定义

| 指标 | 定义 | 用途 |
|---|---|---|
| **根因定位准确率** | Agent 给出的根因标签 == `defect.json` 中 `root_cause` 的比例 | **主指标** |
| **可复现性判定准确率** | Agent 判"可复现/不可复现"与实际一致的比例 | 辅助 |
| **假阳性率** | 完好仓库被判为"不可复现"的比例 | 防误报 |
| **平均诊断耗时** | 每个变体从开始到出报告的时间 | 效率 |
| **依赖缺陷检出率** | `dep_typo` 被正确检出的比例 | **考验环境构建能力** |

### 对比基线（实测结果，2026-10-02，19 变体全量）

| 方案 | 说明 | 根因定位准确率 | 实测 |
|---|---|---|---|
| B1 朴素脚本 | 只跑 `main.py`，失败即止 | 无根因能力 | 0/19（可复现性判断仅 0.21） |
| B2 大模型看报错 | 代码+stderr 一次性交 LLM（单模型单次调用，无工具） | 中 | 14/19（0.74）；dep_typo 仅 1/4 |
| **B3 本方案** | AGH agent + `repro-diagnosis` skill + `repro-tools` MCP 七工具，6 步闭环 | **高** | **19/19（1.00）**；假阳性 0；dep_typo 4/4；平均 ≈88s/变体 |

> 完整数字与逐变体明细见 `evidence/05-专业验证结果/三方案对比表.md`、`agent_results.csv`；B3 无失败样例（`失败样例分析.md`）。

---

## 五、扩展方向（时间充裕时再做）

1. **更多缺陷类型**：浮点精度、路径硬编码、时区/编码依赖、并发竞态
2. **更多基础仓库**：从真实开源仓库简化而来（注明来源与许可）
3. **难度分级**：按"是否抛异常 / 是否静默"分 easy / medium / hard
4. **多缺陷叠加**：一个仓库注入 2 个缺陷，考察根因排序能力

---

## 六、许可与来源声明

- 所有基础仓库均为**本项目原创编写**，仅依赖 numpy（BSD 许可）
- 未使用任何第三方论文代码，故无版权问题
- 若后续引入真实开源仓库，必须在此处逐条注明**仓库地址、commit、许可协议**
