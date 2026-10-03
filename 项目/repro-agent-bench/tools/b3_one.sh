#!/bin/bash
# 单 eval 完整流程：确保 MCP ready → 跑诊断 prompt → 从会话 export 捞报告
cd /root/repro-agent-bench
AGH="node /root/agnes-harness/packages/cli/dist/local/agnes.mjs"
K="agnes:local:local-dev:cli:workspace:decaff41923f8b8e"
EVAL="$1"   # e.g. eval_04
EXP="$2"    # expected values string

# 0) 取当前 MCP 状态；若 unavailable，用 ptyrun 重连
ST=$($AGH mcp status repro-tools 2>&1 | head -1)
echo "MCP before: $ST"
if ! echo "$ST" | grep -q "connection=ready"; then
  echo "需要重连，跑 pty reconnect..."
  cat > register-inner.sh <<INNER
#!/bin/bash
cd /root/agnes-harness
AGH="node packages/cli/dist/local/agnes.mjs"
R=\$(\$AGH mcp get repro-tools 2>/dev/null | grep -oE "revision=[0-9a-f]+" | head -1 | sed "s/revision=//")
\$AGH mcp reconnect repro-tools --expected-revision "\$R" 2>&1 | head -3
\$AGH mcp status repro-tools 2>&1 | head -1
INNER
  python3 ptyrun.py >/dev/null 2>&1
  ST=$($AGH mcp status repro-tools 2>&1 | head -1)
  echo "MCP after reconnect: $ST"
fi

# 记录当前会话 lastSeq（用于 export 时截出本次新增）
SEQ_BEFORE=$($AGH sessions show "$K" 2>/dev/null | awk 'NR==1{print $2}')

# 1) 跑诊断（忽略 stdout 正文，turn 会写入会话）
timeout 300 $AGH -p "使用 repro-diagnosis skill 诊断 /root/repro-agent-bench/eval/$EVAL。该仓库论文宣称的期望关键数值：$EXP（逐项用 compare_numbers 比对）。按 6 步闭环：inspect_repo → build_env → run_repo(两次) → compare_numbers → diagnose → 第6步（有缺陷则 get_source+verify_fix 最小修复验证；无缺陷则说明）。不得修改原仓库。最后输出诊断报告，最后一行固定格式：
判定: root_cause=<标签> reproducible=<true|false> confidence=<0-1小数>
标签逐字取自：可复现（无缺陷）、随机性未固定、数据泄漏（目标泄漏特征）、单位换算错误、数值不稳定、静默截断、环境不匹配、依赖版本问题、未知" >/dev/null 2>&1
echo "turn rc=$?"

# 2) export 会话，取最后一条 gpt 消息里含"判定"的报告
$AGH export "$K" --format sharegpt -o /tmp/b3exp.json 2>/dev/null
python3 - "$EVAL" "$SEQ_BEFORE" <<'PY'
import json,sys
eval_name=sys.argv[1]
d=json.load(open('/tmp/b3exp.json'))
msgs=d.get('conversations') or d
# 找最后一条含 eval_name 的 human，之后第一条含"判定"的 gpt
idx=[i for i,m in enumerate(msgs) if (m.get('from') or m.get('role'))=='human' and eval_name in str(m.get('value') or m.get('content'))]
start=idx[-1] if idx else 0
report=None
for m in msgs[start:]:
    if (m.get('from') or m.get('role'))=='gpt' and '判定' in str(m.get('value') or m.get('content')):
        report=m.get('value') or m.get('content')
if report:
    open(f'/root/repro-agent-bench/results/b3/{eval_name}.md','w').write(str(report))
    print(f"[{eval_name}] REPORT CAPTURED ({len(report)} chars)")
    print('---tail---')
    print('\n'.join(str(report).splitlines()[-8:]))
else:
    # 可能模型本轮报 unknown tool；打印该段最后 gpt
    tail=[m for m in msgs[start:] if (m.get('from') or m.get('role')) in ('gpt','tool')]
    print(f"[{eval_name}] NO REPORT. last msgs:")
    for m in tail[-4:]:
        print(' ', (m.get('from') or m.get('role')), str(m.get('value') or m.get('content'))[:150])
PY
