#!/bin/bash
cd /root/repro-agent-bench
cp "/mnt/c/Users/DELL/Documents/deepseek-harness/default-workspace/agnes-hackathon-2026/项目/repro-agent-bench/mcp_server.py" .
python3 -m py_compile mcp_server.py || exit 1
echo "SYNTAX_OK"
python3 -c "
import json, subprocess
reqs = [
  json.dumps({\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"clientInfo\":{\"name\":\"t\",\"version\":\"0\"}}}),
  json.dumps({\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/list\",\"params\":{}}),
]
r = subprocess.run([\"python3\",\"mcp_server.py\"], input=chr(10).join(reqs)+chr(10), capture_output=True, text=True)
for l in r.stdout.splitlines():
    o = json.loads(l)
    if o.get(\"id\")==2:
        print([t[\"name\"] for t in o[\"result\"][\"tools\"]])
"
cd /root/agnes-harness
AGH="node packages/cli/dist/local/agnes.mjs"
REV=$($AGH mcp get repro-tools 2>/dev/null | grep -oE "revision=[0-9a-f]+" | head -1 | sed "s/revision=//")
echo "REV=$REV"
$AGH mcp reconnect repro-tools --expected-revision "$REV"
$AGH mcp status repro-tools
