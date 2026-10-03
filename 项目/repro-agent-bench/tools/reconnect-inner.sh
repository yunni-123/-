#!/bin/bash
cd /root/repro-agent-bench
# 更新 register-inner.sh 为 reconnect 流程，再用 ptyrun 跑
cat > register-inner.sh <<'INNER'
#!/bin/bash
cd /root/agnes-harness
AGH="node packages/cli/dist/local/agnes.mjs"
get_rev() { $AGH mcp get repro-tools 2>/dev/null | grep -oE "revision=[0-9a-f]+" | head -1 | sed "s/revision=//"; }
echo "@@@ STATUS BEFORE @@@"
$AGH mcp status repro-tools 2>&1 | head -2
R1="$(get_rev)"; echo "@@@ R1=$R1 @@@"
echo "@@@ STEP reconnect @@@"
$AGH mcp reconnect repro-tools --expected-revision "$R1" 2>&1 | head -8
R2="$(get_rev)"; echo "@@@ R2=$R2 @@@"
echo "@@@ STATUS AFTER @@@"
$AGH mcp status repro-tools 2>&1 | head -2
echo "@@@ TOOLS @@@"
$AGH mcp tools repro-tools 2>&1 | head -12
echo "@@@ DONE @@@"
INNER
chmod +x register-inner.sh
python3 ptyrun.py
echo "PTX_EXIT=$?"
grep -E "@@@|ok|error|revision" pty-register.log | tail -30
