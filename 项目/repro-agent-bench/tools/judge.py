#!/usr/bin/env python3
"""judge：把 B1/B2/B3 结果与 ground-truth 对齐，输出 agent_results.csv + 三方案对比表 + 失败样例分析。

ground-truth：每个变体目录内的 defect.json（拷贝进 eval 时保留，Agent 看不到——
它只会出现在 judge 侧）。标签归一：defect.json 的 root_cause 为中文标签
（如「依赖版本问题」「无缺陷（对照组）」），与 Agent 标签表对齐（pristine 组
ground-truth 归一为「可复现（无缺陷）」。
"""
import csv, json, os, re, sys, time

ROOT = "/root/repro-agent-bench"
LABELS = {
    "dep_typo": "依赖版本问题",
    "env_cuda": "环境不匹配",
    "no_seed": "随机性未固定",
    "data_leakage": "数据泄漏（目标泄漏特征）",
    "unit_confusion": "单位换算错误",
    "numerical_instability": "数值不稳定",
    "silent_truncation": "静默截断",
    "pristine": "可复现（无缺陷）",
}

def norm(text):
    """从 Agent 自由文本里抽取根因标签（优先匹配固定标签表）。"""
    if not text:
        return None
    best, best_pos = None, None
    for canon in list(LABELS.values()) + ["未知"]:
        i = text.find(canon)
        if i >= 0 and (best is None or i < best_pos or (i == best_pos and len(canon) > len(best))):
            best, best_pos = canon, i
    return best

def main():
    mapping = json.load(open(os.path.join(ROOT, "eval", "mapping.json")))
    rows, fail_rows = [], []
    for m in mapping:
        defect = m["defect"]
        gt_rc = LABELS[defect]
        gt_rep = defect == "pristine"
        # --- B3 ---
        b3f = os.path.join(ROOT, "results", "b3", m["eval"] + ".md")
        b3_text = open(b3f, encoding="utf-8").read() if os.path.exists(b3f) else ""
        verdict = None
        mm = re.findall(r"判定:\s*root_cause=([^\s]+)\s*reproducible=(true|false)\s*confidence=([0-9.]+)", b3_text)
        if mm:
            rc, rep, conf = mm[-1]
            verdict = {"root_cause": rc, "reproducible": rep == "true", "confidence": float(conf)}
        b3_rc_text = verdict["root_cause"] if verdict else (norm(b3_text) or "（缺失）")
        b3_rep = verdict["reproducible"] if verdict else None
        b3_conf = verdict["confidence"] if verdict else None
        b3_correct = 1 if (b3_rep is not None and b3_rep == gt_rep
                           and b3_rc_text in (gt_rc, "可复现（无缺陷）") and defect == "pristine") \
                          else (1 if (b3_rep is not None and b3_rep == gt_rep and b3_rc_text == gt_rc) else 0)
        b3_rc_correct = 1 if b3_rc_text == gt_rc else 0
        # --- B2 ---
        b2f = os.path.join(ROOT, "results", "b2", m["eval"] + ".json")
        b2 = json.load(open(b2f)) if os.path.exists(b2f) else {}
        b2_rc = b2.get("root_cause")
        b2_rep = b2.get("reproducible")
        b2_correct = 1 if (b2_rep is not None and b2_rep == gt_rep and b2_rc == gt_rc) else 0
        # --- B1 ---
        b1f = os.path.join(ROOT, "results", "b1", m["eval"] + ".json")
        b1 = json.load(open(b1f)) if os.path.exists(b1f) else {}
        b1_rep = b1.get("reproducible")
        b1_correct = 1 if (b1_rep == gt_rep and defect == "pristine") else 0  # B1 无根因能力，缺陷组必错
        rows.append({
            "eval": m["eval"], "variant": m["variant"], "defect": defect,
            "gt_root_cause": gt_rc, "gt_reproducible": gt_rep,
            "b1_root_cause": "未知（无根因能力）", "b1_reproducible": b1_rep,
            "b1_correct": b1_correct, "b1_elapsed_s": b1.get("elapsed_s"),
            "b2_root_cause": b2_rc, "b2_reproducible": b2_rep,
            "b2_correct": b2_correct, "b2_elapsed_s": b2.get("elapsed_s"),
            "b3_root_cause": b3_rc_text, "b3_reproducible": b3_rep,
            "b3_confidence": b3_conf, "b3_correct": b3_correct, "b3_rc_correct": b3_rc_correct,
        })
        if not (b3_correct and b3_rc_correct):
            fail_rows.append(m)

    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    cols = ["eval", "variant", "defect", "gt_root_cause", "gt_reproducible",
            "b1_root_cause", "b1_reproducible", "b1_correct", "b1_elapsed_s",
            "b2_root_cause", "b2_reproducible", "b2_correct", "b2_elapsed_s",
            "b3_root_cause", "b3_reproducible", "b3_confidence", "b3_correct", "b3_rc_correct"]
    with open(os.path.join(ROOT, "results", "agent_results.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)

    n = len(rows)
    def acc(rows_, k):
        v = [r[k] for r in rows_ if r[k] is not None]
        return (sum(v) / len(v)) if v else None
    def count(rows_, k, v=True):
        return sum(1 for r in rows_ if r[k] == v)
    dep = [r for r in rows if r["defect"] == "dep_typo"]
    pri = [r for r in rows if r["defect"] == "pristine"]

    report = []
    report.append(f"# 三方案对比表（基准集 19 变体）\n")
    report.append(f"生成时间：{time.strftime('%Y-%m-%d %H:%M %Z')}（本机 WSL）\n")
    report.append("| 指标 | B1 朴素脚本 | B2 大模型看报错 | B3 本方案（AGH+MCP+Skill） |")
    report.append("|---|---|---|---|")
    report.append(f"| 根因定位准确率（{n}） | 0/{n}（无根因能力） | {acc(rows, 'b2_correct'):.2f} ({count(rows,'b2_correct')}/{n}) | {acc(rows, 'b3_rc_correct'):.2f} ({count(rows,'b3_rc_correct')}/{n}) |")
    report.append(f"| 可复现性判断准确率（{n}） | {acc(rows, 'b1_correct'):.2f} | {acc(rows, 'b2_correct'):.2f} | {acc(rows, 'b3_correct'):.2f} |")
    report.append(f"| 假阳性率（pristine {len(pri)}） | {count(pri, 'b1_correct') is not None and (len(pri)-count(pri,'b1_correct'))/len(pri):.2f} | {(len(pri)-count(pri,'b2_correct'))/len(pri):.2f} | {(len(pri)-count(pri,'b3_correct'))/len(pri):.2f} |")
    report.append(f"| 依赖缺陷检出率（dep_typo {len(dep)}） | {count(dep, 'b1_correct')}/{len(dep)}* | {count(dep, 'b2_correct')}/{len(dep)} | {count(dep, 'b3_rc_correct')}/{len(dep)} |")
    report.append(f"| 平均耗时（s/变体） | {sum(r['b1_elapsed_s'] or 0 for r in rows)/n:.1f} | {sum(r['b2_elapsed_s'] or 0 for r in rows)/n:.1f} | 见 04-模型使用记录 |\n")
    report.append("> \\* B1 对缺陷组全部报「可复现」（跑一次 exit=0 即判好），根因恒为未知；表中 dep 检出按可复现性误判计数。")
    report.append("\n## 失败样例（B3 未完全正确的变体）")
    if fail_rows:
        for m in fail_rows:
            r = next(x for x in rows if x["eval"] == m["eval"])
            report.append(f"- **{m['eval']}** `{m['variant']}`：期望 {r['gt_root_cause']}/{r['gt_reproducible']}，"
                          f"B3 判 {r['b3_root_cause']}/{r['b3_reproducible']}（conf={r['b3_confidence']}）")
    else:
        report.append("- 无（B3 全对）")
    open(os.path.join(ROOT, "results", "三方案对比表.md"), "w", encoding="utf-8").write("\n".join(report))
    print("\n".join(report))

if __name__ == "__main__":
    main()
