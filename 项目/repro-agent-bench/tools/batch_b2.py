#!/usr/bin/env python3
"""B2 基线：大模型看报错。

定义（06 手册）：把 stderr（+代码+requirements）丢给模型一次，不执行验证、不跑两次、
无工具链、无回退。数据收集阶段用一个朴素脚本跑一次 main.py 取输出，然后单次 LLM 调用裁决。
模型：agnes-3.0-flash（OpenAI 兼容 API）。
输出：results/b2/<eval>.json = {root_cause, reproducible, confidence, ...}
"""
import json, os, re, subprocess, time, urllib.request

ROOT = "/root/repro-agent-bench"
PY = "/usr/bin/python3"
API = "https://api.agnes-ai.cn/v1/chat/completions"
KEY = os.environ.get("AGNES_KEY", "")
MODEL = "agnes-3.0-flash"

LABELS = ["可复现（无缺陷）", "随机性未固定", "数据泄漏（目标泄漏特征）", "单位换算错误",
          "数值不稳定", "静默截断", "环境不匹配", "依赖版本问题", "未知"]

PROMPT = """你是科研计算可复现性诊断专家。下面是一个科研计算仓库的代码与一次运行结果。
请判断其根因与可复现性。你没有任何执行/验证工具，只能基于给出的文本推理。

根因标签必须逐字取自以下列表之一：{labels}
可复现性：true = 结果可复现且与期望一致；false = 不可复现或有缺陷。

要求：只输出一个 JSON 对象，不要其他文字：
{{"root_cause": "<标签>", "reproducible": <true|false>, "confidence": <0-1>, "reason": "<一句话理由>"}}

--- 仓库文件 ---
{files}

--- 一次运行结果（仅用于观察，非可复现性判定依据） ---
exit_code: {exit}
stdout: {stdout}
stderr: {stderr}
"""

def llm(prompt: str) -> dict:
    req = urllib.request.Request(API, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"},
        data=json.dumps({"model": MODEL, "temperature": 0,
                         "messages": [{"role": "user", "content": prompt}]}).encode())
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    text = data["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {"raw": text, "parse_error": True}

def main():
    global KEY
    keyfile = "/root/.agh/secrets/agnes-ai/account-541870c1c9bcbd925407fcca-r1"
    if os.path.exists(keyfile):
        raw = open(keyfile).read().strip()
        try:
            KEY = json.loads(raw).get("value", raw)
        except json.JSONDecodeError:
            KEY = raw
    mapping = json.load(open(os.path.join(ROOT, "eval", "mapping.json")))
    out_dir = os.path.join(ROOT, "results", "b2")
    os.makedirs(out_dir, exist_ok=True)
    for m in mapping:
        eval_dir = os.path.join(ROOT, "eval", m["eval"])
        p = subprocess.run([PY, "main.py"], cwd=eval_dir, capture_output=True,
                           text=True, timeout=120)
        files, seen = [], set()
        for fn in sorted(os.listdir(eval_dir)):
            if fn in ("defect.json",) or fn in seen:
                continue
            if os.path.getsize(os.path.join(eval_dir, fn)) < 20000:
                files.append(f"### {fn}\n{open(os.path.join(eval_dir, fn), encoding='utf-8').read()}")
        prompt = PROMPT.format(labels="、".join(LABELS), files="\n\n".join(files),
                               exit=p.returncode, stdout=p.stdout[-800:], stderr=p.stderr[-800:])
        t0 = time.monotonic()
        try:
            res = llm(prompt)
        except Exception as e:
            res = {"error": f"{type(e).__name__}: {e}"}
        out = {
            "eval": m["eval"], "variant": m["variant"],
            "root_cause": res.get("root_cause", "未知"),
            "reproducible": res.get("reproducible"),
            "confidence": res.get("confidence"),
            "reason": res.get("reason", ""),
            "elapsed_s": round(time.monotonic() - t0, 1),
            "parse_error": res.get("parse_error", False),
            "error": res.get("error"),
        }
        with open(os.path.join(out_dir, m["eval"] + ".json"), "w") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"{m['eval']} -> {out['root_cause']} rep={out['reproducible']} conf={out['confidence']} {out['elapsed_s']}s")
    print("B2 done:", len(mapping))

if __name__ == "__main__":
    main()
