#!/usr/bin/env python3
"""边界测试（06 手册 §7.1）：空仓库 / 缺 requirements / 缺入口文件。

期望：工具明确报「无法解析/未找到」，不崩溃。
"""
import json, os, shutil, subprocess, sys

ROOT = "/root/repro-agent-bench"
BENCH = os.path.join(ROOT, "boundary")
PY = "/usr/bin/python3"
TOOL = os.path.join(ROOT, "tools")
results = []

# 构造三个边界样例
shutil.rmtree(BENCH, ignore_errors=True)
os.makedirs(os.path.join(BENCH, "empty_repo"))                       # 完全空目录
d = os.path.join(BENCH, "missing_requirements")
os.makedirs(d)
open(os.path.join(d, "main.py"), "w").write('import numpy as np\n'
                                            'print(f"peak = {np.sin(1.0):.4f}")\n')      # 无 requirements.txt
d = os.path.join(BENCH, "missing_entry")
os.makedirs(d)
open(os.path.join(d, "requirements.txt"), "w").write("numpy>=1.24\n")                   # 无 main.py

def rpc_call(method, params):
    """直接对 mcp_server.py 发 JSON-RPC（等价于 AGH 侧 tools/call，但离线）。"""
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    init = json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                      "params": {"protocolVersion": "2024-11-05",
                                  "clientInfo": {"name": "boundary-test", "version": "0"}}})
    p = subprocess.run([PY, os.path.join(ROOT, "mcp_server.py")],
                       input=init + "\n" + req + "\n", capture_output=True, text=True, timeout=60)
    for line in p.stdout.splitlines():
        try:
            o = json.loads(line)
            if o.get("id") == 1:
                if "error" in o:
                    return {"_rpc_error": o["error"]}
                return json.loads(o["result"]["content"][0]["text"])
        except (json.JSONDecodeError, KeyError):
            continue
    return {"_no_response": p.stdout[-200:] + p.stderr[-200:]}

for name in ("empty_repo", "missing_requirements", "missing_entry"):
    path = os.path.join(BENCH, name)
    row = {"case": name, "path": path}
    for tool in ("inspect_repo", "build_env", "run_repo"):
        res = rpc_call("tools/call", {"name": tool, "arguments": {"repo_path": path}})
        row[tool] = res
        crashed = "Traceback" in json.dumps(res) or res.get("_no_response") is not None
        print(f"[{name}] {tool}: ok={res.get('ok')} err={str(res.get('error'))[:60]}")
    # 缺证据 -> 必须以『未知』上报，绝不可判为可复现
    row["diagnose_missing_evidence"] = rpc_call(
        "tools/call", {"name": "diagnose", "arguments": {"evidence_json": "{}"}})
    # 正例：证据齐全的完好仓库 -> 应判『可复现（无缺陷）』，确认守卫未误伤正常路径
    row["diagnose_clean_evidence"] = rpc_call(
        "tools/call", {"name": "diagnose", "arguments": {"evidence_json": json.dumps({
            "build_env": {"all_resolvable": True, "requirements": []},
            "run": {"consistent": True, "runs": [{"exit_code": 0}, {"exit_code": 0}]},
            "compare": [{"within_tol": True}],
        })}})
    # 断言
    _miss = row["diagnose_missing_evidence"]
    assert _miss.get("ok") is False, "缺证据时 diagnose 必须返回 ok=False"
    assert _miss.get("root_cause") == "未知", "缺证据时根因必须为『未知』"
    assert _miss.get("reported_as_unknown") is True, "缺证据时必须标记 reported_as_unknown"
    _clean = row["diagnose_clean_evidence"]
    assert _clean.get("root_cause") == "可复现（无缺陷）", "证据齐全时不应被误伤"
    print("  [断言通过] 缺证据 -> 未知；证据齐全 -> 可复现")
    results.append(row)

with open(os.path.join(ROOT, "results", "boundary_results.json"), "w") as f:
    json.dump(results, f, ensure_ascii=False, indent=1)
print("boundary done")
