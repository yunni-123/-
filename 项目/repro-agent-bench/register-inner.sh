#!/bin/bash
cd /root/agnes-harness
AGH="node packages/cli/dist/local/agnes.mjs"
get_rev() { $AGH mcp get repro-tools 2>/dev/null | grep -oE "revision=[0-9a-f]+" | head -1 | sed "s/revision=//"; }
echo "@@@ mcp status before @@@"
$AGH mcp status repro-tools 2>&1 | head -2
R1="$(get_rev)"; echo "@@@ R1=$R1 @@@"
echo "@@@ STEP reconnect @@@"
$AGH mcp reconnect repro-tools --expected-revision "$R1" 2>&1 | head -5
R2="$(get_rev)"; echo "@@@ R2=$R2 @@@"
echo "@@@ STEP status after @@@"
$AGH mcp status repro-tools 2>&1 | head -2
echo "@@@ STEP tools @@@"
$AGH mcp tools repro-tools 2>&1 | head -10
echo "@@@ DONE @@@"
