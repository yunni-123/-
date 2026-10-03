#!/bin/bash
# B3 全量批量：AGH agent + repro-diagnosis skill + repro-tools MCP
cd /root/repro-agent-bench
python3 tools/batch_b3.py 2>&1
echo "ALL_DONE $(date -u)"
