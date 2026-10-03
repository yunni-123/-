#!/usr/bin/env python3
"""生成每个 repo 的期望关键数值（来自同仓 pristine 基线 observations.csv）。

这些期望值是「论文宣称的结果」——合法的诊断输入（用户提供的目标），不是答案。
答案（期望根因）在 defect.json，judge 阶段才使用。
"""
import csv, json, os, sys

ROOT = "/root/repro-agent-bench"

def main():
    obs = {}
    with open(os.path.join(ROOT, "observations.csv"), newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            obs[row["variant"]] = row
    out = {}
    for variant, row in obs.items():
        if row["defect"] == "pristine":
            out[row["repo"]] = json.loads(row["key_outputs"])
    path = os.path.join(ROOT, "eval", "expected_values.json")
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False))

if __name__ == "__main__":
    main()
