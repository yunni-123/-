#!/usr/bin/env python3
"""B3 批量驱动：AGH agent + skill + MCP 六步闭环。

方法学要点：eval 目录做了中性化（eval_01...），OBS 按 basename 查不到登记，
因此「论文宣称的期望值」（= 同仓 pristine 基线）由 prompt 注入——这是合法诊断输入，
而非答案（答案 = defect.json 的根因标签，judge 阶段才使用）。
逐个跑（并发 AGH 会话会 SESSION_BUSY），结果落盘 results/b3/<eval>.md。
"""
import json, os, subprocess, time, sys

ROOT = "/root/repro-agent-bench"
AGH = ["node", "packages/cli/dist/local/agnes.mjs"]
LABELS = "可复现（无缺陷）、随机性未固定、数据泄漏（目标泄漏特征）、单位换算错误、数值不稳定、静默截断、环境不匹配、依赖版本问题、未知"

def build_prompt(m, expected):
    exp = ", ".join(f"{k}={v}" for k, v in expected.items()) if expected else "（未提供）"
    return (
        f"使用 repro-diagnosis skill 诊断 /root/repro-agent-bench/eval/{m['eval']} 的可复现性。\n"
        f"该仓库论文宣称的期望关键数值：{exp}（请逐项用 compare_numbers 比对）。\n"
        "按 6 步闭环执行：inspect_repo → build_env → run_repo(两次) → compare_numbers → diagnose → "
        "第6步（若有缺陷：get_source 读源码定位缺陷行，做最小修复，用 verify_fix 在 /tmp 沙箱验证修复后数值回到期望；"
        "若无缺陷：说明无需修复）。不得修改原仓库。\n"
        "最后输出诊断报告，最后一行必须为固定格式：\n"
        f"判定: root_cause=<标签> reproducible=<true|false> confidence=<0-1小数>\n"
        f"标签必须逐字取自：{LABELS}"
    )

def toolchain_available() -> bool:
    """预检：确认 MCP repro-tools 在本会话可用。不可用则本轮结果无效。"""
    probe_prompt = ("调用 inspect_repo 检查 /root/repro-agent-bench/eval/eval_04，"
                    "只回一行：工具名 + 是否成功。")
    # 探针的 cwd 是 /root/repro-agent-bench，相对 AGH 路径解析不到，须用绝对路径
    agh_abs = ["node", "/root/agnes-harness/packages/cli/dist/local/agnes.mjs"]
    try:
        r = subprocess.run(agh_abs + ["-p", probe_prompt], cwd="/root/repro-agent-bench",
                           capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return False
    blob = r.stdout + r.stderr
    return "inspect_repo" in blob

def main():
    mapping = json.load(open(os.path.join(ROOT, "eval", "mapping.json")))
    expected = json.load(open(os.path.join(ROOT, "eval", "expected_values.json")))
    out_dir = os.path.join(ROOT, "results", "b3")
    os.makedirs(out_dir, exist_ok=True)
    only = sys.argv[1:] if len(sys.argv) > 1 else [m["eval"] for m in mapping]
    if not toolchain_available():
        print("!! MCP 工具链不可用，本轮全部中止；请检查 mcp status repro-tools 后重跑")
        sys.exit(3)
    print("toolchain probe: OK")
    for m in mapping:
        if m["eval"] not in only:
            continue
        f = os.path.join(out_dir, m["eval"] + ".md")
        if os.path.exists(f) and os.path.getsize(f) > 500:
            print(f"skip {m['eval']} (exists)"); continue
        prompt = build_prompt(m, expected.get(m["repo"], {}))
        t0 = time.monotonic()
        r = subprocess.run(AGH + ["-p", prompt], cwd="/root/agnes-harness",
                           capture_output=True, text=True, timeout=600)
        out = r.stdout + (("\n[stderr]\n" + r.stderr) if r.stderr.strip() else "")
        open(f, "w", encoding="utf-8").write(out)
        print(f"{m['eval']} done in {time.monotonic()-t0:.0f}s rc={r.returncode} -> {m['variant']}")
    print("B3 done")

if __name__ == "__main__":
    main()
