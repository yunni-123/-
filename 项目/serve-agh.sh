#!/bin/bash
# AGH serve 启动脚本（WSL 内运行）
# AGNES_MCP_STDIO_ALLOWLIST：部署策略 stdio 可执行文件白名单（逗号分隔）
#   本项目 MCP 服务器用 /usr/bin/python3 跑 mcp_server.py
cd /root/agnes-harness
export AGNES_MCP_STDIO_ALLOWLIST="/usr/bin/python3"
exec node packages/cli/dist/local/agnes.mjs serve
