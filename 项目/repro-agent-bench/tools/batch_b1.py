#!/usr/bin/env python3
"""B1 基线：朴素脚本。

定义（06 手册）：只跑一次 main.py，无根因能力、无模型、无工具。
输出：reproducible = (exit_code == 0)，root_cause 恒为「未知（无根因能力）」。
"""
import json, os, subprocess, time

ROOT = "/root/repro-agent-bench"
PY = "/usr/bin/python3"

def main():
    mapping = json.load(open(os.path.join(ROOT, "eval", "mapping.json")))
    out_dir = os.path.join(ROOT, "results", "b1")
    os.makedirs(out_dir, exist_ok=True)
    for m in mapping:
        eval_dir = os.path.join(ROOT, "eval", m["eval"])
        t0 = time.monotonic()
        try:
            p = subprocess.run([PY, "main.py"], cwd=eval_dir, capture_output=True,
                               text=True, timeout=120)
            res = {"exit_code": p.returncode, "stdout_tail": p.stdout[-600:],
                   "stderr_tail": p.stderr[-600:]}
        except subprocess.TimeoutExpired:
            res = {"exit_code": None, "timeout": True}
        elapsed = time.monotonic() - t0
        out = {
            "eval": m["eval"], "variant": m["variant"],
            "reproducible": res.get("exit_code") == 0,
            "root_cause": "未知（无根因能力）",
            "confidence": None,
            "elapsed_s": round(elapsed, 1),
            "raw": res,
        }
        with open(os.path.join(out_dir, m["eval"] + ".json"), "w") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"{m['eval']} exit={res.get('exit_code')} rep={out['reproducible']} {out['elapsed_s']}s")
    print("B1 done:", len(mapping))

if __name__ == "__main__":
    main()
