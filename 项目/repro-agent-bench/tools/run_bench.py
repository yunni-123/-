# -*- coding: utf-8 -*-
"""跑一遍基准集，记录每个变体的执行结果与观测签名。

产出 observations.csv：变体 / 期望根因 / 退出码 / 关键输出 / 是否可复现
这份 CSV 就是 judge.py 判定"基线（直接跑）能不能给出根因"的依据。
"""
import csv
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VARIANTS = os.path.join(ROOT, "variants")

# 每个基础仓库的关键输出行前缀（用于提取数值）
KEY_PREFIX = {
    "sinusoid-fit": ["amplitude", "frequency"],
    "linreg-pipeline": ["test_r2"],
    "illcond-solve": ["cond(A)", "relative_residual"],
    "units-pipeline": ["distance_m", "frequency_hz", "path_loss_db", "received_power_dbm"],
}


def run_once(repo_dir, timeout=60):
    try:
        p = subprocess.run(
            [sys.executable, "main.py"],
            cwd=repo_dir, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "TIMEOUT"


def extract_key_outputs(stdout):
    out = {}
    for line in stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def main():
    rows = []
    for name in sorted(os.listdir(VARIANTS)):
        d = os.path.join(VARIANTS, name)
        if not os.path.isdir(d):
            continue
        meta_path = os.path.join(d, "defect.json")
        meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {}

        rc1, so1, se1 = run_once(d)
        rc2, so2, _ = run_once(d)
        # 可复现性：两次输出是否一致
        deterministic = (so1 == so2)
        keys = extract_key_outputs(so1)

        rows.append({
            "variant": name,
            "repo": meta.get("repo", ""),
            "defect": meta.get("defect", ""),
            "expected_root_cause": meta.get("root_cause", ""),
            "expected_reproducible": meta.get("reproducible", ""),
            "exit_code": rc1,
            "deterministic": deterministic,
            "key_outputs": json.dumps(keys, ensure_ascii=False),
            "stderr_head": (se1.strip().splitlines() or [""])[-1][:160],
        })

    out_csv = os.path.join(ROOT, "observations.csv")
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("写出 %s（%d 行）\n" % (out_csv, len(rows)))

    # 打印一张人类可读的观测表
    print("%-42s %-7s %-6s %s" % ("变体", "退出码", "确定性", "关键输出 / 期望根因"))
    print("-" * 130)
    for r in rows:
        note = r["key_outputs"] if r["exit_code"] == 0 else ("ERR: " + r["stderr_head"])
        print("%-42s %-7s %-6s %s" % (
            r["variant"], r["exit_code"], "是" if r["deterministic"] else "否", note[:70]))
        print("%-42s %-7s %-6s -> 期望根因: %s" % ("", "", "", r["expected_root_cause"]))


if __name__ == "__main__":
    main()
