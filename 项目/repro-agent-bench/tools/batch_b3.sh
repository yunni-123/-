#!/bin/bash
# B3 批量：AGH agent + repro-diagnosis skill + repro-tools MCP，六步闭环
# 逐个跑（并发会 SESSION_BUSY），每个结果落盘
set -u
cd /root/agnes-harness
AGH="node packages/cli/dist/local/agnes.mjs"
BENCH=/root/repro-agent-bench
OUT="$BENCH/results/b3"
mkdir -p "$OUT"

mapfile -t EVALS < <(python3 -c "import json; [print(m['eval']) for m in json.load(open('$BENCH/eval/mapping.json'))]")
echo "variants: ${#EVALS[@]}"
for e in "${EVALS[@]}"; do
  f="$OUT/$e.md"
  [ -s "$f" ] && echo "skip $e (exists)" && continue
  echo "=== running $e ==="
  "$AGH" -p "使用 repro-diagnosis skill 诊断 /root/repro-agent-bench/eval/$e 的可复现性。期望关键数值见该仓库内 expected 说明或 inspect_repo 返回；若工具未提供期望值，则用 compare_numbers 对比其多次运行之间的一致性。按 6 步闭环执行：inspect_repo → build_env → run_repo(两次) → compare_numbers → diagnose → 第6步（若有缺陷，用 get_source 读源码并对两处/相关缺陷做最小修复，用 verify_fix 在 /tmp 沙箱验证；若无缺陷则说明无需修复）。不得修改原仓库。最后输出诊断报告，最后一行必须为固定格式：
判定: root_cause=<标签> reproducible=<true|false> confidence=<0-1小数>
标签必须逐字取自：可复现（无缺陷）、随机性未固定、数据泄漏（目标泄漏特征）、单位换算错误、数值不稳定、静默截断、环境不匹配、依赖版本问题、未知" 2>&1 | tee "$f" | tail -12
  echo "=== done $e ==="
done
echo "ALL_DONE"
