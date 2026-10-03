#!/usr/bin/env bash
# 硬核加固：把含标准答案的 defect.json 移出 agent 工作目录，跑一遍"零泄露"复现，
# 然后原样还原。依赖：python3；不修改任何 main.py / requirements.txt / 评分数据。
#
# 用法：
#   bash harden-clean-run.sh setup      # 移走 defect.json（备份到 eval/_leak_backup/）
#   bash harden-clean-run.sh run [eval_NN ...]   # 干净环境下跑 B3（结果落 results/b3_clean/）
#   bash harden-clean-run.sh restore    # 还原 defect.json（幂等）
#   bash harden-clean-run.sh verify     # 对比 b3 与 b3_clean 的结论是否一致
set -u

ROOT=/root/repro-agent-bench
EVAL=$ROOT/eval
BK=$ROOT/_leak_backup      # 放在 eval 树之外，避免 inspect_repo 递归看到

# 环境（保证 node/python3 可用）
cd "$ROOT" || { echo "!! $ROOT 不存在"; exit 1; }

setup() {
  mkdir -p "$BK"
  # 先把 expected_values.json 固化到 eval_canon/（run 阶段需要它，且它不含根因答案）
  mkdir -p "$ROOT/eval_canon"
  if [ -f "$EVAL/expected_values.json" ]; then
    cp "$EVAL/expected_values.json" "$ROOT/eval_canon/expected_values.json"
    echo "已固化 eval/expected_values.json -> eval_canon/expected_values.json"
  fi
  n=0
  for f in "$EVAL"/eval_*/defect.json; do
    [ -e "$f" ] || continue
    d=$(basename "$(dirname "$f")")
    mv "$f" "$BK/$d.defect.json"
    n=$((n+1))
  done
  # mapping.json 也含 variant 名/defect id，一并移走
  if [ -f "$EVAL/mapping.json" ]; then
    mv "$EVAL/mapping.json" "$BK/mapping.json"
    echo "已移走 eval/mapping.json"
  fi
  # eval/expected_values.json 留在原地会泄露"期望值"？不含根因，但为彻底起见也移走
  if [ -f "$EVAL/expected_values.json" ]; then
    mv "$EVAL/expected_values.json" "$BK/expected_values.json"
    echo "已移走 eval/expected_values.json（副本已在 eval_canon/）"
  fi
  echo "已移走 $n 个 defect.json -> $BK"
  echo "--- 现在 eval 目录里剩下的文件（应只有 main.py 和 requirements.txt）---"
  ls "$EVAL"/eval_01/
  echo "--- 全树泄露扫描（应无输出）---"
  grep -rl "root_cause" "$EVAL" 2>/dev/null || echo "  (无泄露)"
}

restore() {
  [ -d "$BK" ] || { echo "无需还原（无备份目录）"; return 0; }
  n=0
  for f in "$BK"/eval_*.defect.json; do
    [ -e "$f" ] || continue
    d=$(basename "$f" .defect.json)
    mkdir -p "$EVAL/$d"
    mv "$f" "$EVAL/$d/defect.json"
    n=$((n+1))
  done
  [ -f "$BK/mapping.json" ] && mv "$BK/mapping.json" "$EVAL/mapping.json" && echo "已还原 mapping.json"
  [ -f "$BK/expected_values.json" ] && mv "$BK/expected_values.json" "$EVAL/expected_values.json" && echo "已还原 expected_values.json"
  echo "已还原 $n 个 defect.json"
}

run() {
  if ls "$EVAL"/eval_*/defect.json >/dev/null 2>&1; then
    echo "!! 警告：eval 目录里仍有 defect.json，请先执行 setup"
  fi
  # 复用官方 batch_b3.py，但输出目录改为 results/b3_clean
  python3 - "$@" <<'PY'
import json, os, subprocess, time, sys

ROOT = "/root/repro-agent-bench"
AGH = ["node", "/root/agnes-harness/packages/cli/dist/local/agnes.mjs"]
LABELS = ("可复现（无缺陷）、随机性未固定、数据泄漏（目标泄漏特征）、单位换算错误、"
          "数值不稳定、静默截断、环境不匹配、依赖版本问题、未知")

# eval 顺序固定，不依赖 mapping.json（此刻它已被移走）
def evals():
    ds = sorted(d for d in os.listdir(os.path.join(ROOT, "eval"))
                if d.startswith("eval_") and os.path.isdir(os.path.join(ROOT, "eval", d)))
    return ds

expected = json.load(open(os.path.join(ROOT, "eval_canon", "expected_values.json")))

out_dir = os.path.join(ROOT, "results", "b3_clean")
os.makedirs(out_dir, exist_ok=True)
args = sys.argv[1:]
todo = args if args else evals()

def repo_hint(ev):
    """从 results/agent_results.csv 反查该 eval 对应的仓库（仅用于选期望值，不泄露根因）"""
    import csv
    p = os.path.join(ROOT, "results", "agent_results.csv")
    if not os.path.exists(p):
        return None
    for r in csv.DictReader(open(p, encoding="utf-8")):
        if r.get("eval") == ev:
            return r.get("variant", "").split("--")[0]
    return None

for ev in todo:
    f = os.path.join(out_dir, ev + ".md")
    if os.path.exists(f) and os.path.getsize(f) > 500:
        print("skip %s (exists)" % ev); continue
    repo = repo_hint(ev)
    exp = expected.get(repo, {})
    exp_s = ", ".join("%s=%s" % (k, v) for k, v in exp.items()) if exp else "（未提供）"
    prompt = (
        "使用 repro-diagnosis skill 诊断 %s/eval/%s 的可复现性。\n"
        "该仓库论文宣称的期望关键数值：%s（请逐项用 compare_numbers 比对）。\n"
        "按 6 步闭环执行：inspect_repo → build_env → run_repo(两次) → compare_numbers → diagnose → "
        "第6步（若有缺陷：get_source 读源码定位缺陷行，做最小修复，用 verify_fix 在 /tmp 沙箱验证修复后数值回到期望；"
        "若无缺陷：说明无需修复）。不得修改原仓库。\n"
        "最后输出诊断报告，最后一行必须为固定格式：\n"
        "判定: root_cause=<标签> reproducible=<true|false> confidence=<0-1小数>\n"
        "标签必须逐字取自：%s" % (ROOT, ev, exp_s, LABELS)
    )
    t0 = time.monotonic()
    try:
        r = subprocess.run(AGH + ["-p", prompt], cwd="/root/repro-agent-bench",
                           capture_output=True, text=True, timeout=600)
        out = r.stdout + (("\n[stderr]\n" + r.stderr) if r.stderr.strip() else "")
        rc = r.returncode
    except subprocess.TimeoutExpired:
        out, rc = "[TIMEOUT]", 124
    open(f, "w", encoding="utf-8").write(out)
    print("%s done in %.0fs rc=%s" % (ev, time.monotonic() - t0, rc), flush=True)
print("CLEAN RUN DONE")
PY
}

verify() {
  echo "=== 干净跑结论 vs 原跑结论 ==="
  printf "%-10s %-34s %-24s %-24s %s\n" eval variant orig clean 一致
  printf -- "%.0s-" {1..120}; echo
  python3 - <<'PY'
import csv, os, re
ROOT="/root/repro-agent-bench"
def last_label(p):
    if not os.path.exists(p): return "(缺失)"
    txt=open(p,encoding="utf-8",errors="replace").read()
    m=re.findall(r"root_cause\s*=\s*([^,\s]+)", txt)
    return m[-1] if m else "(未解析)"
rows=list(csv.DictReader(open(os.path.join(ROOT,"results","agent_results.csv"),encoding="utf-8")))
ok=0
for r in rows:
    ev=r["eval"]
    o=last_label(os.path.join(ROOT,"results","b3",ev+".md"))
    c=last_label(os.path.join(ROOT,"results","b3_clean",ev+".md"))
    same="是" if (o==c and o!="(缺失)") else ("待跑" if c=="(缺失)" else "否")
    if same=="是": ok+=1
    print("%-10s %-34s %-24s %-24s %s"%(ev,r["variant"],o,c,same))
print()
print("结论一致的 eval 数：%d/%d"%(ok,len(rows)))
PY
}

case "${1:-}" in
  setup)   setup ;;
  run)     shift; run "$@" ;;
  restore) restore ;;
  verify)  verify ;;
  *) echo "用法: $0 {setup|run [eval_NN...]|restore|verify}"; exit 2 ;;
esac
